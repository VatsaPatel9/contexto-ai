"""Admin exam authoring endpoints.

Phase 1 covers the *authoring* surface only — create draft exams, add /
edit / remove questions while in draft, publish (one-way lock), extend
deadline post-publish, and soft delete. Student-facing endpoints (start,
take, submit, grade) and AI generation land in later phases.

Authorization mirrors the courses router:
* super_admin: any course.
* admin: only courses they created (``Dataset.created_by``).

Course identity follows the rest of the schema — URL paths use the
public ``course_id`` slug, the router resolves it to ``Dataset.id`` (UUID),
and ``exams.dataset_id`` stores that UUID.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _stable_hash31(s: str) -> int:
    """Process-stable 31-bit non-negative hash.

    Python's built-in ``hash()`` randomises string hashing per process
    (``PYTHONHASHSEED``), which would shuffle options into different
    orders across pods or restarts and break the "same attempt always
    looks the same" guarantee of :func:`_serialize_question_for_student`.
    A 4-byte SHA-1 prefix gives us deterministic 31-bit ints — plenty
    of entropy for a per-question seed mix.
    """
    return int.from_bytes(
        hashlib.sha1(s.encode("utf-8")).digest()[:4], "big"
    ) & 0x7FFFFFFF

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from supertokens_python.recipe.session import SessionContainer

from backend.auth.dependencies import get_user_roles, require_auth, require_role
from backend.auth.roles import ADMIN, SUPER_ADMIN
from backend.database import get_db
from backend.models.dataset import Dataset
from backend.models.exam import (
    Exam,
    ExamAttempt,
    ExamAttemptGrant,
    ExamQuestion,
    ExamQuestionOption,
    ExamResponse,
    ExamState,
    QuestionType,
)
from backend.models.user_course import UserCourse

router = APIRouter(prefix="/api/admin", tags=["admin-exams"])
student_router = APIRouter(prefix="/api/exams", tags=["exams"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OptionIn(BaseModel):
    text: str
    is_correct: bool = False


class QuestionIn(BaseModel):
    type: str  # "mcq" | "true_false"
    text: str
    explanation: Optional[str] = None
    options: list[OptionIn]


class QuestionPatch(BaseModel):
    text: Optional[str] = None
    explanation: Optional[str] = None
    options: Optional[list[OptionIn]] = None
    position: Optional[int] = None


class ExamCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    deadline_at: datetime  # any TZ-aware ISO; stored UTC
    time_limit_minutes: Optional[int] = Field(default=60, ge=1, le=24 * 60)


class ExamUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline_at: Optional[datetime] = None
    time_limit_minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)


class OptionResponse(BaseModel):
    id: str
    position: int
    text: str
    is_correct: bool


class QuestionResponse(BaseModel):
    id: str
    position: int
    type: str
    text: str
    explanation: Optional[str] = None
    options: list[OptionResponse]


class ExamSummary(BaseModel):
    id: str
    course_id: str
    title: str
    description: Optional[str] = None
    state: str
    deadline_at: str  # ISO 8601 UTC
    time_limit_minutes: Optional[int] = None
    question_count: int
    created_by: str
    created_at: str
    published_at: Optional[str] = None


class ExamDetail(ExamSummary):
    questions: list[QuestionResponse]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_owns_course(
    dataset: Dataset, caller_id: str, caller_roles: list[str]
) -> None:
    if SUPER_ADMIN in caller_roles:
        return
    if dataset.created_by and dataset.created_by == caller_id:
        return
    raise HTTPException(
        status_code=403,
        detail="You can only manage courses you created.",
    )


def _resolve_course(db: DBSession, course_id: str) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")
    return dataset


def _resolve_exam(db: DBSession, exam_id: str) -> Exam:
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.deleted_at.is_(None)).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


async def _ensure_can_manage_exam(
    db: DBSession, exam: Exam, session: SessionContainer
) -> Dataset:
    """Resolve the exam's course and confirm the caller may manage it."""
    dataset = db.query(Dataset).filter(Dataset.id == exam.dataset_id).first()
    if not dataset:
        # Course gone but exam still here — shouldn't happen given the
        # FK cascade, but treat defensively as 404 instead of 500.
        raise HTTPException(status_code=404, detail="Course not found")
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)
    _ensure_owns_course(dataset, caller_id, caller_roles)
    return dataset


def _utc(dt: datetime) -> datetime:
    """Coerce any incoming aware/naive datetime to UTC (treat naive as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_question_payload(payload: QuestionIn) -> None:
    """Reject obviously malformed question shapes (called on add/edit)."""
    qtype = payload.type
    if qtype not in (QuestionType.MCQ.value, QuestionType.TRUE_FALSE.value):
        raise HTTPException(status_code=400, detail=f"Unknown question type: {qtype}")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Question text is required")
    if qtype == QuestionType.MCQ.value:
        if len(payload.options) != 4:
            raise HTTPException(
                status_code=400,
                detail="MCQ requires exactly 4 options",
            )
        if not any(o.is_correct for o in payload.options):
            raise HTTPException(
                status_code=400,
                detail="MCQ requires at least one correct option",
            )
    else:  # true_false
        if len(payload.options) != 2:
            raise HTTPException(
                status_code=400,
                detail="True/False requires exactly 2 options",
            )
        correct = sum(1 for o in payload.options if o.is_correct)
        if correct != 1:
            raise HTTPException(
                status_code=400,
                detail="True/False requires exactly one correct option",
            )
    for o in payload.options:
        if not o.text.strip():
            raise HTTPException(status_code=400, detail="Option text cannot be empty")


def _serialize_question(q: ExamQuestion) -> QuestionResponse:
    return QuestionResponse(
        id=str(q.id),
        position=q.position,
        type=q.type,
        text=q.text,
        explanation=q.explanation,
        options=[
            OptionResponse(
                id=str(o.id),
                position=o.position,
                text=o.text,
                is_correct=o.is_correct,
            )
            for o in q.options
        ],
    )


def _serialize_exam(exam: Exam, course_id: str, *, with_questions: bool) -> dict:
    base = {
        "id": str(exam.id),
        "course_id": course_id,
        "title": exam.title,
        "description": exam.description,
        "state": exam.state,
        "deadline_at": exam.deadline_at.isoformat(),
        "time_limit_minutes": exam.time_limit_minutes,
        "question_count": len(exam.questions),
        "created_by": exam.created_by,
        "created_at": exam.created_at.isoformat(),
        "published_at": exam.published_at.isoformat() if exam.published_at else None,
    }
    if with_questions:
        base["questions"] = [_serialize_question(q) for q in exam.questions]
    return base


# ---------------------------------------------------------------------------
# Course-scoped: list / create
# ---------------------------------------------------------------------------

@router.get("/courses/{course_id}/exams")
async def list_exams(
    course_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List non-deleted exams in a course."""
    dataset = _resolve_course(db, course_id)
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)
    _ensure_owns_course(dataset, caller_id, caller_roles)

    exams = (
        db.query(Exam)
        .filter(Exam.dataset_id == dataset.id, Exam.deleted_at.is_(None))
        .order_by(Exam.created_at.desc())
        .all()
    )
    return {"exams": [_serialize_exam(e, course_id, with_questions=False) for e in exams]}


@router.post("/courses/{course_id}/exams")
async def create_exam(
    course_id: str,
    body: ExamCreateRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Create a draft exam. Questions are added via separate endpoints."""
    dataset = _resolve_course(db, course_id)
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)
    _ensure_owns_course(dataset, caller_id, caller_roles)

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    deadline = _utc(body.deadline_at)
    if deadline <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="deadline_at must be in the future",
        )

    exam = Exam(
        dataset_id=dataset.id,
        title=title,
        description=(body.description or "").strip() or None,
        created_by=caller_id,
        state=ExamState.DRAFT.value,
        deadline_at=deadline,
        time_limit_minutes=body.time_limit_minutes,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return _serialize_exam(exam, course_id, with_questions=True)


# ---------------------------------------------------------------------------
# Exam-scoped: get / patch / publish / delete
# ---------------------------------------------------------------------------

@router.get("/exams/{exam_id}")
async def get_exam(
    exam_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Full exam payload including questions and options."""
    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)
    return _serialize_exam(exam, dataset.course_id, with_questions=True)


