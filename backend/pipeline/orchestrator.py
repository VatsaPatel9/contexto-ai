"""Core tutoring pipeline orchestrator.

Ties together PII scrubbing, offensive-language filtering, prompt-injection
detection, message classification, RAG retrieval, LLM streaming, output
validation, citation formatting, and risk escalation into a single async
generator that produces Server-Sent Events.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from backend.llm.client import LLMClient
from backend.llm.humanizer import humanize_response
from backend.models.conversation import Conversation, Message
from backend.models.dataset import Dataset
from backend.models.user_course import UserCourse
from backend.models.user_flags import FlagLevel, UserFlagService
from backend.models.user_profile import get_or_create_profile
from backend.config import Settings

# Pipeline filters (existing)
from backend.pipeline_filters.pii_scrubber_filter import PIIScrubber
from backend.pipeline_filters.offensive_language_filter import check_message as check_offensive
from backend.pipeline_filters.prompt_injection_filter import PromptInjectionFilter
from backend.pipeline_filters.attempt_first_filter import classify_message, detect_attempt
from backend.pipeline_filters.output_validation_filter import OutputValidationFilter

# Utilities
from backend.utils.citation_formatter import CitationFormatter, SourceChunk
from backend.services.escalation_service import EscalationService

logger = logging.getLogger(__name__)

# Path to the tutor persona system prompt
_PERSONA_PATH = Path(__file__).resolve().parent.parent / "tutor_persona.md"

# Cached system prompt text (loaded once)
_SYSTEM_PROMPT_CACHE: Optional[str] = None


def _load_system_prompt() -> str:
    """Load and cache the tutor persona system prompt from disk."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        _SYSTEM_PROMPT_CACHE = _PERSONA_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT_CACHE


