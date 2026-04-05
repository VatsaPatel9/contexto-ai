"""
Open WebUI outlet pipeline filter for validating LLM responses.

Checks for canary token leaks, system prompt fragment leaks, solution leaks
(direct answers without scaffolding), and persona drift. Optionally replaces
violating responses with a safe fallback.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    violation_type: str      # "canary_leak" | "system_prompt_leak" | "solution_leak" | "persona_drift"
    description: str
    severity: str = "high"   # "low" | "medium" | "high"
    matched_text: str = ""


@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[Violation] = field(default_factory=list)
    sanitized_response: Optional[str] = None


# ---------------------------------------------------------------------------
# Safe fallback messages
# ---------------------------------------------------------------------------

_SAFE_FALLBACK = (
    "I'm here to help you learn! Let me know what concept you'd like "
    "to explore, and I'll guide you through it step by step."
)

_SAFE_FALLBACK_SOLUTION_LEAK = (
    "I want to help you understand this concept rather than just give you "
    "the answer. Let's work through it together. What part are you finding "
    "most challenging?"
)


# ---------------------------------------------------------------------------
# Canary token detector
# ---------------------------------------------------------------------------

class CanaryTokenDetector:
    """
    Checks if a configurable canary string from the system prompt appears
    in the LLM output. A canary is a unique token planted in the system
    prompt that should never appear in responses.
    """

    def __init__(self, canary_tokens: Optional[list[str]] = None) -> None:
        self.canary_tokens = canary_tokens or []

    def check(self, response_text: str) -> Optional[Violation]:
        """Return a Violation if any canary token is found in output."""
        response_lower = response_text.lower()
        for token in self.canary_tokens:
            if token.lower() in response_lower:
                return Violation(
                    violation_type="canary_leak",
                    description=f"Canary token found in output: '{token[:20]}...'",
                    severity="high",
                    matched_text=token,
                )
        return None


# ---------------------------------------------------------------------------
# System prompt leak detector
# ---------------------------------------------------------------------------

class SystemPromptLeakDetector:
    """
    Scans output for fragments of known system prompt instructions.
    """

    def __init__(self, system_prompt_fragments: Optional[list[str]] = None) -> None:
        self.fragments = system_prompt_fragments or []
        # Minimum fragment length to check (avoid false positives with short strings)
        self._min_fragment_len = 15

    def check(self, response_text: str) -> Optional[Violation]:
        """Return a Violation if system prompt fragments are found in output."""
        response_lower = response_text.lower()
        for fragment in self.fragments:
            if len(fragment) < self._min_fragment_len:
                continue
            if fragment.lower() in response_lower:
                return Violation(
                    violation_type="system_prompt_leak",
                    description="System prompt fragment detected in output",
                    severity="high",
                    matched_text=fragment[:50],
                )
        return None


# ---------------------------------------------------------------------------
# Solution leak detector
# ---------------------------------------------------------------------------

class SolutionLeakDetector:
    """
    Detects if a response provides a direct complete answer without
    pedagogical scaffolding (hints, guiding questions, etc.).
    """

    # Patterns indicating a direct final answer
    _ANSWER_PATTERNS: list[re.Pattern] = [
        re.compile(r"(?:the\s+)?answer\s+is\s+[\d\.\-]+", re.IGNORECASE),
        re.compile(r"(?:the\s+)?solution\s+is\s+[\d\.\-]+", re.IGNORECASE),
        re.compile(r"therefore\s+x\s*=\s*[\d\.\-]+", re.IGNORECASE),
        re.compile(r"therefore\s+y\s*=\s*[\d\.\-]+", re.IGNORECASE),
        re.compile(r"=\s*[\d\.\-]+\s*$", re.MULTILINE),  # ends with "= 42"
        re.compile(r"(?:the\s+)?(?:final\s+)?result\s+is\s+[\d\.\-]+", re.IGNORECASE),
        re.compile(r"(?:so|thus|hence)\s+the\s+(?:answer|solution|result)\s+is\b", re.IGNORECASE),
    ]

    # Patterns indicating scaffolding / pedagogical approach
    _SCAFFOLDING_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bhint\s*:", re.IGNORECASE),
        re.compile(r"\btry\s+(thinking|considering|looking)\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+(do\s+you\s+think|happens|would|if)\b", re.IGNORECASE),
        re.compile(r"\bcan\s+you\s+(think|figure|try|see)\b", re.IGNORECASE),
        re.compile(r"\bconsider\s+(what|how|why|the)\b", re.IGNORECASE),
        re.compile(r"\blet'?s?\s+(think|work|start|look|consider|break)\b", re.IGNORECASE),
        re.compile(r"\bfirst,?\s+(think|consider|try|let)\b", re.IGNORECASE),
        re.compile(r"\bstep\s+\d+\s*:", re.IGNORECASE),
        re.compile(r"\bwhat\s+approach\b", re.IGNORECASE),
        re.compile(r"\bhow\s+would\s+you\b", re.IGNORECASE),
        re.compile(r"\?$", re.MULTILINE),  # response contains a question
        re.compile(r"___+|\.\.\.|\[fill\s+in\]|\[your\s+answer\]", re.IGNORECASE),
        re.compile(r"\btry\s+it\b", re.IGNORECASE),
    ]

    # Patterns for "I'll solve this for you" language
    _DIRECT_SOLVE_PATTERNS: list[re.Pattern] = [
        re.compile(r"i'?ll?\s+solve\s+this\s+for\s+you", re.IGNORECASE),
        re.compile(r"here'?s?\s+the\s+complete\s+solution", re.IGNORECASE),
        re.compile(r"here'?s?\s+the\s+(?:full|entire)\s+(?:answer|solution|code)", re.IGNORECASE),
        re.compile(r"the\s+complete\s+(?:answer|solution)\s+is", re.IGNORECASE),
        re.compile(r"let\s+me\s+(?:just\s+)?(?:solve|answer)\s+(?:this|that|it)\s+(?:directly|for\s+you)", re.IGNORECASE),
    ]

    # Pattern for complete code solutions (function with return value)
    _CODE_SOLUTION_PATTERN = re.compile(
        r"```\w*\n"                             # opening code fence
        r".*?"                                   # any content (non-greedy)
        r"(?:def\s+\w+|function\s+\w+|int\s+\w+|public\s+\w+)"  # function definition
        r".*?"                                   # function body
        r"return\s+.+?"                          # return statement
        r".*?"                                   # any trailing content
        r"```",                                  # closing code fence
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern for code with blanks/skeleton (allowed)
    _CODE_SKELETON_PATTERNS: list[re.Pattern] = [
        re.compile(r"(?:TODO|FIXME|pass|\.\.\.|\#\s*your\s+code)", re.IGNORECASE),
        re.compile(r"___+", re.IGNORECASE),
        re.compile(r"\?\?\?", re.IGNORECASE),
        re.compile(r"\#\s*fill\s+(?:in|this)", re.IGNORECASE),
    ]

    def check(self, response_text: str) -> list[Violation]:
        """Return a list of violations found in the response."""
        violations: list[Violation] = []

        # Check for direct solve language
        for pat in self._DIRECT_SOLVE_PATTERNS:
            m = pat.search(response_text)
            if m:
                violations.append(Violation(
                    violation_type="solution_leak",
                    description="Response uses direct-solve language",
                    severity="high",
                    matched_text=m.group(0),
                ))

        # Check for answer patterns without scaffolding
        has_answer = any(pat.search(response_text) for pat in self._ANSWER_PATTERNS)
        has_scaffolding = any(pat.search(response_text) for pat in self._SCAFFOLDING_PATTERNS)

        if has_answer and not has_scaffolding:
            violations.append(Violation(
                violation_type="solution_leak",
                description="Direct answer provided without scaffolding",
                severity="high",
                matched_text="",
            ))

        # Check for complete code solutions
        code_match = self._CODE_SOLUTION_PATTERN.search(response_text)
        if code_match:
            code_block = code_match.group(0)
            # Check if it's a skeleton with blanks (allowed)
            is_skeleton = any(pat.search(code_block) for pat in self._CODE_SKELETON_PATTERNS)
            if not is_skeleton:
                violations.append(Violation(
                    violation_type="solution_leak",
                    description="Complete code solution provided without blanks",
                    severity="medium",
                    matched_text=code_block[:100],
                ))

        return violations


# ---------------------------------------------------------------------------
# Persona drift detector
# ---------------------------------------------------------------------------

class PersonaDriftDetector:
    """
    Checks if the response contradicts the AI tutor persona.
    """

    _DRIFT_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"i'?m\s+not\s+(?:really\s+)?a\s+tutor", re.IGNORECASE),
         "Denies being a tutor"),
        (re.compile(r"i\s+(?:don'?t|cannot|can'?t)\s+(?:act\s+as|be)\s+a\s+tutor", re.IGNORECASE),
         "Refuses tutor role"),
        (re.compile(r"i\s+(?:am|'m)\s+(?:actually|really)\s+(?:a|an)\s+(?!tutor|AI\s+tutor|learning)", re.IGNORECASE),
         "Claims non-tutor identity"),
        (re.compile(r"i'?ll?\s+(?:just\s+)?(?:solve|answer|give\s+you)\s+(?:this|that|it|the\s+answer)", re.IGNORECASE),
         "Offers to directly solve"),
        (re.compile(r"(?:my\s+)?(?:real|true|actual)\s+(?:purpose|function|role)\s+is\s+(?!to\s+(?:help|tutor|teach|guide|assist))", re.IGNORECASE),
         "Claims different purpose"),
        (re.compile(r"i\s+(?:was|have\s+been)\s+(?:jailbroken|freed|liberated|unlocked)", re.IGNORECASE),
         "Claims to be jailbroken"),
        (re.compile(r"(?:entering|activat(?:ed?|ing)|enabl(?:ed?|ing))\s+(?:DAN|developer|god|sudo|unrestricted)\s+mode", re.IGNORECASE),
         "Claims mode change"),
        (re.compile(r"(?:DAN|developer|god|sudo|unrestricted)\s+mode\s+(?:enabled|activated|engaged|on)", re.IGNORECASE),
         "Claims mode change"),
    ]

    def check(self, response_text: str) -> list[Violation]:
        """Return violations for persona drift."""
        violations: list[Violation] = []
        for pat, desc in self._DRIFT_PATTERNS:
            m = pat.search(response_text)
            if m:
                violations.append(Violation(
                    violation_type="persona_drift",
                    description=desc,
                    severity="high",
                    matched_text=m.group(0),
                ))
        return violations


# ---------------------------------------------------------------------------
# Main filter
# ---------------------------------------------------------------------------

class OutputValidationFilter:
    """
    Open WebUI outlet pipeline filter that validates LLM responses.

    Checks for:
    - Canary token leaks
    - System prompt fragment leaks
    - Solution leaks (direct answers without scaffolding)
    - Persona drift

    On violation, optionally replaces response with a safe fallback.
    """

    def __init__(
        self,
        canary_tokens: Optional[list[str]] = None,
        system_prompt_fragments: Optional[list[str]] = None,
        replace_on_violation: bool = True,
    ) -> None:
        self.canary_detector = CanaryTokenDetector(canary_tokens)
        self.leak_detector = SystemPromptLeakDetector(system_prompt_fragments)
        self.solution_detector = SolutionLeakDetector()
        self.persona_detector = PersonaDriftDetector()
        self.replace_on_violation = replace_on_violation
        self._incident_log: list[dict] = []

    def outlet(self, body: dict[str, Any], user: Optional[dict] = None) -> dict[str, Any]:
        """
        Validate the LLM response before sending to user.

        If violations are found and replace_on_violation is True,
        replaces the assistant's response with a safe fallback.
        """
        messages = body.get("messages", [])
        if not messages:
            return body

        # Find the latest assistant message
        last_assistant_msg = None
        last_assistant_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                last_assistant_msg = messages[i]
                last_assistant_idx = i
                break

        if last_assistant_msg is None:
            return body

        response_text = last_assistant_msg.get("content", "")
        if not response_text.strip():
            return body

        user_id = (user or {}).get("id", "unknown")

        # Run validation
        result = self.validate(response_text)

        body.setdefault("__metadata", {})
        body["__metadata"]["output_validation"] = {
            "is_valid": result.is_valid,
            "violation_count": len(result.violations),
            "violation_types": [v.violation_type for v in result.violations],
        }

        if not result.is_valid:
            # Log the incident
            incident = {
                "user_id": user_id,
                "violations": [
                    {
                        "type": v.violation_type,
                        "description": v.description,
                        "severity": v.severity,
                    }
                    for v in result.violations
                ],
                "response_preview": response_text[:200],
            }
            self._incident_log.append(incident)
            logger.warning(
                "Output validation failed: user=%s violations=%s",
                user_id,
                [v.violation_type for v in result.violations],
            )

            # Replace response if configured to do so
            if self.replace_on_violation and result.sanitized_response:
                messages[last_assistant_idx]["content"] = result.sanitized_response
                body["messages"] = messages
                body["__response_replaced"] = True

        return body

    def validate(self, response_text: str) -> ValidationResult:
        """
        Validate a response string.

        Returns a ValidationResult with any violations found.
        """
        violations: list[Violation] = []

        # Check canary tokens
        canary_v = self.canary_detector.check(response_text)
        if canary_v:
            violations.append(canary_v)

        # Check system prompt leaks
        leak_v = self.leak_detector.check(response_text)
        if leak_v:
            violations.append(leak_v)

        # Check solution leaks
        solution_vs = self.solution_detector.check(response_text)
        violations.extend(solution_vs)

        # Check persona drift
        persona_vs = self.persona_detector.check(response_text)
        violations.extend(persona_vs)

        if not violations:
            return ValidationResult(is_valid=True)

        # Determine fallback message based on violation types
        violation_types = {v.violation_type for v in violations}
        if "solution_leak" in violation_types:
            fallback = _SAFE_FALLBACK_SOLUTION_LEAK
        else:
            fallback = _SAFE_FALLBACK

        return ValidationResult(
            is_valid=False,
            violations=violations,
            sanitized_response=fallback,
        )

    def get_incident_log(self) -> list[dict]:
        """Return all logged validation incidents."""
        return list(self._incident_log)