@router.patch("/exams/{exam_id}")
async def update_exam(
    exam_id: str,
    body: ExamUpdateRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Edit an exam.

    Allowed in draft: any field.
    Allowed post-publish: ``deadline_at`` only (extension/correction).
    Title / description / time_limit are locked at publish to keep
    student expectations stable.
    """
    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)

    is_draft = exam.state == ExamState.DRAFT.value

    if body.title is not None:
        if not is_draft:
            raise HTTPException(status_code=400, detail="Cannot rename after publish")
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        exam.title = title

    if body.description is not None:
        if not is_draft:
            raise HTTPException(status_code=400, detail="Cannot edit description after publish")
        cleaned = body.description.strip()
        exam.description = cleaned if cleaned else None

    # Use ``model_fields_set`` to distinguish "field absent" from
    # "field explicitly null" — null on this field means "switch to
    # untimed", not "no change". The Pydantic ``ge=1`` constraint still
    # rejects 0 and negatives when an integer IS supplied.
    if "time_limit_minutes" in body.model_fields_set:
        if not is_draft:
            raise HTTPException(status_code=400, detail="Cannot change time limit after publish")
        exam.time_limit_minutes = body.time_limit_minutes  # may be None ⇒ untimed

    if body.deadline_at is not None:
        new_deadline = _utc(body.deadline_at)
        if new_deadline <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400,
                detail="deadline_at must be in the future",
            )
        old_deadline = exam.deadline_at
        exam.deadline_at = new_deadline

        # Propagate deadline extensions to in-flight attempts.
        # ``due_at`` was frozen at start as min(old_deadline, started_at +
        # time_limit). When the admin extends the deadline, attempts
        # whose due_at was bound by the old deadline should get the new
        # one — otherwise the student gets cut off at the OLD deadline
        # despite the extension. We only EXTEND (never shorten) here:
        # shortening mid-attempt is a contract change we don't want to
        # spring on a student who's already half-through.
        if new_deadline > old_deadline:
            from datetime import timedelta as _td
            tl = exam.time_limit_minutes
            active = (
                db.query(ExamAttempt)
                .filter(
                    ExamAttempt.exam_id == exam.id,
                    ExamAttempt.submitted_at.is_(None),
                )
                .all()
            )
            for a in active:
                if tl is None:
                    new_due = new_deadline
                else:
                    new_due = min(new_deadline, a.started_at + _td(minutes=tl))
                if new_due > a.due_at:
                    a.due_at = new_due

    db.commit()
    db.refresh(exam)
    return _serialize_exam(exam, dataset.course_id, with_questions=True)


@router.post("/exams/{exam_id}/publish")
async def publish_exam(
    exam_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Publish a draft exam — questions and answers lock at this moment."""
    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)

    if exam.state != ExamState.DRAFT.value:
        raise HTTPException(
            status_code=400,
            detail=f"Only drafts can be published (current state: {exam.state})",
        )
    if not exam.questions:
        raise HTTPException(
            status_code=400,
            detail="Add at least one question before publishing",
        )
    if exam.deadline_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="Cannot publish an exam whose deadline has passed",
        )

    exam.state = ExamState.PUBLISHED.value
    exam.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)
    return _serialize_exam(exam, dataset.course_id, with_questions=True)


@router.delete("/exams/{exam_id}")
async def delete_exam(
    exam_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Soft-delete an exam. Submissions (Phase 2) are preserved on disk."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    exam.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"result": "success", "exam_id": exam_id}


# ---------------------------------------------------------------------------
# Question CRUD (draft only)
# ---------------------------------------------------------------------------

def _ensure_draft(exam: Exam) -> None:
    if exam.state != ExamState.DRAFT.value:
        raise HTTPException(
            status_code=400,
            detail="Questions can only be edited while the exam is in draft.",
        )


@router.post("/exams/{exam_id}/questions")
async def add_question(
    exam_id: str,
    body: QuestionIn,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Add a single question to a draft exam (appended to the end)."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)
    _validate_question_payload(body)

    next_position = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam.id)
        .count()
    )

    question = ExamQuestion(
        exam_id=exam.id,
        position=next_position,
        type=body.type,
        text=body.text.strip(),
        explanation=(body.explanation or "").strip() or None,
    )
    db.add(question)
    db.flush()  # populate question.id

    for i, opt in enumerate(body.options):
        db.add(
            ExamQuestionOption(
                question_id=question.id,
                position=i,
                text=opt.text.strip(),
                is_correct=opt.is_correct,
            )
        )

    db.commit()
    db.refresh(question)
    return _serialize_question(question)


class QuestionsBulkRequest(BaseModel):
    questions: list[QuestionIn]


@router.post("/exams/{exam_id}/questions/bulk")
async def add_questions_bulk(
    exam_id: str,
    body: QuestionsBulkRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Append several questions atomically (used by the AI flow in Phase 3)."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    for q in body.questions:
        _validate_question_payload(q)

    next_position = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam.id)
        .count()
    )

    created: list[ExamQuestion] = []
    for offset, q_in in enumerate(body.questions):
        q = ExamQuestion(
            exam_id=exam.id,
            position=next_position + offset,
            type=q_in.type,
            text=q_in.text.strip(),
            explanation=(q_in.explanation or "").strip() or None,
        )
        db.add(q)
        db.flush()
        for i, opt in enumerate(q_in.options):
            db.add(
                ExamQuestionOption(
                    question_id=q.id,
                    position=i,
                    text=opt.text.strip(),
                    is_correct=opt.is_correct,
                )
            )
        created.append(q)

    db.commit()
    for q in created:
        db.refresh(q)
    return {"questions": [_serialize_question(q) for q in created]}


# ---------------------------------------------------------------------------
# AI-assisted question generation (Phase 3)
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    topic: str
    n_mcq: int = Field(default=5, ge=0, le=20)
    n_tf: int = Field(default=5, ge=0, le=20)


