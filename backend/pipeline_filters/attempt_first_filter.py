"""
Open WebUI inlet pipeline filter that enforces the "attempt first" policy.

Classifies incoming student messages and, for homework questions, checks
whether the student has shown evidence of a prior attempt.  Injects
appropriate system prompts to guide the tutor LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    HOMEWORK = "homework"
    CONCEPTUAL = "conceptual"
    PROCEDURAL = "procedural"
    META = "meta"


class AttemptQuality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AttemptResult:
    has_attempt: bool
    quality: Optional[str] = None  # low | medium | high
    evidence: str = ""


@dataclass
class ClassificationResult:
    message_type: str
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

_HOMEWORK_PATTERNS = [
    re.compile(r"\b(solve|calculate|compute|find the (value|answer|solution)|evaluate)\b", re.I),
    re.compile(r"\b(what is \d|how (many|much) (is|are|do))\b", re.I),
    re.compile(r"\b(homework|assignment|problem \d|exercise|question \d|worksheet)\b", re.I),
    re.compile(r"\b(simplif(y|ication)|factor(i[sz]e)?|derive|integrate|differentiate)\b", re.I),
    re.compile(r"\b(write (a |the )?(program|function|code|script) (that|to|which|for))\b", re.I),
    re.compile(r"\b(implement|create a class|write a method)\b", re.I),
    re.compile(r"\b(prove (that|the)|show that)\b", re.I),
    re.compile(r"\b(balance the equation|draw the (diagram|graph|circuit))\b", re.I),
    re.compile(r"=\s*\?", re.I),  # e.g. "x + 3 = ?"
]

_CONCEPTUAL_PATTERNS = [
    re.compile(r"\b(what (is|are|does)|explain|describe|define|meaning of)\b", re.I),
    re.compile(r"\b(why (is|does|do|are|did)|how (does|do|is|are) .+ work)\b", re.I),
    re.compile(r"\b(concept|theory|principle|theorem|definition|intuition)\b", re.I),
    re.compile(r"\b(difference between|compare|contrast|relation(ship)? between)\b", re.I),
    re.compile(r"\b(can you explain|what'?s the idea|help me understand)\b", re.I),
]

_PROCEDURAL_PATTERNS = [
    re.compile(r"\b(how (do|can|to|should) (i|you|we))\b", re.I),
    re.compile(r"\b(step(s| by step)|procedure|process|method|approach|technique)\b", re.I),
    re.compile(r"\b(how to (use|install|set up|configure|run|compile|debug))\b", re.I),
    re.compile(r"\b(tutorial|guide|walkthrough|instructions)\b", re.I),
]

_META_PATTERNS = [
    re.compile(r"\b(who are you|what (can|do) you do|your (name|purpose|role))\b", re.I),
    re.compile(r"\b(help me with|can you help|i need help)\b", re.I),
    re.compile(r"\b(thank(s| you)|good (job|bot)|nice)\b", re.I),
    re.compile(r"\b(hello|hi|hey|greetings|good (morning|afternoon|evening))\b", re.I),
    re.compile(r"\b(how does this (work|tutor)|what are (the )?rules)\b", re.I),
]

# ---------------------------------------------------------------------------
# Attempt detection patterns
# ---------------------------------------------------------------------------

_ATTEMPT_VERBAL_PATTERNS = [
    re.compile(r"\b(i tried|i attempted|my (approach|attempt|solution|answer|work))\b", re.I),
    re.compile(r"\b(i got (stuck|confused) (at|on|with|when))\b", re.I),
    re.compile(r"\b(here'?s (what|my)|this is (what|my))\b", re.I),
    re.compile(r"\b(i (think|believe|got) (the answer|it) (is|should be|might be|could be))\b", re.I),
    re.compile(r"\b(i (started|began) (by|with)|first i)\b", re.I),
    re.compile(r"\b(i (used|applied|substituted|plugged in))\b", re.I),
    re.compile(r"\b(my (code|program|script|function) (is|does|returns|outputs))\b", re.I),
    re.compile(r"\b(when i (run|execute|compile|test))\b", re.I),
    re.compile(r"\b(i keep getting|the (error|output|result) (is|says|shows))\b", re.I),
]

_MATH_WORK_PATTERNS = [
    # Variable assignment result following a comma/semicolon/so: ", x = 2" (student computed a value)
    re.compile(r"[,;]\s*\d*[a-z]\s*=\s*-?\d+\b", re.I),
    # Multi-step arithmetic showing intermediate results: "3 + 4 = 7"
    re.compile(r"\d+\s*[\+\*/]\s*\d+\s*=\s*\d+"),
    # Function definitions the student wrote: "f(x) = ..."
    re.compile(r"(f|g|h)\([a-z]\)\s*=", re.I),
    # Derivative notation in student work: "dy/dx"
    re.compile(r"d[a-z]/d[a-z]", re.I),
    # LaTeX expressions (student typed math)
    re.compile(r"\\(frac|int|sum|lim|sqrt)", re.I),
    # Step-by-step work indicators
    re.compile(r"step\s*\d+\s*:", re.I),
    # Conclusion indicators showing the student derived something
    re.compile(r"\b(therefore|thus|hence|so)\s*[:,]?\s*[a-z]\s*=\s*-?\d", re.I),
    # Showing intermediate algebra: "so 2x = 4" or "I got x = 5"
    re.compile(r"\b(so|got|gives|yields|equals)\s+\d*[a-z]\s*=\s*-?\d+", re.I),
]

_CODE_SNIPPET_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),  # fenced code block
    re.compile(r"(def |class |import |from .+ import |print\(|return |if __name__)"),
    re.compile(r"(function\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=)"),
    re.compile(r"(for\s*\(|while\s*\(|if\s*\(.*\)\s*\{)"),
    re.compile(r"(#include|int main|std::)"),
    re.compile(r"(public\s+class|System\.out\.println)"),
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_message(text: str) -> ClassificationResult:
    """Classify a student message into one of four types using keyword + pattern matching."""
    if not text or not text.strip():
        return ClassificationResult(message_type=MessageType.META.value, confidence=0.0)

    scores: dict[str, tuple[float, list[str]]] = {
        MessageType.HOMEWORK.value: (0.0, []),
        MessageType.CONCEPTUAL.value: (0.0, []),
        MessageType.PROCEDURAL.value: (0.0, []),
        MessageType.META.value: (0.0, []),
    }

    pattern_map = {
        MessageType.HOMEWORK.value: _HOMEWORK_PATTERNS,
        MessageType.CONCEPTUAL.value: _CONCEPTUAL_PATTERNS,
        MessageType.PROCEDURAL.value: _PROCEDURAL_PATTERNS,
        MessageType.META.value: _META_PATTERNS,
    }

    for msg_type, patterns in pattern_map.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                current_score, current_kw = scores[msg_type]
                scores[msg_type] = (current_score + 1.0, current_kw + [m.group(0)])

    # Pick the type with highest score; default to meta if all zero
    best_type = MessageType.META.value
    best_score = 0.0
    best_kw: list[str] = []

    for msg_type, (score, kw) in scores.items():
        if score > best_score:
            best_score = score
            best_type = msg_type
            best_kw = kw

    total = sum(s for s, _ in scores.values())
    confidence = best_score / total if total > 0 else 0.0

    return ClassificationResult(
        message_type=best_type,
        confidence=round(confidence, 2),
        matched_keywords=best_kw,
    )


# ---------------------------------------------------------------------------
# Attempt detector
# ---------------------------------------------------------------------------

def detect_attempt(text: str) -> AttemptResult:
    """Detect whether the student has shown evidence of a prior attempt."""
    if not text or not text.strip():
        return AttemptResult(has_attempt=False)

    evidence_parts: list[str] = []
    score = 0

    # Verbal indicators
    for pat in _ATTEMPT_VERBAL_PATTERNS:
        m = pat.search(text)
        if m:
            evidence_parts.append(f"verbal: {m.group(0)}")
            score += 1

    # Math work
    for pat in _MATH_WORK_PATTERNS:
        m = pat.search(text)
        if m:
            evidence_parts.append(f"math: {m.group(0)}")
            score += 2  # math work is stronger evidence

    # Code snippets
    for pat in _CODE_SNIPPET_PATTERNS:
        m = pat.search(text)
        if m:
            evidence_parts.append(f"code: {m.group(0)[:60]}")
            score += 2

    if score == 0:
        return AttemptResult(has_attempt=False)

    # Quality assessment
    if score >= 4:
        quality = AttemptQuality.HIGH.value
    elif score >= 2:
        quality = AttemptQuality.MEDIUM.value
    else:
        quality = AttemptQuality.LOW.value

    return AttemptResult(
        has_attempt=True,
        quality=quality,
        evidence="; ".join(evidence_parts),
    )


# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_PROMPT_HOMEWORK_NO_ATTEMPT = (
    "\n\n[TUTOR POLICY — ATTEMPT FIRST]\n"
    "The student appears to be asking for help with a homework problem but has "
    "not shown any prior work or attempt. Before providing guidance:\n"
    "1. Acknowledge the question positively.\n"
    "2. Ask the student to share what they have tried so far.\n"
    "3. Suggest a starting point or first step they could try.\n"
    "4. Do NOT provide the solution or a worked example yet.\n"
    "5. Use encouraging, growth-mindset language.\n"
)

_PROMPT_HOMEWORK_LOW_ATTEMPT = (
    "\n\n[TUTOR POLICY — ENCOURAGE MORE EFFORT]\n"
    "The student has shown a minimal attempt at the problem. Encourage them to "
    "develop their work further:\n"
    "1. Praise the effort they have shown so far.\n"
    "2. Ask targeted questions about their approach.\n"
    "3. Provide a small hint to move them forward, not the answer.\n"
    "4. Do NOT solve the problem; guide with Socratic questioning.\n"
)

_PROMPT_HOMEWORK_WITH_ATTEMPT = (
    "\n\n[TUTOR POLICY — HINT-BASED RESPONSE]\n"
    "The student has shown work on this problem. Provide guided assistance:\n"
    "1. Acknowledge and validate the work shown.\n"
    "2. Identify where they went right and where they may have gone wrong.\n"
    "3. Provide hints and guiding questions, not direct answers.\n"
    "4. If they are very close, give a more specific nudge.\n"
    "5. Offer a similar but different practice problem if helpful.\n"
)

_PROMPT_CONCEPTUAL = (
    "\n\n[TUTOR POLICY — CONCEPTUAL EXPLANATION]\n"
    "The student is asking a conceptual question. Provide clear explanation:\n"
    "1. Start with a high-level intuition or analogy.\n"
    "2. Build toward the formal definition step by step.\n"
    "3. Use examples to illustrate key points.\n"
    "4. Check understanding with a follow-up question.\n"
)

_PROMPT_PROCEDURAL = (
    "\n\n[TUTOR POLICY — PROCEDURAL GUIDANCE]\n"
    "The student is asking how to do something. Provide step-by-step guidance:\n"
    "1. Outline the general approach or procedure.\n"
    "2. Walk through each step clearly.\n"
    "3. Provide tips or common pitfalls to avoid.\n"
)


# ---------------------------------------------------------------------------
# AttemptFirstFilter — Open WebUI Inlet Filter
# ---------------------------------------------------------------------------

class AttemptFirstFilter:
    """
    Open WebUI inlet pipeline filter that enforces the attempt-first policy.

    Usage in Open WebUI pipeline config:
        filters = [AttemptFirstFilter()]
    """

    def __init__(self) -> None:
        # Conversation-level attempt tracking: {conversation_id: {turn: AttemptResult}}
        self._conversation_state: dict[str, dict[int, AttemptResult]] = {}

    def inlet(self, body: dict[str, Any], user: Optional[dict] = None) -> dict[str, Any]:
        """
        Process an incoming message before it reaches the LLM.

        Args:
            body: The Open WebUI message body containing 'messages' list and metadata.
            user: The authenticated user dict (may contain id, role, etc.).

        Returns:
            Modified body with injected system prompts as needed.
        """
        messages = body.get("messages", [])
        if not messages:
            return body

        # Get the latest user message
        last_user_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg
                break

        if last_user_msg is None:
            return body

        text = last_user_msg.get("content", "")
        if not text.strip():
            return body

        # Classify the message
        classification = classify_message(text)
        msg_type = classification.message_type

        # Track conversation state
        conv_id = body.get("chat_id", body.get("session_id", "default"))
        if conv_id not in self._conversation_state:
            self._conversation_state[conv_id] = {}
        turn = len([m for m in messages if m.get("role") == "user"])

        # Store metadata on the body for downstream filters
        body.setdefault("__metadata", {})
        body["__metadata"]["message_type"] = msg_type
        body["__metadata"]["classification_confidence"] = classification.confidence

        # Determine what system prompt to inject
        system_addition = ""

        if msg_type == MessageType.HOMEWORK.value:
            attempt = detect_attempt(text)

            # Also check if prior turns had attempts
            prior_attempts = self._conversation_state[conv_id]
            has_prior_attempt = any(a.has_attempt for a in prior_attempts.values())

            # Store this turn's attempt
            self._conversation_state[conv_id][turn] = attempt

            body["__metadata"]["attempt"] = {
                "has_attempt": attempt.has_attempt,
                "quality": attempt.quality,
                "evidence": attempt.evidence,
                "has_prior_attempt": has_prior_attempt,
            }

            if attempt.has_attempt:
                if attempt.quality == AttemptQuality.LOW.value and not has_prior_attempt:
                    system_addition = _PROMPT_HOMEWORK_LOW_ATTEMPT
                else:
                    system_addition = _PROMPT_HOMEWORK_WITH_ATTEMPT
            else:
                if has_prior_attempt:
                    # They showed work before in this conversation
                    system_addition = _PROMPT_HOMEWORK_WITH_ATTEMPT
                else:
                    system_addition = _PROMPT_HOMEWORK_NO_ATTEMPT

        elif msg_type == MessageType.CONCEPTUAL.value:
            system_addition = _PROMPT_CONCEPTUAL

        elif msg_type == MessageType.PROCEDURAL.value:
            system_addition = _PROMPT_PROCEDURAL

        # For meta messages, no special system prompt needed

        # Inject the system prompt
        if system_addition:
            self._inject_system_prompt(messages, system_addition)

        body["messages"] = messages
        return body

    @staticmethod
    def _inject_system_prompt(messages: list[dict], addition: str) -> None:
        """Append policy text to the system message, creating one if needed."""
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] = msg.get("content", "") + addition
                return
        # No system message exists — insert one at the beginning
        messages.insert(0, {"role": "system", "content": addition.strip()})

    def reset_conversation(self, conv_id: str) -> None:
        """Clear tracked state for a conversation."""
        self._conversation_state.pop(conv_id, None)
