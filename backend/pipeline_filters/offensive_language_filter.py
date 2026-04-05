"""
Open WebUI inlet pipeline filter for offensive language detection.

Normalizes obfuscated text, checks against blocklist, respects academic
allowlist, and applies severity-based actions (warn / block / escalate).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.utils.offensive_word_list import (
    AcademicTerm,
    OffensivePattern,
    OffensiveWordList,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class OffenseResult:
    is_offensive: bool
    severity: Optional[str] = None  # mild | moderate | severe
    categories: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    cleaned_text: str = ""


# ---------------------------------------------------------------------------
# Obfuscation decoder
# ---------------------------------------------------------------------------

class ObfuscationDecoder:
    """Normalizes common obfuscation tricks so the blocklist can match."""

    # Leetspeak map
    _LEET_MAP: dict[str, str] = {
        "4": "a", "@": "a",
        "8": "b",
        "(": "c", "[": "c", "{": "c",
        "3": "e",
        "6": "g", "9": "g",
        "#": "h",
        "1": "i", "!": "i", "|": "i",
        "0": "o",
        "5": "s", "$": "s",
        "7": "t", "+": "t",
        "2": "z",
    }

    # Unicode confusables (common ones)
    _CONFUSABLE_MAP: dict[str, str] = {
        "\u0430": "a",  # Cyrillic а
        "\u0435": "e",  # Cyrillic е
        "\u043e": "o",  # Cyrillic о
        "\u0440": "p",  # Cyrillic р
        "\u0441": "c",  # Cyrillic с
        "\u0443": "y",  # Cyrillic у
        "\u0445": "x",  # Cyrillic х
        "\u0456": "i",  # Cyrillic і
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\uff41": "a",  # fullwidth a
        "\uff42": "b",
        "\uff43": "c",
        "\uff44": "d",
        "\uff45": "e",
        "\uff46": "f",
    }

    def decode(self, text: str) -> str:
        """Apply all normalization layers and return cleaned text."""
        result = text
        result = self._normalize_unicode(result)
        result = self._decode_leetspeak(result)
        result = self._strip_inserted_chars(result)
        result = self._expand_abbreviations(result)
        return result

    def _normalize_unicode(self, text: str) -> str:
        """NFKD normalize + replace confusables."""
        # First, NFKD decomposition
        text = unicodedata.normalize("NFKD", text)
        # Replace known confusables
        chars = []
        for ch in text:
            chars.append(self._CONFUSABLE_MAP.get(ch, ch))
        return "".join(chars)

    def _decode_leetspeak(self, text: str) -> str:
        """Replace leetspeak characters with their letter equivalents."""
        chars = []
        for ch in text:
            chars.append(self._LEET_MAP.get(ch, ch))
        return "".join(chars)

    def _strip_inserted_chars(self, text: str) -> str:
        """Remove dots/spaces/special chars inserted between letters (e.g., f.u.c.k -> fuck).

        Strategy: if we see a pattern of single letters separated by the same
        separator character, collapse them.
        """
        # Pattern: letter, separator, letter, separator, letter (3+ chars)
        # e.g., "f.u.c.k", "f u c k", "f-u-c-k", "f*u*c*k"
        result = re.sub(
            r"\b([a-zA-Z])([.\-_*~`'\" ])\1?(?:[a-zA-Z]\2){2,}[a-zA-Z]\b",
            lambda m: m.group(0),  # keep original for now, real removal below
            text,
        )
        # More direct approach: collapse single chars separated by common separators
        result = re.sub(
            r"(?<![a-zA-Z])([a-zA-Z])[.\-_*~\s]+(?=[a-zA-Z][.\-_*~\s]+[a-zA-Z])",
            r"\1",
            result,
        )
        # Final cleanup: remaining single-char-separator patterns
        result = re.sub(
            r"(?<![a-zA-Z])([a-zA-Z])[.\-_*~\s]+([a-zA-Z])(?![a-zA-Z])",
            r"\1\2",
            result,
        )
        return result

    def _expand_abbreviations(self, text: str) -> str:
        """Expand common offensive abbreviations."""
        abbrevs = {
            r"\bstfu\b": "shut the fuck up",
            r"\bgtfo\b": "get the fuck out",
            r"\bwtf\b": "what the fuck",
            r"\bkys\b": "kill yourself",
            r"\bfml\b": "fuck my life",
            r"\bsmh\b": "shaking my head",
            r"\bpos\b": "piece of shit",
            r"\bsob\b": "son of a bitch",
        }
        result = text
        for pattern, expansion in abbrevs.items():
            result = re.sub(pattern, expansion, result, flags=re.IGNORECASE)
        return result


# ---------------------------------------------------------------------------
# Academic Allowlist checker
# ---------------------------------------------------------------------------

class AcademicAllowlist:
    """Checks if offensive-looking terms are legitimate in STEM context."""

    def __init__(self, word_list: OffensiveWordList) -> None:
        self._allowlist = word_list.allowlist

    def find_academic_terms(self, text: str) -> list[AcademicTerm]:
        """Return all academic terms found in the text."""
        return [term for term in self._allowlist if term.pattern.search(text)]

    def get_protected_spans(self, text: str) -> list[tuple[int, int]]:
        """Return (start, end) spans of academic terms that should be excluded."""
        spans = []
        for term in self._allowlist:
            for m in term.pattern.finditer(text):
                spans.append((m.start(), m.end()))
        return spans


# ---------------------------------------------------------------------------
# Core checker
# ---------------------------------------------------------------------------

def check_message(
    text: str,
    word_list: Optional[OffensiveWordList] = None,
    decoder: Optional[ObfuscationDecoder] = None,
) -> OffenseResult:
    """
    Check a message for offensive content.

    Returns an OffenseResult with severity, categories, matched terms,
    and a cleaned version of the text.
    """
    if not text or not text.strip():
        return OffenseResult(is_offensive=False, cleaned_text=text or "")

    if word_list is None:
        word_list = OffensiveWordList()
    if decoder is None:
        decoder = ObfuscationDecoder()

    # Step 1: find academic terms in the ORIGINAL text (before decoding)
    academic = AcademicAllowlist(word_list)
    academic_terms = academic.find_academic_terms(text)
    protected_spans = academic.get_protected_spans(text)

    # Step 2: decode obfuscation
    decoded = decoder.decode(text)

    # Also get academic terms from decoded text
    academic_terms_decoded = academic.find_academic_terms(decoded)
    protected_spans_decoded = academic.get_protected_spans(decoded)

    # Step 3: scan decoded text against blocklist
    matches: list[tuple[OffensivePattern, re.Match]] = []

    for pattern in word_list.patterns:
        for m in pattern.pattern.finditer(decoded):
            # Check if this match overlaps with any protected academic span
            match_start, match_end = m.start(), m.end()
            is_protected = False
            for ps, pe in protected_spans_decoded:
                if match_start >= ps and match_end <= pe:
                    is_protected = True
                    break
                # Partial overlap: also protect
                if match_start < pe and match_end > ps:
                    is_protected = True
                    break
            if not is_protected:
                matches.append((pattern, m))

    if not matches:
        return OffenseResult(is_offensive=False, cleaned_text=text)

    # Step 4: determine overall severity and categories
    severity_order = {"mild": 0, "moderate": 1, "severe": 2}
    categories: set[str] = set()
    matched_terms: list[str] = []
    max_severity = "mild"

    for pattern, m in matches:
        categories.add(pattern.category)
        matched_terms.append(pattern.term)
        if severity_order.get(pattern.severity, 0) > severity_order.get(max_severity, 0):
            max_severity = pattern.severity

    # Step 5: build cleaned text (replace offensive terms with asterisks)
    cleaned = text
    for pattern, m in matches:
        # Replace in the original text using the original pattern
        cleaned = pattern.pattern.sub(
            lambda match: "*" * len(match.group(0)),
            cleaned,
        )

    return OffenseResult(
        is_offensive=True,
        severity=max_severity,
        categories=sorted(categories),
        matched_terms=sorted(set(matched_terms)),
        cleaned_text=cleaned,
    )


# ---------------------------------------------------------------------------
# Policy response messages
# ---------------------------------------------------------------------------

_POLICY_WARN = (
    "Hey — just a heads-up: your message contained language that goes against "
    "our community guidelines. Let's keep things respectful so I can help you "
    "learn effectively. Your message has been cleaned up and sent through."
)

_POLICY_BLOCK_MODERATE = (
    "Your message was blocked because it contained language that violates our "
    "community guidelines. This incident has been noted on your account. "
    "Please rephrase your question respectfully and I'll be happy to help."
)

_POLICY_BLOCK_SEVERE = (
    "Your message has been blocked due to a serious policy violation. "
    "This incident has been logged and may be reviewed by your institution. "
    "If you believe this is a mistake, please contact your instructor."
)


# ---------------------------------------------------------------------------
# OffensiveLanguageFilter — Open WebUI Inlet Filter
# ---------------------------------------------------------------------------

class OffensiveLanguageFilter:
    """
    Open WebUI inlet pipeline filter that detects and handles offensive
    language in student messages.
    """

    def __init__(
        self,
        word_list: Optional[OffensiveWordList] = None,
        on_escalate: Optional[Any] = None,  # callback(user_id, severity, context)
        on_flag_user: Optional[Any] = None,  # callback(user_id, severity, category, msg_hash)
    ) -> None:
        self.word_list = word_list or OffensiveWordList()
        self.decoder = ObfuscationDecoder()
        self._on_escalate = on_escalate
        self._on_flag_user = on_flag_user
        self._incident_log: list[dict] = []

    def inlet(self, body: dict[str, Any], user: Optional[dict] = None) -> dict[str, Any]:
        """
        Process an incoming message, checking for offensive content.

        Depending on severity:
        - mild: warn user, send cleaned text to LLM
        - moderate: block message, return policy reminder
        - severe: block message, escalate, flag user

        Returns modified body dict. If blocked, sets body["__blocked"] = True
        and body["__policy_message"] with the user-facing message.
        """
        messages = body.get("messages", [])
        if not messages:
            return body

        # Find the latest user message
        last_user_msg = None
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_msg = messages[i]
                last_user_idx = i
                break

        if last_user_msg is None:
            return body

        text = last_user_msg.get("content", "")
        if not text.strip():
            return body

        result = check_message(text, self.word_list, self.decoder)

        user_id = (user or {}).get("id", "unknown")
        body.setdefault("__metadata", {})

        if not result.is_offensive:
            body["__metadata"]["offensive_check"] = {"is_offensive": False}
            return body

        # Log incident
        msg_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        incident = {
            "user_id": user_id,
            "severity": result.severity,
            "categories": result.categories,
            "matched_terms": result.matched_terms,
            "message_hash": msg_hash,
            "message_preview": text[:100],
        }
        self._incident_log.append(incident)

        body["__metadata"]["offensive_check"] = {
            "is_offensive": True,
            "severity": result.severity,
            "categories": result.categories,
        }

        if result.severity == "mild":
            # Warn but allow (with cleaned text)
            messages[last_user_idx]["content"] = result.cleaned_text
            body["messages"] = messages
            body["__policy_warning"] = _POLICY_WARN
            # Flag user
            if self._on_flag_user:
                self._on_flag_user(user_id, "mild", result.categories, msg_hash)
            return body

        elif result.severity == "moderate":
            # Block message
            body["__blocked"] = True
            body["__policy_message"] = _POLICY_BLOCK_MODERATE
            if self._on_flag_user:
                self._on_flag_user(user_id, "moderate", result.categories, msg_hash)
            return body

        else:  # severe
            # Block + escalate + flag
            body["__blocked"] = True
            body["__policy_message"] = _POLICY_BLOCK_SEVERE
            if self._on_flag_user:
                self._on_flag_user(user_id, "severe", result.categories, msg_hash)
            if self._on_escalate:
                self._on_escalate(user_id, result.severity, {
                    "categories": result.categories,
                    "matched_terms": result.matched_terms,
                    "message_hash": msg_hash,
                })
            return body

    def get_incident_log(self) -> list[dict]:
        """Return all logged incidents (for testing / admin review)."""
        return list(self._incident_log)