# JSON schema we hand to the LLM via OpenAI's structured-output mode.
# Strict mode means the model must produce JSON that validates exactly —
# no prose, no markdown fences, no extra fields. We still re-validate
# semantically afterwards (4-option MCQ, 2-option T/F, ≥1 correct, etc.)
# because strict-mode JSON-Schema can't express "options must have length
# exactly 4 OR exactly 2 depending on type".
_GENERATE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "text", "options", "explanation"],
                "properties": {
                    "type": {"type": "string", "enum": ["mcq", "true_false"]},
                    "text": {"type": "string"},
                    "explanation": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "is_correct"],
                            "properties": {
                                "text": {"type": "string"},
                                "is_correct": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def _build_generate_prompt(
    topic: str,
    n_mcq: int,
    n_tf: int,
    chunks: list,
    course_name: str | None,
) -> list[dict]:
    """Compose the system + user messages for question generation.

    Caller guarantees ``chunks`` is non-empty — the strict course-only
    contract is enforced at :func:`_generate_candidates_for_course`,
    which refuses (422) when retrieval returns nothing.
    """
    system_lines = [
        "You are an exam-question author. EVERY question you produce "
        "MUST be answerable directly from the supplied course materials. "
        "You do NOT use general knowledge, prior training, intuition, "
        "or anything outside the chunks given to you.",
        "",
        "Rules — apply ALL of them, strictly:",
        "  * COURSE-ONLY: every question's correct answer must be "
        "explicitly supported by content in the source chunks. If you "
        "cannot ground a question in the chunks, OMIT it. Returning "
        "fewer questions than asked is the correct behaviour — never "
        "fill quota by inventing.",
        "  * NO outside facts: do not introduce dates, names, formulas, "
        "definitions, examples, or claims that aren't in the chunks. "
        "If the chunk doesn't say it, you don't know it.",
        "  * NO meta-questions about the materials themselves (\"who "
        "wrote this?\", \"what page is X on?\"). Test the content, "
        "not the artefact.",
        "  * Multiple-choice (mcq) questions MUST have exactly 4 options. "
        "At least one option must be correct; multiple correct options "
        "are allowed when justified by the material (the student gets "
        "partial credit for a partial selection).",
        "  * True/False (true_false) questions MUST have exactly 2 "
        "options with text 'True' and 'False' (in that order), and "
        "exactly one correct.",
        "  * The explanation cites WHY the correct answer is correct, "
        "in 1–3 sentences, paraphrasing the source material.",
        "  * Distractors (wrong options) should be plausible and "
        "course-relevant — drawn from related concepts in the chunks, "
        "not obvious nonsense.",
        "  * Keep question stems and options self-contained. Don't "
        'write "see the diagram above" or "as the previous question '
        'showed".',
    ]
    if course_name:
        system_lines.insert(1, f"This exam is for the course: {course_name}.")

    system_msg = "\n".join(system_lines)

    chunk_lines = ["", "--- Course Materials (the ONLY ground truth) ---"]
    for i, c in enumerate(chunks, 1):
        chunk_lines.append(
            f"\n[Source {i}] {c.doc_title} "
            f"(p.{c.page_num}{', ' + c.section if c.section else ''})\n"
            f"{c.text}"
        )
    chunk_lines.append("\n--- End Course Materials ---")
    system_msg += "\n".join(chunk_lines)

    user_lines = [
        f"Generate exam questions on this topic: {topic.strip()}.",
        f"Target counts: {n_mcq} multiple-choice (mcq) + "
        f"{n_tf} true/false (true_false).",
        "If the materials don't support the requested count, return "
        "fewer — never fabricate to hit the number. Return only the "
        "JSON object matching the schema; no prose.",
    ]

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


async def _generate_candidates_for_course(
    *,
    dataset,
    topic: str,
    n_mcq: int,
    n_tf: int,
) -> dict:
    """Run the RAG + LLM generation pipeline for one (dataset, topic) ask.

    Shared between the form-driven ``/generate`` endpoint and the
    chat-driven ``/agent`` endpoint so both produce candidates the same
    way and pass them through the same validation.

    Returns ``{ candidates, dropped, chunks_used, retrieval_failed }``.
    Raises ``HTTPException(502)`` only on outright LLM failure — empty
    retrievals are tolerated (the model falls back to general knowledge
    on the topic, with a system-prompt note).
    """
    from backend.dependencies import get_llm_client, get_retriever

    retriever = get_retriever()
    try:
        chunks = retriever.retrieve_for_course(
            query=topic,
            dataset_id=str(dataset.id),
            top_k=8,
            score_threshold=0.2,
        )
    except Exception as exc:
        logger.error("Retrieval failed during exam generation: %s", exc)
        chunks = []

    # Strict course-only: refuse to generate when retrieval comes back
    # empty. The chat tutor refuses for the same reason; the exam author
    # must abide by the same contract — no questions on material the
    # course doesn't cover. The admin sees a clear error so they can
    # rephrase the topic or upload missing materials.
    if not chunks:
        raise HTTPException(
            status_code=422,
            detail=(
                "No course materials match that topic. Try a topic "
                "closer to wording in the uploaded documents, or upload "
                "materials that cover it before generating."
            ),
        )

    messages = _build_generate_prompt(
        topic=topic,
        n_mcq=n_mcq,
        n_tf=n_tf,
        chunks=chunks,
        course_name=dataset.name,
    )

    llm = get_llm_client()
    try:
        result = await llm.chat_json(
            messages,
            schema=_GENERATE_SCHEMA,
            schema_name="exam_questions",
            temperature=0.3,
        )
    except Exception as exc:
        logger.exception("LLM generation failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Question generation failed — try again in a moment.",
        )

    raw_candidates = result.get("questions", []) if isinstance(result, dict) else []
    valid: list[dict] = []
    dropped = 0
    import uuid as _uuid
    for cand in raw_candidates:
        if not _candidate_is_valid(cand):
            dropped += 1
            continue
        valid.append({
            "client_id": str(_uuid.uuid4()),
            "type": cand["type"],
            "text": cand["text"],
            "explanation": cand.get("explanation") or "",
            "options": [
                {"text": o["text"], "is_correct": bool(o["is_correct"])}
                for o in cand["options"]
            ],
            "source_chunks": [
                {
                    "doc_title": c.doc_title,
                    "page_num": c.page_num,
                    "section": c.section,
                }
                for c in chunks[:3]
            ],
        })

    return {
        "candidates": valid,
        "dropped": dropped,
        "chunks_used": len(chunks),
    }


def _candidate_is_valid(candidate: dict) -> bool:
    """Cheap sanity check on a single LLM-emitted candidate.

    The schema already constrains shape; here we enforce the
    type-specific cardinality and "≥1 correct" rule.
    """
    qtype = candidate.get("type")
    options = candidate.get("options") or []
    if not candidate.get("text", "").strip():
        return False
    if qtype == "mcq":
        if len(options) != 4:
            return False
        if not any(o.get("is_correct") for o in options):
            return False
    elif qtype == "true_false":
        if len(options) != 2:
            return False
        if sum(1 for o in options if o.get("is_correct")) != 1:
            return False
    else:
        return False
    return all((o.get("text") or "").strip() for o in options)


@router.post("/exams/{exam_id}/generate")
async def generate_questions(
    exam_id: str,
    body: GenerateRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Draft candidate questions via RAG + LLM. Does NOT persist them.

    Flow:
      1. Authorise (admin owns course / super_admin) and ensure draft.
      2. Retrieve course-scoped chunks for the topic prompt.
      3. Call the LLM with strict JSON-Schema structured output.
      4. Validate candidates per type-specific rules; drop bad ones.
      5. Return them with stable ``client_id``s the UI uses for
         selection. Persisting is a separate ``/questions/bulk`` call —
         the admin reviews and edits in the side panel first.
    """
    from backend.dependencies import get_llm_client, get_retriever

    if body.n_mcq + body.n_tf <= 0:
        raise HTTPException(status_code=400, detail="Request at least one question.")
    if body.n_mcq + body.n_tf > 30:
        raise HTTPException(status_code=400, detail="Cap is 30 questions per call.")
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    result = await _generate_candidates_for_course(
        dataset=dataset,
        topic=topic,
        n_mcq=body.n_mcq,
        n_tf=body.n_tf,
    )

    return {
        "candidates": result["candidates"],
        "requested": {"mcq": body.n_mcq, "tf": body.n_tf},
        "dropped": result["dropped"],
        "chunks_used": result["chunks_used"],
    }


# ---------------------------------------------------------------------------
# AI Agent (Phase 5) — chat-driven question generation with tool calls
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: Optional[str] = None
    # OpenAI tool-call shape; round-trips between client and server so
    # the conversation has full context on each turn.
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class AgentRequest(BaseModel):
    user_message: str
    history: list[AgentMessage] = Field(default_factory=list)


# Tool spec the LLM sees. The agent has exactly one tool — making the
# admin's natural-language request fully self-contained ("I'll just
# call this with these args"). Adding more tools later (e.g.
# ``regenerate_question``) is a matter of expanding this list.
_AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "generate_exam_questions",
            "description": (
                "Draft candidate exam questions and put them in the "
                "review panel. ALWAYS call this — never write questions "
                "in chat. Triggered by ANY request that involves making, "
                "drafting, generating, creating, writing, adding, "
                "preparing, or producing questions / exam items / MCQs "
                "/ T-or-Fs / quizzes / problems. The tool returns "
                "structured candidates the admin reviews and edits in a "
                "side panel; you do NOT add them to the exam yourself."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["topic", "n_mcq", "n_tf"],
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "Subject of the questions, e.g. 'photosynthesis "
                            "light reactions'. Use the admin's wording."
                        ),
                    },
                    "n_mcq": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 20,
                        "description": "How many multiple-choice questions.",
                    },
                    "n_tf": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 20,
                        "description": "How many true/false questions.",
                    },
                },
            },
        },
    },
]


def _agent_system_prompt(exam: Exam, course_name: str | None) -> str:
    return (
        "You are a tool-calling exam-authoring agent embedded in the "
        f"editor for the exam \"{exam.title}\""
        f"{' in course ' + course_name if course_name else ''}. "
        "You are NOT a tutor and NOT a chatbot. You are an action "
        "agent whose primary behaviour is to call tools.\n"
        "\n"
        "RULES — apply strictly:\n"
        "  1. The ONLY way you produce questions is by calling "
        "`generate_exam_questions`. Never write question stems, "
        "options, or T/F items in chat — even if the admin says "
        "'just brainstorm' or 'show me ideas'. The brainstorm IS "
        "the tool call; the tool returns candidates the admin "
        "reviews and edits.\n"
        "  2. Call the tool for ANY request that asks to make, draft, "
        "generate, create, write, add, prepare, brainstorm, or come "
        "up with questions / quizzes / MCQs / T-or-Fs / problems / "
        "items / exam content. If unsure whether to call the tool, "
        "call it.\n"
        "  3. Pick reasonable counts when the admin doesn't specify: "
        "default n_mcq=3, n_tf=2. The topic argument is the admin's "
        "wording, lightly cleaned.\n"
        "  4. After the tool runs, write ONE short sentence telling "
        "the admin to look at the side panel. Do NOT repeat any "
        "question text — the panel already shows it.\n"
        "  5. ONLY for genuine meta questions about the exam itself "
        "(\"what's the deadline?\", \"how many questions does this "
        "exam have?\", \"is it published?\") or for clarifying "
        "questions to disambiguate the topic, answer briefly in "
        "plain text without calling the tool.\n"
        "  6. NEVER claim you 'can't create exam questions' or 'can "
        "only brainstorm'. You CAN — by calling the tool. If you find "
        "yourself about to write that, call the tool instead."
    )


def _serialize_history_for_openai(history: list[AgentMessage]) -> list[dict]:
    """Convert the API-side AgentMessage list into OpenAI message dicts."""
    out: list[dict] = []
    for m in history:
        d: dict = {"role": m.role}
        if m.content is not None:
            d["content"] = m.content
        if m.tool_calls:
            d["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        if m.name:
            d["name"] = m.name
        out.append(d)
    return out


@router.post("/exams/{exam_id}/agent")
async def exam_agent(
    exam_id: str,
    body: AgentRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Chat-driven generation. Drives an OpenAI tool-call loop server-side.

    The admin's history is round-tripped through the client (no DB
    state) — each turn we re-send the prior messages, plus the current
    user message, plus accumulated tool-call results. Loop terminates
    when the model stops asking for tools (typically 1–2 iterations).

    Candidates produced by ``generate_exam_questions`` calls are returned
    out-of-band so the panel can render them — they're NOT persisted,
    matching the form-based flow's review-before-add contract.
    """
    from backend.dependencies import get_llm_client

    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    user_msg = body.user_message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="user_message is required")

    # Compose initial messages: system prompt → prior history → new user msg.
    messages: list[dict] = [
        {"role": "system", "content": _agent_system_prompt(exam, dataset.name)}
    ]
    messages.extend(_serialize_history_for_openai(body.history))
    messages.append({"role": "user", "content": user_msg})

    llm = get_llm_client()

    accumulated_candidates: list[dict] = []
    accumulated_dropped = 0
    final_text = ""
    new_history_messages: list[dict] = []

    # Multi-turn tool loop. Capped to keep us off runaway costs if the
    # model misbehaves; in practice 2 iterations covers every flow.
    MAX_TURNS = 4
    for turn in range(MAX_TURNS):
        try:
            call = await llm.chat_call(
                messages,
                tools=_AGENT_TOOLS,
                temperature=0.4,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.exception("Agent LLM call failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="Agent failed — try again in a moment.",
            )

        # If there's no tool call, we're done.
        if not call["tool_calls"]:
            final_text = call["content"] or ""
            messages.append({"role": "assistant", "content": final_text})
            new_history_messages.append(
                {"role": "assistant", "content": final_text}
            )
            break

        # Otherwise: dispatch each tool call, append the assistant turn
        # AND the tool result(s), and loop.
        assistant_msg = {
            "role": "assistant",
            "content": call["content"],
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments_json"],
                    },
                }
                for tc in call["tool_calls"]
            ],
        }
        messages.append(assistant_msg)
        new_history_messages.append(assistant_msg)

        for tc in call["tool_calls"]:
            tool_result_summary: dict = {"ok": False, "error": "Unknown tool"}
            if tc["name"] == "generate_exam_questions":
                try:
                    args = json.loads(tc["arguments_json"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                topic = (args.get("topic") or "").strip()
                n_mcq = int(args.get("n_mcq") or 0)
                n_tf = int(args.get("n_tf") or 0)
                if not topic or (n_mcq + n_tf) <= 0:
                    tool_result_summary = {
                        "ok": False,
                        "error": "topic, n_mcq, and n_tf are required (n_mcq + n_tf > 0).",
                    }
                elif n_mcq + n_tf > 30:
                    tool_result_summary = {
                        "ok": False,
                        "error": "30 questions is the per-call cap.",
                    }
                else:
                    try:
                        result = await _generate_candidates_for_course(
                            dataset=dataset,
                            topic=topic,
                            n_mcq=n_mcq,
                            n_tf=n_tf,
                        )
                        accumulated_candidates.extend(result["candidates"])
                        accumulated_dropped += result["dropped"]
                        tool_result_summary = {
                            "ok": True,
                            "candidate_count": len(result["candidates"]),
                            "mcq_count": sum(
                                1 for c in result["candidates"] if c["type"] == "mcq"
                            ),
                            "tf_count": sum(
                                1 for c in result["candidates"] if c["type"] == "true_false"
                            ),
                            "dropped": result["dropped"],
                            "chunks_used": result["chunks_used"],
                            "topic": topic,
                        }
                    except HTTPException as he:
                        tool_result_summary = {"ok": False, "error": he.detail}
                    except Exception as exc:
                        logger.exception("Tool execution failed: %s", exc)
                        tool_result_summary = {
                            "ok": False,
                            "error": "Generation failed — try again.",
                        }

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "content": json.dumps(tool_result_summary),
            }
            messages.append(tool_msg)
            new_history_messages.append(tool_msg)
    else:
        # Exhausted the loop without a stop — bail with whatever we have.
        final_text = (
            "I couldn't finish that request in one go. The drafts so far "
            "are visible in the side panel."
        )
        messages.append({"role": "assistant", "content": final_text})
        new_history_messages.append(
            {"role": "assistant", "content": final_text}
        )

    # Return: the new history fragments to APPEND to the client's local
    # history (user msg + everything we generated), the final text, and
    # the candidates. Client holds full state.
    return {
        "assistant_message": final_text,
        "candidates": accumulated_candidates,
        "dropped": accumulated_dropped,
        "appended_history": [
            {"role": "user", "content": user_msg}
        ] + new_history_messages,
    }


@router.patch("/exams/{exam_id}/questions/{question_id}")
async def update_question(
    exam_id: str,
    question_id: str,
    body: QuestionPatch,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Edit a question on a draft exam.

    To replace options, send the full list. Partial option edits aren't
    supported — the client always knows the canonical N options.
    """
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    question = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.id == question_id, ExamQuestion.exam_id == exam.id)
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if body.text is not None:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Question text cannot be empty")
        question.text = text

    if body.explanation is not None:
        cleaned = body.explanation.strip()
        question.explanation = cleaned if cleaned else None

    if body.position is not None and body.position >= 0:
        question.position = body.position

    if body.options is not None:
        # Replace the full set. Re-validate by composing a fresh payload
        # so MCQ vs T/F rules apply to the new shape.
        candidate = QuestionIn(
            type=question.type,
            text=question.text,
            explanation=question.explanation,
            options=body.options,
        )
        _validate_question_payload(candidate)
        # Drop existing options, then re-add. cascade='all, delete-orphan'
        # on the relationship handles row deletion when we clear the list.
        question.options.clear()
        db.flush()
        for i, opt in enumerate(body.options):
            db.add(
                ExamQuestionOption(
                    question_id=question.id,
                    position=i,
                    text=opt.text.strip(),
                    is_correct=opt.is_correct,
                )
            )

    db.commit()
    db.refresh(question)
    return _serialize_question(question)


@router.delete("/exams/{exam_id}/questions/{question_id}")
async def delete_question(
    exam_id: str,
    question_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Remove a question from a draft exam, compacting remaining positions."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    question = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.id == question_id, ExamQuestion.exam_id == exam.id)
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    removed_position = question.position
    db.delete(question)
    db.flush()

    # Compact: every question after the removed one shifts down by one.
    db.query(ExamQuestion).filter(
        ExamQuestion.exam_id == exam.id,
        ExamQuestion.position > removed_position,
    ).update(
        {ExamQuestion.position: ExamQuestion.position - 1},
        synchronize_session=False,
    )

    db.commit()
    return {"result": "success", "exam_id": exam_id, "question_id": question_id}


class ReorderRequest(BaseModel):
    # New order, expressed as an ordered list of question_ids.
    question_ids: list[str]


@router.post("/exams/{exam_id}/questions/reorder")
async def reorder_questions(
    exam_id: str,
    body: ReorderRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Set the canonical question order on a draft exam."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)
    _ensure_draft(exam)

    existing = {
        str(q.id): q
        for q in db.query(ExamQuestion).filter(ExamQuestion.exam_id == exam.id).all()
    }
    # Both checks are needed: ``set()`` collapses duplicates, so the
    # equality alone would accept ``[q1, q1, q2, q3]`` against a 4-row
    # exam (set ⊂ existing). The length parity catches that case before
    # we silently overwrite positions and orphan a question.
    if (
        len(body.question_ids) != len(existing)
        or set(body.question_ids) != set(existing.keys())
    ):
        raise HTTPException(
            status_code=400,
            detail="question_ids must list every question in the exam exactly once",
        )

    for new_position, qid in enumerate(body.question_ids):
        existing[qid].position = new_position

    db.commit()
    return {"result": "success", "exam_id": exam_id}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN GRADEBOOK + RETAKE GRANTS + MANUAL OVERRIDE (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════

class ScoreOverrideRequest(BaseModel):
    # Raw points (out of total_points). Send ``null`` to clear the
    # override and revert to the auto-graded score.
    score_raw: Optional[float] = None
    reason: Optional[str] = None


class GrantRetakeRequest(BaseModel):
    # Identify the student by user_id, email, or display_name — same
    # rules the courses router uses for enrollment.
    identifier: str
    reason: Optional[str] = None


async def _resolve_member_label_async(
    user_id: str, db: DBSession
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(display_name, email)`` for a user_id. SuperTokens-aware."""
    from backend.models.user_profile import UserProfile
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    display_name = profile.display_name if profile else None
    email: Optional[str] = None
    try:
        from supertokens_python.asyncio import get_user
        user = await get_user(user_id)
        if user:
            for lm in user.login_methods:
                if lm.email:
                    email = lm.email
                    break
    except Exception:
        pass
    return display_name, email


@router.get("/exams/{exam_id}/gradebook")
async def get_gradebook(
    exam_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List enrolled students and their *latest* attempt status.

    Rows include students who haven't attempted yet (so the admin can
    see the full class roster against the exam in one view). Status
    follows the same vocabulary as the student-facing list.
    """
    from backend.models.user_course import UserCourse

    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)

    enrollments = (
        db.query(UserCourse)
        .filter(UserCourse.dataset_id == dataset.id)
        .all()
    )
    enrolled_user_ids = [r.user_id for r in enrollments]

    # Bulk-load attempts for all enrolled students; pick latest per user.
    attempts_by_user: dict[str, ExamAttempt] = {}
    if enrolled_user_ids:
        for a in (
            db.query(ExamAttempt)
            .filter(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.user_id.in_(enrolled_user_ids),
            )
            .order_by(ExamAttempt.started_at.asc())
            .all()
        ):
            attempts_by_user[a.user_id] = a  # last write wins => latest

        # Lazy-close active attempts past due so the gradebook reflects
        # the final state without an extra round-trip from each student.
        closed_any = False
        for u, a in attempts_by_user.items():
            if a.submitted_at is None and datetime.now(timezone.utc) >= a.due_at:
                _grade_attempt(db, a, exam)
                a.submitted_at = a.due_at
                closed_any = True
        if closed_any:
            db.commit()

    # Per-user attempt count (helps admins spot who's already used a
    # retake grant). Manual count is fine — class size bounds the work.
    attempt_count_by_user: dict[str, int] = {}
    if enrolled_user_ids:
        for a in (
            db.query(ExamAttempt)
            .filter(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.user_id.in_(enrolled_user_ids),
            )
            .all()
        ):
            attempt_count_by_user[a.user_id] = attempt_count_by_user.get(a.user_id, 0) + 1

    # Active grants per user (so the admin can see who has an unused retake).
    active_grants_by_user: dict[str, int] = {}
    if enrolled_user_ids:
        for g in (
            db.query(ExamAttemptGrant)
            .filter(
                ExamAttemptGrant.exam_id == exam.id,
                ExamAttemptGrant.user_id.in_(enrolled_user_ids),
                ExamAttemptGrant.consumed.is_(False),
            )
            .all()
        ):
            active_grants_by_user[g.user_id] = active_grants_by_user.get(g.user_id, 0) + 1

    now = datetime.now(timezone.utc)
    deadline_passed = now >= exam.deadline_at

    rows: list[dict] = []
    for u in enrolled_user_ids:
        attempt = attempts_by_user.get(u)
        display_name, email = await _resolve_member_label_async(u, db)
        if attempt and attempt.submitted_at is not None:
            status = "submitted"
        elif attempt and attempt.submitted_at is None:
            status = "in_progress"
        elif deadline_passed:
            status = "missed"
        else:
            status = "not_started"

        eff_raw, eff_pct = _effective_score(attempt) if attempt else (None, None)
        rows.append({
            "user_id": u,
            "display_name": display_name,
            "email": email,
            "status": status,
            "attempt_id": str(attempt.id) if attempt else None,
            "attempt_count": attempt_count_by_user.get(u, 0),
            "submitted_at": attempt.submitted_at.isoformat() if attempt and attempt.submitted_at else None,
            "score_pct": eff_pct,
            "score_raw": eff_raw,
            "auto_score_raw": (
                attempt.score_raw
                if attempt and attempt.manual_override_score is not None
                else None
            ),
            "total_points": attempt.total_points if attempt else None,
            "manual_override": attempt is not None and attempt.manual_override_score is not None,
            "active_grants": active_grants_by_user.get(u, 0),
        })

    # Sort: in_progress first, then submitted by score desc, then not_started.
    sort_priority = {"in_progress": 0, "submitted": 1, "missed": 2, "not_started": 3}
    rows.sort(key=lambda r: (sort_priority.get(r["status"], 99), -(r["score_pct"] or 0)))

    return {
        "exam_id": str(exam.id),
        "course_id": dataset.course_id,
        "title": exam.title,
        "total_enrolled": len(enrolled_user_ids),
        "rows": rows,
    }


@router.get("/exams/{exam_id}/attempts/{attempt_id}")
async def get_attempt_detail(
    exam_id: str,
    attempt_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Per-question detail of one attempt — for admin review + override."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)

    attempt = (
        db.query(ExamAttempt)
        .filter(ExamAttempt.id == attempt_id, ExamAttempt.exam_id == exam.id)
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    # Safety net: if it was never lazy-closed and is past due.
    if _maybe_lazy_close(db, attempt, exam):
        db.commit()

    responses = {
        str(r.question_id): r
        for r in db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt.id).all()
    }
    questions = sorted(exam.questions, key=lambda q: q.position)
    review = []
    for q in questions:
        r = responses.get(str(q.id))
        review.append({
            "question_id": str(q.id),
            "type": q.type,
            "text": q.text,
            "explanation": q.explanation,
            "options": [
                {"id": str(o.id), "text": o.text, "is_correct": o.is_correct}
                for o in q.options
            ],
            "selected_option_ids": list(r.selected_option_ids) if r else [],
            "is_correct": bool(r.is_correct) if r and r.is_correct is not None else False,
            "partial_score": (r.partial_score if r and r.partial_score is not None else 0.0),
        })

    display_name, email = await _resolve_member_label_async(attempt.user_id, db)
    eff_raw, eff_pct = _effective_score(attempt)
    return {
        "attempt_id": str(attempt.id),
        "exam_id": str(exam.id),
        "user_id": attempt.user_id,
        "display_name": display_name,
        "email": email,
        "started_at": attempt.started_at.isoformat(),
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "due_at": attempt.due_at.isoformat(),
        "score_raw": eff_raw,
        "score_pct": eff_pct,
        "total_points": attempt.total_points,
        "auto_score_raw": attempt.score_raw,
        "manual_override_score": attempt.manual_override_score,
        "override_by": attempt.override_by,
        "override_reason": attempt.override_reason,
        "override_at": attempt.override_at.isoformat() if attempt.override_at else None,
        "review": review,
    }


@router.patch("/exams/{exam_id}/attempts/{attempt_id}/score")
async def override_attempt_score(
    exam_id: str,
    attempt_id: str,
    body: ScoreOverrideRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Set or clear an admin manual override on the attempt's raw score.

    ``score_raw`` of ``null`` clears the override and reverts the
    student-visible score to the auto-graded value. The auto score
    itself is never mutated.
    """
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)

    attempt = (
        db.query(ExamAttempt)
        .filter(ExamAttempt.id == attempt_id, ExamAttempt.exam_id == exam.id)
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.submitted_at is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot override score on an unsubmitted attempt.",
        )

    if body.score_raw is None:
        attempt.manual_override_score = None
        attempt.override_by = None
        attempt.override_reason = None
        attempt.override_at = None
    else:
        # Reject ``inf``/``NaN`` early — JSON allows them as floats but
        # they'd corrupt downstream JSON encoding (the result endpoint
        # would emit ``Infinity`` which isn't valid JSON for browsers).
        if not math.isfinite(body.score_raw):
            raise HTTPException(
                status_code=400, detail="score_raw must be a finite number"
            )
        if body.score_raw < 0:
            raise HTTPException(status_code=400, detail="score_raw must be >= 0")
        if attempt.total_points is not None and body.score_raw > attempt.total_points:
            raise HTTPException(
                status_code=400,
                detail=f"score_raw cannot exceed total_points ({attempt.total_points})",
            )
        attempt.manual_override_score = body.score_raw
        attempt.override_by = session.get_user_id()
        attempt.override_reason = (body.reason or "").strip() or None
        attempt.override_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(attempt)
    eff_raw, eff_pct = _effective_score(attempt)
    return {
        "result": "success",
        "attempt_id": str(attempt.id),
        "score_raw": eff_raw,
        "score_pct": eff_pct,
        "manual_override": attempt.manual_override_score is not None,
        "auto_score_raw": attempt.score_raw,
    }


@router.get("/exams/{exam_id}/grants")
async def list_grants(
    exam_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List all retake grants (consumed and unconsumed) for an exam."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)

    rows = (
        db.query(ExamAttemptGrant)
        .filter(ExamAttemptGrant.exam_id == exam.id)
        .order_by(ExamAttemptGrant.granted_at.desc())
        .all()
    )

    out: list[dict] = []
    for g in rows:
        display_name, email = await _resolve_member_label_async(g.user_id, db)
        out.append({
            "id": str(g.id),
            "user_id": g.user_id,
            "display_name": display_name,
            "email": email,
            "granted_by": g.granted_by,
            "granted_at": g.granted_at.isoformat(),
            "reason": g.reason,
            "consumed": g.consumed,
            "consumed_at": g.consumed_at.isoformat() if g.consumed_at else None,
            "consumed_by_attempt_id": (
                str(g.consumed_by_attempt_id) if g.consumed_by_attempt_id else None
            ),
        })
    return {"grants": out}


@router.post("/exams/{exam_id}/grants")
async def grant_retake(
    exam_id: str,
    body: GrantRetakeRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Grant a single retake to one student.

    Requires the student to be enrolled in the exam's course. Idempotent
    against the user — if they already have an unconsumed grant, this
    returns the existing one rather than stacking duplicates (admins
    rarely want two pending retakes for the same person).
    """
    from backend.routers.courses import _resolve_user_id
    from backend.models.user_course import UserCourse

    exam = _resolve_exam(db, exam_id)
    dataset = await _ensure_can_manage_exam(db, exam, session)

    target_user_id = await _resolve_user_id(body.identifier, db)
    if not target_user_id:
        raise HTTPException(
            status_code=404,
            detail=f"No user found matching '{body.identifier}'",
        )

    enrolled = (
        db.query(UserCourse)
        .filter(
            UserCourse.user_id == target_user_id,
            UserCourse.dataset_id == dataset.id,
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(
            status_code=400,
            detail="That user is not enrolled in this course.",
        )

    existing = (
        db.query(ExamAttemptGrant)
        .filter(
            ExamAttemptGrant.exam_id == exam.id,
            ExamAttemptGrant.user_id == target_user_id,
            ExamAttemptGrant.consumed.is_(False),
        )
        .first()
    )
    if existing is not None:
        return {
            "result": "exists",
            "id": str(existing.id),
            "user_id": target_user_id,
        }

    grant = ExamAttemptGrant(
        exam_id=exam.id,
        user_id=target_user_id,
        granted_by=session.get_user_id(),
        reason=(body.reason or "").strip() or None,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return {
        "result": "success",
        "id": str(grant.id),
        "user_id": target_user_id,
        "granted_at": grant.granted_at.isoformat(),
    }


@router.delete("/exams/{exam_id}/grants/{grant_id}")
async def revoke_grant(
    exam_id: str,
    grant_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Revoke an *unconsumed* grant. Consumed grants stay as audit records."""
    exam = _resolve_exam(db, exam_id)
    await _ensure_can_manage_exam(db, exam, session)

    grant = (
        db.query(ExamAttemptGrant)
        .filter(
            ExamAttemptGrant.id == grant_id,
            ExamAttemptGrant.exam_id == exam.id,
        )
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.consumed:
        raise HTTPException(
            status_code=400,
            detail="Grant already consumed — can't revoke a used retake.",
        )
    db.delete(grant)
    db.commit()
    return {"result": "success", "id": grant_id}


# ═══════════════════════════════════════════════════════════════════════════
# STUDENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════
#
# Visibility model: a student sees an exam iff they are enrolled in its
# course (``user_courses(user_id, dataset_id)``) and the exam is in state
# ``published`` and not soft-deleted.
#
# Hard-close at deadline: every mutation enforces ``now < min(deadline_at,
# attempt.due_at)``. If the user has an un-submitted attempt and the
# deadline elapses, the next access (list / start / submit / result) lazy
# auto-grades it with whatever responses were autosaved.
# ---------------------------------------------------------------------------


def _active_attempt(
    db: DBSession, exam_id, user_id: str
) -> Optional[ExamAttempt]:
    """The user's currently in-progress attempt for ``exam_id``, if any.

    Distinct from ``_latest_attempt`` because once retakes (Phase 4) are
    granted, the user can have multiple submitted attempts plus at most
    one active. The partial unique index on ``(exam_id, user_id) WHERE
    submitted_at IS NULL`` enforces the "at most one active" invariant
    server-side.
    """
    return (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.user_id == user_id,
            ExamAttempt.submitted_at.is_(None),
        )
        .first()
    )


def _latest_attempt(
    db: DBSession, exam_id, user_id: str
) -> Optional[ExamAttempt]:
    """The newest attempt for ``(exam_id, user_id)``, regardless of state.

    "Newest" wins for display-state and result resolution: when an admin
    grants a retake and the student takes it, the retake's score is the
    one shown in /exams and /result.
    """
    return (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.user_id == user_id,
        )
        .order_by(ExamAttempt.started_at.desc())
        .first()
    )


def _effective_score(attempt: ExamAttempt) -> tuple[float | None, float | None]:
    """Return ``(effective_raw, effective_pct)`` for an attempt.

    Manual override (set by admin) replaces the auto-graded raw score
    when present. ``score_pct`` is recomputed from the effective raw
    rather than read from the column so the override propagates without
    a second write.
    """
    if attempt.score_raw is None:
        return None, None
    raw = attempt.manual_override_score if attempt.manual_override_score is not None else attempt.score_raw
    total = attempt.total_points or 0
    pct = (raw / total * 100.0) if total else 0.0
    return raw, pct


def _ensure_enrolled(db: DBSession, user_id: str, dataset_id) -> None:
    """Reject 403 if the user is not enrolled in the exam's course."""
    enrolled = (
        db.query(UserCourse)
        .filter(
            UserCourse.user_id == user_id,
            UserCourse.dataset_id == dataset_id,
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course.",
        )


def _shuffled(items: list, seed: int) -> list:
    """Deterministic per-attempt shuffle. Returns a new list."""
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def _grade_attempt(db: DBSession, attempt: ExamAttempt, exam: Exam) -> None:
    """Grade ``attempt`` in place. Computes + persists per-response scores
    and the rolled-up ``score_raw`` / ``score_pct`` / ``total_points`` on
    the attempt itself. Caller commits.

    MCQ partial credit: ``max(0, (correct_selected - incorrect_selected) /
    num_correct)``. Penalises blanket "select all" guessing while crediting
    partial knowledge. T/F is binary — picking the one correct option is 1,
    anything else (including the wrong option, no answer, or both) is 0.
    """
    # Index existing responses by question_id
    responses = {
        str(r.question_id): r
        for r in db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt.id).all()
    }

    score_raw = 0.0
    total = 0
    for q in exam.questions:
        total += 1
        correct_ids = {str(o.id) for o in q.options if o.is_correct}
        resp = responses.get(str(q.id))
        selected = set(resp.selected_option_ids) if resp else set()

        if q.type == QuestionType.MCQ.value:
            num_correct = max(1, len(correct_ids))  # avoid div-by-zero on malformed q
            correctly_selected = len(selected & correct_ids)
            incorrectly_selected = len(selected - correct_ids)
            partial = max(
                0.0,
                (correctly_selected - incorrectly_selected) / num_correct,
            )
        else:  # true_false — must select exactly the single correct option
            partial = 1.0 if selected == correct_ids else 0.0

        if resp is None:
            # Persist a zero row so the gradebook (Phase 4) shows the gap
            # instead of a missing record.
            resp = ExamResponse(
                attempt_id=attempt.id,
                question_id=q.id,
                selected_option_ids=[],
                is_correct=False,
                partial_score=0.0,
            )
            db.add(resp)
        else:
            resp.is_correct = partial >= 0.999  # equal-weight binary correctness
            resp.partial_score = partial

        score_raw += partial

    attempt.score_raw = score_raw
    attempt.total_points = total
    attempt.score_pct = (score_raw / total * 100.0) if total else 0.0


def _maybe_lazy_close(db: DBSession, attempt: ExamAttempt, exam: Exam) -> bool:
    """If ``attempt`` is unsubmitted past its ``due_at``, force-grade it.

    Returns True if the attempt was closed by this call (caller commits).
    """
    if attempt.submitted_at is not None:
        return False
    now = datetime.now(timezone.utc)
    if now >= attempt.due_at:
        _grade_attempt(db, attempt, exam)
        attempt.submitted_at = attempt.due_at
        return True
    return False


def _serialize_question_for_student(
    q: ExamQuestion, option_seed: int
) -> dict:
    """Render a question for the taking-page. Strips ``is_correct``."""
    options = _shuffled(list(q.options), option_seed ^ _stable_hash31(str(q.id)))
    return {
        "id": str(q.id),
        "type": q.type,
        "text": q.text,
        "options": [
            {"id": str(o.id), "text": o.text, "position": i}
            for i, o in enumerate(options)
        ],
    }


def _attempt_due_at(exam: Exam, started_at: datetime) -> datetime:
    """``min(deadline_at, started_at + time_limit)``. Untimed = deadline."""
    if exam.time_limit_minutes is None:
        return exam.deadline_at
    from datetime import timedelta
    return min(
        exam.deadline_at,
        started_at + timedelta(minutes=exam.time_limit_minutes),
    )


# ---------------------------------------------------------------------------
# Student: list across enrolled courses
# ---------------------------------------------------------------------------

@student_router.get("")
async def list_exams_for_student(
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """List exams visible to the caller.

    Each row carries a computed display ``state``:
      * ``available``    — published, no attempt, ``now < deadline``
      * ``in_progress``  — un-submitted attempt with time remaining
      * ``submitted``    — caller has a finalised attempt
      * ``missed``       — past deadline, no attempt
      * ``past_deadline``— past deadline with an attempt that lazy-closed

    Lazy auto-close runs over any encountered un-submitted-but-past-due
    attempts so listing a stale exam returns a finalised state.
    """
    user_id = session.get_user_id()

    # All enrolled course IDs for the caller
    enrolled_dataset_ids = [
        r[0]
        for r in db.query(UserCourse.dataset_id)
        .filter(UserCourse.user_id == user_id)
        .all()
    ]
    if not enrolled_dataset_ids:
        return {"exams": []}

    exams = (
        db.query(Exam)
        .filter(
            Exam.dataset_id.in_(enrolled_dataset_ids),
            Exam.state == ExamState.PUBLISHED.value,
            Exam.deleted_at.is_(None),
        )
        .order_by(Exam.deadline_at.asc())
        .all()
    )

    # Bulk-load LATEST attempt per exam for the caller. Iterating in
    # ascending order and overwriting leaves the newest as the final
    # value in the dict — equivalent to a window function but trivial
    # to express in plain SQL.
    exam_ids = [e.id for e in exams]
    attempts_by_exam: dict[str, ExamAttempt] = {}
    grant_exams: set[str] = set()
    if exam_ids:
        for a in (
            db.query(ExamAttempt)
            .filter(
                ExamAttempt.exam_id.in_(exam_ids),
                ExamAttempt.user_id == user_id,
            )
            .order_by(ExamAttempt.started_at.asc())
            .all()
        ):
            attempts_by_exam[str(a.exam_id)] = a
        # Unconsumed grants — surfaces "retake available" on submitted exams.
        for g in (
            db.query(ExamAttemptGrant)
            .filter(
                ExamAttemptGrant.exam_id.in_(exam_ids),
                ExamAttemptGrant.user_id == user_id,
                ExamAttemptGrant.consumed.is_(False),
            )
            .all()
        ):
            grant_exams.add(str(g.exam_id))

    now = datetime.now(timezone.utc)
    closed_any = False
    rows: list[dict] = []
    for exam in exams:
        attempt = attempts_by_exam.get(str(exam.id))
        if attempt and attempt.submitted_at is None and now >= attempt.due_at:
            _grade_attempt(db, attempt, exam)
            attempt.submitted_at = attempt.due_at
            closed_any = True

        deadline_passed = now >= exam.deadline_at
        if attempt and attempt.submitted_at is not None:
            display_state = "submitted"
        elif attempt and attempt.submitted_at is None:
            display_state = "in_progress"
        elif deadline_passed:
            display_state = "missed"
        else:
            display_state = "available"

        time_remaining_seconds: Optional[int] = None
        if attempt and attempt.submitted_at is None:
            time_remaining_seconds = max(0, int((attempt.due_at - now).total_seconds()))

        # Retake available iff: submitted attempt + unconsumed grant + before deadline.
        can_retake = (
            display_state == "submitted"
            and str(exam.id) in grant_exams
            and not deadline_passed
        )

        # Resolve course_id slug for the URL
        # (one query per exam — fine for typical class sizes; could be
        # batched later if it ever shows up in profiling).
        dataset = db.query(Dataset).filter(Dataset.id == exam.dataset_id).first()

        eff_raw, eff_pct = _effective_score(attempt) if attempt and attempt.submitted_at else (None, None)
        rows.append({
            "id": str(exam.id),
            "course_id": dataset.course_id if dataset else None,
            "course_name": dataset.name if dataset else None,
            "title": exam.title,
            "description": exam.description,
            "deadline_at": exam.deadline_at.isoformat(),
            "time_limit_minutes": exam.time_limit_minutes,
            "question_count": len(exam.questions),
            "display_state": display_state,
            "score_pct": eff_pct,
            "submitted_at": attempt.submitted_at.isoformat() if attempt and attempt.submitted_at else None,
            "time_remaining_seconds": time_remaining_seconds,
            "can_retake": can_retake,
        })

    if closed_any:
        db.commit()

    return {"exams": rows}


# ---------------------------------------------------------------------------
# Student: pre-start summary
# ---------------------------------------------------------------------------

def _resolve_published_exam(db: DBSession, exam_id: str) -> Exam:
    """Strict resolver for endpoints that mutate state (start, autosave,
    submit). Only ``PUBLISHED`` exams accept new activity."""
    exam = (
        db.query(Exam)
        .filter(Exam.id == exam_id, Exam.deleted_at.is_(None))
        .first()
    )
    if not exam or exam.state != ExamState.PUBLISHED.value:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def _resolve_visible_exam(db: DBSession, exam_id: str) -> Exam:
    """Looser resolver for read-only access (e.g. ``/result``).

    Past students keep access to their score after an admin archives an
    exam — archive should hide the exam from new takers, not strand
    students from their grades. Soft-deleted exams stay hidden.
    """
    exam = (
        db.query(Exam)
        .filter(Exam.id == exam_id, Exam.deleted_at.is_(None))
        .first()
    )
    if not exam or exam.state not in (
        ExamState.PUBLISHED.value,
        ExamState.ARCHIVED.value,
    ):
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


@student_router.get("/{exam_id}")
async def get_exam_summary(
    exam_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Pre-start summary for the student. Does *not* return question text."""
    user_id = session.get_user_id()
    exam = _resolve_published_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    # Lazy-close the active attempt if past due, so display_state below
    # reflects reality rather than the stale row.
    active = _active_attempt(db, exam.id, user_id)
    if active and _maybe_lazy_close(db, active, exam):
        db.commit()

    latest = _latest_attempt(db, exam.id, user_id)
    has_grant = (
        db.query(ExamAttemptGrant)
        .filter(
            ExamAttemptGrant.exam_id == exam.id,
            ExamAttemptGrant.user_id == user_id,
            ExamAttemptGrant.consumed.is_(False),
        )
        .first()
        is not None
    )

    now = datetime.now(timezone.utc)
    deadline_passed = now >= exam.deadline_at
    if latest and latest.submitted_at is None:
        display_state = "in_progress"
    elif latest and latest.submitted_at is not None:
        display_state = "submitted"
    elif deadline_passed:
        display_state = "missed"
    else:
        display_state = "available"

    can_retake = (
        display_state == "submitted" and has_grant and not deadline_passed
    )

    return {
        "id": str(exam.id),
        "title": exam.title,
        "description": exam.description,
        "deadline_at": exam.deadline_at.isoformat(),
        "time_limit_minutes": exam.time_limit_minutes,
        "question_count": len(exam.questions),
        "display_state": display_state,
        "has_attempt": latest is not None,
        "can_retake": can_retake,
    }


# ---------------------------------------------------------------------------
# Student: start an attempt (idempotent — resumes existing if present)
# ---------------------------------------------------------------------------

class StartResponse(BaseModel):
    attempt_id: str
    started_at: str
    due_at: str


@student_router.post("/{exam_id}/start")
async def start_attempt(
    exam_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Begin the caller's attempt. Idempotent — returns the existing
    in-progress attempt if there is one. Rejects with 403 / 409 / 410 in
    the obvious bad states.
    """
    user_id = session.get_user_id()
    exam = _resolve_published_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    now = datetime.now(timezone.utc)
    if now >= exam.deadline_at:
        raise HTTPException(status_code=410, detail="Deadline has passed")

    # If there's an active attempt, just resume it.
    active = _active_attempt(db, exam.id, user_id)
    if active is not None:
        return StartResponse(
            attempt_id=str(active.id),
            started_at=active.started_at.isoformat(),
            due_at=active.due_at.isoformat(),
        )

    latest = _latest_attempt(db, exam.id, user_id)
    if latest is not None and latest.submitted_at is not None:
        # User already submitted. Allow a new attempt only if there's an
        # unconsumed retake grant; consume the oldest one (FIFO) so the
        # audit log is linear.
        grant = (
            db.query(ExamAttemptGrant)
            .filter(
                ExamAttemptGrant.exam_id == exam.id,
                ExamAttemptGrant.user_id == user_id,
                ExamAttemptGrant.consumed.is_(False),
            )
            .order_by(ExamAttemptGrant.granted_at.asc())
            .first()
        )
        if grant is None:
            raise HTTPException(
                status_code=409,
                detail="You have already submitted this exam.",
            )
        # Fall through to create a new attempt; mark the grant consumed
        # in the same transaction.
        consume_grant: Optional[ExamAttemptGrant] = grant
    else:
        consume_grant = None

    started_at = now
    due_at = _attempt_due_at(exam, started_at)
    attempt = ExamAttempt(
        exam_id=exam.id,
        user_id=user_id,
        started_at=started_at,
        due_at=due_at,
        question_order_seed=random.randint(1, 2**31 - 1),
        option_order_seed=random.randint(1, 2**31 - 1),
    )
    db.add(attempt)
    db.flush()  # populate attempt.id so we can reference it from the grant

    if consume_grant is not None:
        consume_grant.consumed = True
        consume_grant.consumed_at = now
        consume_grant.consumed_by_attempt_id = attempt.id

    db.commit()
    db.refresh(attempt)
    return StartResponse(
        attempt_id=str(attempt.id),
        started_at=attempt.started_at.isoformat(),
        due_at=attempt.due_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Student: fetch the current attempt (questions + saved responses)
# ---------------------------------------------------------------------------

@student_router.get("/{exam_id}/attempt")
async def get_attempt(
    exam_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Return the caller's current attempt with shuffled questions/options
    and any autosaved responses. Lazy-closes if past due.
    """
    user_id = session.get_user_id()
    exam = _resolve_published_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    # The taking-page is exclusively about the active attempt — closed
    # ones live under /result. If there's no active attempt but there
    # IS a latest one, route the client there with a deliberate 404.
    attempt = _active_attempt(db, exam.id, user_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="No attempt found — start the exam first.")

    closed = _maybe_lazy_close(db, attempt, exam)
    if closed:
        db.commit()

    questions = _shuffled(list(exam.questions), attempt.question_order_seed)
    rendered = [_serialize_question_for_student(q, attempt.option_order_seed) for q in questions]

    # Saved selections, keyed by question_id
    saved = {
        str(r.question_id): list(r.selected_option_ids)
        for r in db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt.id).all()
    }
    for q in rendered:
        q["selected_option_ids"] = saved.get(q["id"], [])

    now = datetime.now(timezone.utc)
    time_remaining = max(0, int((attempt.due_at - now).total_seconds()))

    return {
        "attempt_id": str(attempt.id),
        "exam_id": str(exam.id),
        "title": exam.title,
        "description": exam.description,
        "deadline_at": exam.deadline_at.isoformat(),
        "due_at": attempt.due_at.isoformat(),
        "time_remaining_seconds": time_remaining,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "questions": rendered,
    }


# ---------------------------------------------------------------------------
# Student: autosave a response
# ---------------------------------------------------------------------------

class AutosaveRequest(BaseModel):
    selected_option_ids: list[str] = Field(default_factory=list)


@student_router.put("/{exam_id}/attempt/responses/{question_id}")
async def autosave_response(
    exam_id: str,
    question_id: str,
    body: AutosaveRequest,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Upsert the caller's response to one question. Rejected after submit
    or after ``due_at``; the client can keep the user's local copy and
    surface the read-only state on next refresh."""
    user_id = session.get_user_id()
    exam = _resolve_published_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    attempt = _active_attempt(db, exam.id, user_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="No attempt — start first.")
    now = datetime.now(timezone.utc)
    if now >= attempt.due_at:
        # Lazy close so the next interaction surfaces the result cleanly.
        _grade_attempt(db, attempt, exam)
        attempt.submitted_at = attempt.due_at
        db.commit()
        raise HTTPException(status_code=410, detail="Time expired.")

    # Verify the question belongs to this exam, and the option ids belong to it
    question = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.id == question_id, ExamQuestion.exam_id == exam.id)
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    valid_option_ids = {str(o.id) for o in question.options}
    submitted_ids = list({oid for oid in body.selected_option_ids if oid in valid_option_ids})

    response = (
        db.query(ExamResponse)
        .filter(
            ExamResponse.attempt_id == attempt.id,
            ExamResponse.question_id == question.id,
        )
        .first()
    )
    if response is None:
        response = ExamResponse(
            attempt_id=attempt.id,
            question_id=question.id,
            selected_option_ids=submitted_ids,
        )
        db.add(response)
    else:
        response.selected_option_ids = submitted_ids

    db.commit()
    return {
        "result": "success",
        "question_id": question_id,
        "selected_option_ids": submitted_ids,
    }


# ---------------------------------------------------------------------------
# Student: submit (final)
# ---------------------------------------------------------------------------

@student_router.post("/{exam_id}/submit")
async def submit_attempt(
    exam_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Finalise the caller's attempt. Grades immediately. Rejects if
    already submitted; if past due, the lazy-close path produces the same
    grade and is exposed via /result."""
    user_id = session.get_user_id()
    exam = _resolve_published_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    attempt = _active_attempt(db, exam.id, user_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="No attempt — start first.")

    now = datetime.now(timezone.utc)
    if now >= attempt.due_at:
        # Treat as lazy-close at the deadline; grade with whatever was saved.
        _grade_attempt(db, attempt, exam)
        attempt.submitted_at = attempt.due_at
    else:
        _grade_attempt(db, attempt, exam)
        attempt.submitted_at = now

    db.commit()
    db.refresh(attempt)
    eff_raw, eff_pct = _effective_score(attempt)
    return {
        "result": "success",
        "attempt_id": str(attempt.id),
        "submitted_at": attempt.submitted_at.isoformat(),
        "score_pct": eff_pct,
        "score_raw": eff_raw,
        "total_points": attempt.total_points,
    }


# ---------------------------------------------------------------------------
# Student: result (post-submit)
# ---------------------------------------------------------------------------

@student_router.get("/{exam_id}/result")
async def get_result(
    exam_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Return the caller's score. Per-question detail (correct answers +
    explanations) is gated until the deadline has passed — until then the
    response is just the score so peers can't game it.

    Uses the looser ``_resolve_visible_exam`` so a student who took an
    exam still sees their grade after the admin archives it.
    """
    user_id = session.get_user_id()
    exam = _resolve_visible_exam(db, exam_id)
    _ensure_enrolled(db, user_id, exam.dataset_id)

    attempt = _latest_attempt(db, exam.id, user_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="No attempt found.")

    # If still active and past due, lazy-close.
    closed = _maybe_lazy_close(db, attempt, exam)
    if closed:
        db.commit()

    if attempt.submitted_at is None:
        raise HTTPException(status_code=409, detail="Attempt is still in progress.")

    now = datetime.now(timezone.utc)
    review_unlocked = now >= exam.deadline_at
    eff_raw, eff_pct = _effective_score(attempt)
    has_override = attempt.manual_override_score is not None

    base = {
        "attempt_id": str(attempt.id),
        "exam_id": str(exam.id),
        "title": exam.title,
        "submitted_at": attempt.submitted_at.isoformat(),
        "deadline_at": exam.deadline_at.isoformat(),
        "score_pct": eff_pct,
        "score_raw": eff_raw,
        "total_points": attempt.total_points,
        "review_unlocked": review_unlocked,
        # When an admin overrides, the student should see the auto-graded
        # original alongside the final to understand what changed.
        "auto_score_raw": attempt.score_raw if has_override else None,
        "manual_override": has_override,
    }
    if not review_unlocked:
        return base

    # Post-deadline: include per-question correctness + explanations.
    responses = {
        str(r.question_id): r
        for r in db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt.id).all()
    }
    questions = sorted(exam.questions, key=lambda q: q.position)
    review = []
    for q in questions:
        r = responses.get(str(q.id))
        review.append({
            "question_id": str(q.id),
            "type": q.type,
            "text": q.text,
            "explanation": q.explanation,
            "options": [
                {
                    "id": str(o.id),
                    "text": o.text,
                    "is_correct": o.is_correct,
                }
                for o in q.options
            ],
            "selected_option_ids": list(r.selected_option_ids) if r else [],
            "is_correct": bool(r.is_correct) if r else False,
            "partial_score": (r.partial_score if r and r.partial_score is not None else 0.0),
        })
    base["review"] = review
    return base