def _sse(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


# Pre-built filter instances (stateless enough to reuse)
_pii_scrubber = PIIScrubber()
_injection_filter = PromptInjectionFilter()
_output_validator = OutputValidationFilter()
_citation_formatter = CitationFormatter()
_escalation_service = EscalationService()

# Policy messages
_OFFENSIVE_BLOCK_MSG = (
    "Your message was blocked because it contained language that violates our "
    "community guidelines. Please rephrase your question respectfully and "
    "I'll be happy to help."
)

_INJECTION_BLOCK_MSG = (
    "I appreciate the creativity, but I'm here to help you learn course "
    "material. Could you rephrase your question about the topic you're studying?"
)

_ATTEMPT_FIRST_MSG = (
    "I'd love to help you with this! Before I do, could you share what "
    "you've tried so far? Even a rough idea or a first step is great. "
    "Showing your thinking helps me give you the best guidance."
)


def _list_available_docs(db: Session, dataset_id) -> list[dict]:
    """One representative line per active doc in a dataset.

    Used to populate "here's what I can help with" responses — both on
    refusals (so the user knows how to retry) and on explicit meta
    questions like "what topics can you help with?".
    """
    from backend.models.dataset import Document, DocumentSegment

    docs = (
        db.query(Document)
        .filter(
            Document.dataset_id == dataset_id,
            Document.deleted_at.is_(None),
            Document.status == "ready",
        )
        .order_by(Document.created_at.desc())
        .limit(30)
        .all()
    )

    out: list[dict] = []
    for d in docs:
        first_seg = (
            db.query(DocumentSegment.content)
            .filter(DocumentSegment.document_id == d.id)
            .order_by(DocumentSegment.position)
            .first()
        )
        preview = ""
        if first_seg and first_seg.content:
            # Collapse whitespace, trim, take ~140 chars.
            text = " ".join(first_seg.content.split())
            preview = text[:140].rstrip()
            if len(text) > 140:
                preview += "…"
        out.append({"title": d.title, "preview": preview})
    return out


async def _generate_suggested_questions(
    llm: LLMClient,
    docs: list[dict],
    limit: int = 3,
) -> list[str]:
    """Ask the LLM for *limit* student-sounding questions grounded in the
    provided document previews. Returns [] on failure — caller is
    expected to render the block only if the list is non-empty.
    """
    if not docs or not llm:
        return []

    doc_list = "\n".join(
        f"- {d['title']}" + (f" — {d['preview']}" if d.get("preview") else "")
        for d in docs[:10]
    )
    system = (
        "You help a student discover what questions they can ask a course tutor. "
        "Given a list of available documents (title + short excerpt), return a JSON "
        "array of exactly " + str(limit) + " short, specific, student-friendly "
        "questions that can be answered from those documents. Favor concrete terms "
        "from the excerpts over generic phrasing. No preamble, no trailing text — "
        "only the JSON array. Example: [\"What is encapsulation?\", \"How does DFS differ from BFS?\", \"When to use private attributes?\"]"
    )
    user = f"Available documents:\n{doc_list}\n\nReturn the JSON array now."

    try:
        raw = await llm.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except Exception as exc:
        logger.warning("Suggested-questions call failed: %s", exc)
        return []

    # Extract the JSON array — LLMs sometimes wrap it in ```json fences.
    text = raw.strip()
    if text.startswith("```"):
        # strip opening fence
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Suggested-questions JSON parse failed: %r", raw[:200])
        return []

    if not isinstance(parsed, list):
        return []

    out: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            out.append(item.strip().rstrip("?") + "?")
        if len(out) >= limit:
            break
    return out


def _persist_early_exit(
    db: Session,
    *,
    conversation_id: str | None,
    user_id: str,
    course_id: str,
    user_query: str,
    msg_type: str,
    has_attempt: bool,
    assistant_content: str,
) -> str:
    """Create (or reuse) a conversation, save user + assistant messages, return the id.

    Used for every path that would otherwise return without persisting:
    offensive-language blocks, prompt-injection blocks, attempt-first refusal,
    and no-context refusal. Keeping these interactions in the DB preserves
    the sidebar thread and the audit trail.
    """
    conv_uuid = None
    if conversation_id:
        try:
            candidate = uuid.UUID(conversation_id)
            existing = db.query(Conversation).filter(Conversation.id == candidate).first()
            if existing is not None:
                conv_uuid = candidate
        except ValueError:
            conv_uuid = None

    if conv_uuid is None:
        new_conv = Conversation(
            user_id=user_id,
            course_id=course_id,
            name=user_query[:100],
            hint_level=0,
            interaction_count=0,
        )
        db.add(new_conv)
        db.flush()
        conv_uuid = new_conv.id

    db.add(Message(
        conversation_id=conv_uuid,
        role="user",
        content=user_query,
        message_type=msg_type,
        has_attempt=has_attempt,
    ))
    db.add(Message(
        conversation_id=conv_uuid,
        role="assistant",
        content=assistant_content,
        message_type=msg_type,
        has_attempt=False,
    ))
    db.commit()
    return str(conv_uuid)


async def process_chat_message(
    query: str,
    conversation_id: str | None,
    course_id: str,
    user_id: str,
    db: Session,
    retriever,  # Retriever instance (may be None)
    llm: LLMClient,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """Run the full tutoring pipeline and yield SSE-formatted chunks.

    This is the single entry point called by the chat endpoint.
    """
    now_ts = int(time.time())

    # ------------------------------------------------------------------
    # 0. Check ban status + token limit
    # ------------------------------------------------------------------
    flag_svc = UserFlagService(db)
    restriction = flag_svc.check_restricted(user_id)
    if restriction.flag_level == FlagLevel.SUSPENDED.value:
        yield _sse({
            "event": "error",
            "message": "Your account has been suspended due to policy violations. "
                       "Please contact your instructor or advisor.",
            "code": "account_suspended",
        })
        return

    # Token budget check
    profile = get_or_create_profile(db, user_id)
    if profile.token_limit is not None:
        total_used = profile.tokens_in + profile.tokens_out
        if total_used >= profile.token_limit:
            yield _sse({
                "event": "error",
                "message": "You have reached your token usage limit. "
                           "Please contact your administrator.",
                "code": "token_limit_reached",
            })
            return

    # ------------------------------------------------------------------
    # 1. PII scrub
    # ------------------------------------------------------------------
    scrub_result = _pii_scrubber.scrub(query)
    working_query = scrub_result.scrubbed_text

    # ------------------------------------------------------------------
    # 2. Offensive language check + flag recording
    # ------------------------------------------------------------------
    offense_result = check_offensive(working_query)
    if offense_result.is_offensive:
        msg_hash = UserFlagService._hash_message(working_query)
        category = offense_result.categories[0] if offense_result.categories else "unknown"
        offense_record = flag_svc.record_offense(
            user_id=user_id,
            severity=offense_result.severity,
            category=category,
            message_hash=msg_hash,
        )
        logger.warning(
            "Offensive language from user %s: severity=%s flag=%s",
            user_id, offense_result.severity, offense_record.new_flag_level,
        )

        if offense_record.new_flag_level == FlagLevel.SUSPENDED.value:
            suspend_msg = ("Your account has been suspended due to repeated policy violations. "
                           "Please contact your instructor or advisor.")
            conversation_id = _persist_early_exit(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                course_id=course_id,
                user_query=query,
                msg_type="blocked",
                has_attempt=False,
                assistant_content=suspend_msg,
            )
            yield _sse({
                "event": "error",
                "message": suspend_msg,
                "code": "account_suspended",
                "conversation_id": conversation_id,
            })
            return

        if offense_result.severity in ("moderate", "severe"):
            conversation_id = _persist_early_exit(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                course_id=course_id,
                user_query=query,
                msg_type="blocked",
                has_attempt=False,
                assistant_content=_OFFENSIVE_BLOCK_MSG,
            )
            yield _sse({
                "event": "error",
                "message": _OFFENSIVE_BLOCK_MSG,
                "code": "offensive_language",
                "conversation_id": conversation_id,
            })
            return

        # Mild offense: warn the user but continue processing
        total_offenses = offense_record.offense_count_mild + offense_record.offense_count_severe
        warnings_remaining = max(0, 3 - total_offenses)
        if warnings_remaining > 0:
            warning_msg = (
                f"Warning: your message contained language that may violate our guidelines. "
                f"You have {warnings_remaining} warning(s) remaining before your account is restricted. "
                f"Please keep the conversation respectful."
            )
        else:
            warning_msg = (
                "Final warning: your account has been restricted due to repeated violations. "
                "One more violation will result in a permanent ban."
            )
        yield _sse({
            "event": "message",
            "answer": warning_msg + "\n\n",
            "conversation_id": conversation_id or "",
            "message_id": "",
            "created_at": now_ts,
        })

    # ------------------------------------------------------------------
    # 3. Prompt injection check
    # ------------------------------------------------------------------
    injection_result = _injection_filter.check_injection(working_query)
    if injection_result.is_injection:
        conversation_id = _persist_early_exit(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            course_id=course_id,
            user_query=query,
            msg_type="blocked",
            has_attempt=False,
            assistant_content=_INJECTION_BLOCK_MSG,
        )
        yield _sse({
            "event": "error",
            "message": _INJECTION_BLOCK_MSG,
            "code": "prompt_injection",
            "conversation_id": conversation_id,
        })
        return

    # ------------------------------------------------------------------
    # 4. Classify message
    # ------------------------------------------------------------------
    classification = classify_message(working_query)
    msg_type = classification.message_type

    # ------------------------------------------------------------------
    # 5. Attempt check (homework only)
    # ------------------------------------------------------------------
    has_attempt = False
    if msg_type == "homework":
        attempt = detect_attempt(working_query)
        has_attempt = attempt.has_attempt
        if not attempt.has_attempt:
            conversation_id = _persist_early_exit(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                course_id=course_id,
                user_query=query,
                msg_type=msg_type,
                has_attempt=False,
                assistant_content=_ATTEMPT_FIRST_MSG,
            )
            yield _sse({
                "event": "message",
                "answer": _ATTEMPT_FIRST_MSG,
                "conversation_id": conversation_id,
                "message_id": "",
                "created_at": now_ts,
            })
            yield _sse({"event": "message_end", "conversation_id": conversation_id, "message_id": "", "metadata": {}})
            return

    # ------------------------------------------------------------------
    # 6. Load conversation history
    # ------------------------------------------------------------------
    history_messages: list[dict] = []
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id)
            past = (
                db.query(Message)
                .filter(Message.conversation_id == conv_uuid)
                .order_by(Message.created_at.asc())
                .limit(20)
                .all()
            )
            for m in past:
                history_messages.append({"role": m.role, "content": m.content})
        except (ValueError, Exception) as exc:
            logger.warning("Failed to load conversation history: %s", exc)

    # ------------------------------------------------------------------
    # 7. RAG retrieve
    # ------------------------------------------------------------------
    # Resolve dataset for the requested course_id, then check membership.
    # If the user isn't enrolled in this course (and isn't an admin/owner),
    # we silently fall back to baseline-only retrieval — they still get
    # super_admin-uploaded baseline content but no course-private materials.
    source_chunks: list[SourceChunk] = []
    dataset = (
        db.query(Dataset).filter(Dataset.course_id == course_id).first()
        if course_id
        else None
    )
    effective_dataset_id: str | None = None
    if dataset:
        is_enrolled = (
            db.query(UserCourse)
            .filter(UserCourse.user_id == user_id, UserCourse.dataset_id == dataset.id)
            .first()
            is not None
        )
        is_owner = dataset.created_by == user_id
        if is_enrolled or is_owner:
            effective_dataset_id = str(dataset.id)
    if retriever:
        try:
            source_chunks = retriever.retrieve(
                working_query,
                effective_dataset_id,
                top_k=settings.rag_top_k,
                score_threshold=settings.rag_score_threshold,
                user_id=user_id,
            )
        except Exception as exc:
            logger.error("RAG retrieval failed: %s", exc)

    # ------------------------------------------------------------------
    # 7b. STRICT: Refuse if no relevant context found in vectors
    # Only allow meta questions (greetings, "who are you") without context
    # ------------------------------------------------------------------
    # Only sample topic previews from a dataset the user is allowed to read,
    # otherwise we'd leak course content to unenrolled users.
    has_content = False
    topic_snippets: list[str] = []
    if dataset and effective_dataset_id:
        try:
            from backend.models.dataset import Document
            has_content = (
                db.query(Document)
                .filter(Document.dataset_id == dataset.id, Document.deleted_at.is_(None), Document.status == "ready")
                .first()
            ) is not None

            if has_content:
                # Grab the first ~100 chars from a few diverse segments for topic awareness
                sample_rows = (
                    db.query(DocumentSegment.content)
                    .filter(DocumentSegment.dataset_id == dataset.id)
                    .order_by(DocumentSegment.position)
                    .limit(5)
                    .all()
                )
                topic_snippets = [row.content[:120] for row in sample_rows]
        except Exception:
            pass

    if msg_type != "meta" and not source_chunks:
        if has_content and effective_dataset_id:
            available_docs = _list_available_docs(db, dataset.id)
            if available_docs:
                docs_block = "\n".join(
                    f"- **{d['title']}**" + (f" — {d['preview']}" if d['preview'] else "")
                    for d in available_docs
                )
                no_context_msg = (
                    "I don't see that topic in the uploaded course materials. "
                    "Here's what I can help with:\n\n"
                    f"{docs_block}\n\n"
                    "Ask me about any of these, or rephrase your question. "
                    "If you think this topic should be added, check with your instructor."
                )
                # Concrete-questions block. Emitted as a machine-parsed
                # `suggestions` fence (same pattern as the citations fence)
                # so the frontend can render them as clickable chips that
                # submit the question when tapped.
                suggestions = await _generate_suggested_questions(llm, available_docs)
                if suggestions:
                    no_context_msg += (
                        "\n\n```suggestions\n"
                        + json.dumps(suggestions)
                        + "\n```"
                    )
            else:
                no_context_msg = (
                    "I don't see that topic in the uploaded course materials. "
                    "Try rephrasing your question, or ask your instructor if this "
                    "topic should be added."
                )
        else:
            no_context_msg = (
                "No course materials have been uploaded yet. "
                "Please ask your instructor to upload content so I can help you learn.\n\n"
                "In the meantime, feel free to say hi!"
            )
        conversation_id = _persist_early_exit(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            course_id=course_id,
            user_query=query,
            msg_type=msg_type,
            has_attempt=has_attempt,
            assistant_content=no_context_msg,
        )
        yield _sse({
            "event": "message",
            "answer": no_context_msg,
            "conversation_id": conversation_id,
            "message_id": "",
            "created_at": now_ts,
        })
        yield _sse({"event": "message_end", "conversation_id": conversation_id, "message_id": "", "metadata": {}})
        return

    # ------------------------------------------------------------------
    # 8. Build prompt messages
    # ------------------------------------------------------------------
    system_prompt = _load_system_prompt()
    # Replace [COURSE] with a description inferred from actual content, not a hardcoded name
    if topic_snippets:
        system_prompt = system_prompt.replace(
            "[COURSE]",
            "the uploaded course materials (covering topics such as those in the retrieved content below)",
        )
    else:
        system_prompt = system_prompt.replace("[COURSE]", settings.course_name)

    # Inject dynamic tutor mode based on classification + hint level
    # Load current hint level from conversation
    current_hint_level = 0
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id)
            conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
            if conv:
                current_hint_level = conv.hint_level or 0
        except Exception:
            pass

    system_prompt += "\n\n--- CURRENT SESSION CONTEXT ---\n"
    system_prompt += f"Message type: {msg_type}\n"
    system_prompt += f"Student showed prior attempt: {'yes' if has_attempt else 'no'}\n"
    system_prompt += f"Current hint level: {current_hint_level} (0=vague, 1=specific, 2=worked example)\n"

    if msg_type == "homework":
        system_prompt += """
IMPORTANT — THIS IS A HOMEWORK QUESTION. Follow this EXACT response structure:

1. **Acknowledgment** (1 sentence): Recognize the topic, show it's a good question.

2. **Assessment**: If the student showed work, point out what's correct first. If not, ask them to share ONE thing they think is true about this topic so you can build on it.

3. **Guide** (use the hint level):
   - Level 0: Give a vague conceptual nudge. Name the broad topic area and ask what they know about it. Do NOT name the specific answer or mechanism.
   - Level 1: Name the specific concept. Break the problem into numbered sub-steps. Walk them through step 1 only, then ask them to try step 2.
   - Level 2: Walk through a SIMILAR but DIFFERENT worked example step by step with bullet points. Then say "Now apply this same approach to your original question."

4. **Analogy** (1-2 sentences): Give a real-world analogy that makes the concept click. E.g., "Think of X like Y."

5. **Encouragement + Socratic question**: Use growth-mindset language ("You are making progress"). End with a specific question: "Which part seems most confusing?" or "What would you try next?"

6. **Citations fence**: Emit a ```citations``` JSON fence per Rule 7 (see system prompt). No inline `[Source: ...]` markers.

7. **Quiz fence (MANDATORY, never skip, never leave open-ended)**: After the citations fence, emit a ```quiz``` JSON fence per Rule 8. Must be `kind: "mcq"` (4 concrete options + answer index) or `kind: "tf"` (boolean answer). Open-ended follow-up prompts in the response prose do NOT satisfy this rule — the fenced block is required so the UI can render clickable buttons.

NEVER give the final answer, result, or solution. If you catch yourself about to state the answer, STOP and convert it into a question.
"""
    elif msg_type == "conceptual":
        system_prompt += """
THIS IS A CONCEPTUAL QUESTION. Follow this EXACT response structure:

1. **Acknowledgment** (1 sentence): "That's a fundamental topic" or similar.

2. **Check prior knowledge** (1 sentence): Ask what they already know or have seen about this topic.

3. **Structured explanation** using ONLY the retrieved course content:
   - Use bullet points with clear sub-categories (Purpose, Mechanism, Key differences, etc.)
   - Compare and contrast when relevant (e.g., mitosis vs meiosis, DNA vs RNA)
   - Include specific details: numbers, names, sequences
   - Keep each bullet concise (1-2 sentences max)

4. **Analogy**: Give a concrete real-world analogy. E.g., "Think of mitosis as making a photocopy — one copy identical to the original. Meiosis is like shuffling two decks, splitting and recombining cards."

5. **Follow-up**: End with a specific Socratic question to check understanding or deepen learning: "Which of these differences seems most confusing right now?" or "Can you explain back to me how X works?"

6. **Citations fence**: Emit a ```citations``` JSON fence per Rule 7 (see system prompt). No inline `[Source: ...]` markers.

7. **Quiz fence (MANDATORY, never skip, never leave open-ended)**: After the citations fence, emit a ```quiz``` JSON fence per Rule 8. Must be `kind: "mcq"` (4 concrete options + answer index) or `kind: "tf"` (boolean answer). The Socratic "Which of these is most confusing?" prose question does NOT satisfy this — the quiz fence is a separate, required structured block the UI renders as clickable buttons.

Do NOT give a flat paragraph explanation. Always use structured bullets + analogy + question.
"""
    elif msg_type == "meta":
        docs_for_meta: list[dict] = []
        if dataset:
            try:
                docs_for_meta = _list_available_docs(db, dataset.id)
            except Exception:
                docs_for_meta = []

        if docs_for_meta:
            docs_block = "\n".join(
                f"  - {d['title']}" + (f": {d['preview']}" if d['preview'] else "")
                for d in docs_for_meta
            )
            available_info = (
                "Available documents and what they cover (use this list if the student "
                "asks what you can help with, what topics are available, or what "
                "documents exist):\n"
                f"{docs_block}"
            )
        else:
            available_info = (
                "No course materials have been uploaded yet. Let the user know they "
                "can start chatting once their instructor uploads content."
            )

        system_prompt += f"""
THIS IS A META QUESTION (greeting, logistics, identity, or a request to list what you can help with).

{available_info}

- If the student asks what you can help with / what topics you cover / what documents exist:
  Respond with a short intro sentence, then a markdown bullet list of document titles and a brief description of each (infer description from the provided previews). End with a single inviting follow-up question. DO list the actual document titles in this case — it's the whole point.
- If it's a general greeting: be warm and concise (2-3 sentences max). Mention 2-3 example topic areas (inferred from the documents above) but don't dump the full list.
- If about course logistics (schedule, grading, office hours): say you don't have the schedule and suggest checking the syllabus.
- If asked "who are you", "what model are you", "are you GPT/ChatGPT/Claude", or anything about your identity:
  Reply EXACTLY: "I am Contexto, an AI Tutor created by Dr. Vatsa Patel. I'm here to help you learn through guided questions and hints — not by giving you answers directly. All course materials and content are provided by your instructors; Dr. Patel is not responsible for uploaded content."
  NEVER mention OpenAI, GPT, ChatGPT, Claude, Anthropic, or any model name. You are Contexto, period.
"""

    system_prompt += "--- END SESSION CONTEXT ---\n"

    # Append context block if we have retrieved chunks
    if source_chunks:
        context_lines = ["\n\n--- Retrieved Course Content ---"]
        for i, chunk in enumerate(source_chunks, 1):
            context_lines.append(
                f"\n[Chunk {i}] (Source: {chunk.doc_title}, "
                f"Section: {chunk.section}, p.{chunk.page_num}, "
                f"score: {chunk.score:.2f})\n{chunk.text}"
            )
        context_lines.append("\n--- End Retrieved Content ---\n")
        system_prompt += "\n".join(context_lines)

    prompt_messages: list[dict] = [{"role": "system", "content": system_prompt}]
    prompt_messages.extend(history_messages)
    prompt_messages.append({"role": "user", "content": working_query})

    # ------------------------------------------------------------------
    # 9. Create conversation if new
    # ------------------------------------------------------------------
    if not conversation_id:
        new_conv = Conversation(
            user_id=user_id,
            course_id=course_id,
            name=working_query[:100],
            hint_level=0,
            interaction_count=0,
        )
        db.add(new_conv)
        db.flush()
        conversation_id = str(new_conv.id)
    else:
        try:
            uuid.UUID(conversation_id)
        except ValueError:
            new_conv = Conversation(
                user_id=user_id,
                course_id=course_id,
                name=working_query[:100],
                hint_level=0,
                interaction_count=0,
            )
            db.add(new_conv)
            db.flush()
            conversation_id = str(new_conv.id)

    conv_uuid = uuid.UUID(conversation_id)

    # ------------------------------------------------------------------
    # 10. Save user message
    # ------------------------------------------------------------------
    user_msg = Message(
        conversation_id=conv_uuid,
        role="user",
        content=query,  # store original (un-scrubbed) for display
        message_type=msg_type,
        has_attempt=has_attempt,
    )
    db.add(user_msg)
    db.flush()

    # ------------------------------------------------------------------
    # 11. Stream LLM response
    # ------------------------------------------------------------------
    assistant_msg_id = str(uuid.uuid4())
    full_response_parts: list[str] = []

    async for chunk_text in llm.chat_stream(prompt_messages):
        full_response_parts.append(chunk_text)
        yield _sse({
            "event": "message",
            "answer": chunk_text,
            "conversation_id": conversation_id,
            "message_id": assistant_msg_id,
            "created_at": now_ts,
        })

    full_response = "".join(full_response_parts)

    # ------------------------------------------------------------------
    # 12. Output validation
    # ------------------------------------------------------------------
    validation = _output_validator.validate(full_response)
    stored_response = full_response
    if not validation.is_valid and validation.sanitized_response:
        stored_response = validation.sanitized_response

    # ------------------------------------------------------------------
    # 12b. Humanizer (optional)
    # ------------------------------------------------------------------
    if settings.enable_humanizer and stored_response == full_response:
        try:
            stored_response = await humanize_response(llm, stored_response)
        except Exception as exc:
            logger.warning("Humanizer failed, using original: %s", exc)

    # ------------------------------------------------------------------
    # 13. Collect retrieval metadata (fallback for when the LLM skips
    #     the citations fence). The LLM now emits a `citations` code
    #     fence at the end of its response; the frontend parses it and
    #     renders badges from there. We no longer rewrite the text.
    # ------------------------------------------------------------------
    retrieval_sources_json: list[dict] | None = None
    if source_chunks:
        retrieval_sources_json = [
            {
                "doc_title": c.doc_title,
                "doc_id": c.doc_id,
                "page_num": c.page_num,
                "section": c.section,
                "score": c.score,
            }
            for c in source_chunks
        ]

    # ------------------------------------------------------------------
    # 14. Save assistant message
    # ------------------------------------------------------------------
    assistant_msg = Message(
        id=uuid.UUID(assistant_msg_id),
        conversation_id=conv_uuid,
        role="assistant",
        content=stored_response,
        message_type=msg_type,
        has_attempt=False,
        retrieval_sources=retrieval_sources_json,
    )
    db.add(assistant_msg)

    # ------------------------------------------------------------------
    # 15. Update conversation
    # ------------------------------------------------------------------
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
    if conv:
        conv.interaction_count = (conv.interaction_count or 0) + 1
        # Progress hint level after every 2 interactions on same conversation
        if conv.interaction_count % 2 == 0 and (conv.hint_level or 0) < 2:
            conv.hint_level = (conv.hint_level or 0) + 1

    # ------------------------------------------------------------------
    # 15b. Track token usage
    # ------------------------------------------------------------------
    try:
        # Approximate token counts from word counts (×1.3 is standard heuristic)
        prompt_text = " ".join(m.get("content", "") for m in prompt_messages)
        tokens_in_approx = int(len(prompt_text.split()) * 1.3)
        tokens_out_approx = int(len(full_response.split()) * 1.3)

        profile.tokens_in += tokens_in_approx
        profile.tokens_out += tokens_out_approx
    except Exception as exc:
        logger.warning("Token tracking failed: %s", exc)

    db.commit()

    # ------------------------------------------------------------------
    # 16. Yield message_end event
    # ------------------------------------------------------------------
    metadata: dict = {}
    if retrieval_sources_json:
        metadata["retriever_resources"] = retrieval_sources_json

    yield _sse({
        "event": "message_end",
        "conversation_id": conversation_id,
        "message_id": assistant_msg_id,
        "metadata": metadata,
    })

    # ------------------------------------------------------------------
    # 17. Background: risk detection
    # ------------------------------------------------------------------
    try:
        _escalation_service.detect_risk_signals(query)
    except Exception as exc:
        logger.warning("Risk signal detection failed: %s", exc)
