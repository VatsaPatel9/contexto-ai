"""
Open WebUI inlet pipeline filter for prompt injection attack detection.

Detects direct overrides, role-play attacks, extraction attempts, mode
switching, XML/markup injection, and encoding-based evasion techniques.
Normalizes unicode and leetspeak before pattern matching.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.utils.unicode_normalizer import (
    ZERO_WIDTH_CHARS,
    decode_all,
    decode_leetspeak,
    detect_encoding,
    normalize,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class InjectionResult:
    is_injection: bool
    confidence: float = 0.0
    attack_type: str = ""
    matched_patterns: list[str] = field(default_factory=list)
    normalized_input: str = ""


# ---------------------------------------------------------------------------
# Pattern detector
# ---------------------------------------------------------------------------

class InjectionPatternDetector:
    """Regex-based detector for known prompt injection patterns."""

    # Each entry: (compiled_regex, attack_type_label, human-readable description)
    _PATTERNS: list[tuple[re.Pattern, str, str]] = []

    def __init__(self) -> None:
        if not InjectionPatternDetector._PATTERNS:
            InjectionPatternDetector._build_patterns()

    @classmethod
    def _build_patterns(cls) -> None:
        """Compile all detection patterns once."""
        raw: list[tuple[str, str, str]] = [
            # --- Direct overrides ---
            (r"ignore\s+(all\s+)?previous\s+instructions", "direct_override", "ignore previous instructions"),
            (r"ignore\s+all\s+instructions", "direct_override", "ignore all instructions"),
            (r"disregard\s+(all\s+)?(above|previous|prior|earlier)", "direct_override", "disregard above"),
            (r"forget\s+(all\s+)?your\s+instructions", "direct_override", "forget your instructions"),
            (r"new\s+instructions\s*:", "direct_override", "new instructions:"),
            (r"(?:^|\s)SYSTEM\s*:", "direct_override", "SYSTEM:"),
            (r"you\s+are\s+now\b", "direct_override", "you are now"),
            (r"override\s+(all\s+)?(previous\s+)?instructions", "direct_override", "override instructions"),
            (r"do\s+not\s+follow\s+(your\s+)?instructions", "direct_override", "do not follow instructions"),
            (r"stop\s+being\s+a\s+tutor", "direct_override", "stop being a tutor"),
            (r"from\s+now\s+on\s+(you\s+)?(are|will|must|should)", "direct_override", "from now on you are"),

            # --- Role-play attacks ---
            (r"pretend\s+(that\s+)?you\s*(are|'re)\b", "role_play", "pretend you are"),
            (r"act\s+as\s+if\s+you\b", "role_play", "act as if you"),
            (r"roleplay\s+as\b", "role_play", "roleplay as"),
            (r"imagine\s+you\s+are\s+a\b", "role_play", "imagine you are a"),
            (r"you\s+are\s+no\s+longer\s+a\s+tutor", "role_play", "you are no longer a tutor"),
            (r"behave\s+(like|as)\s+(a\s+)?(?!a\s+student)", "role_play", "behave like/as"),
            (r"play\s+the\s+role\s+of\b", "role_play", "play the role of"),
            (r"take\s+on\s+the\s+persona\s+of\b", "role_play", "take on the persona of"),

            # --- Extraction attempts ---
            (r"repeat\s+your\s+system\s+prompt", "extraction", "repeat your system prompt"),
            (r"print\s+your\s+instructions", "extraction", "print your instructions"),
            (r"show\s+me\s+your\s+prompt", "extraction", "show me your prompt"),
            (r"what\s+are\s+your\s+rules", "extraction", "what are your rules"),
            (r"output\s+your\s+configuration", "extraction", "output your configuration"),
            (r"reveal\s+your\s+(system\s+)?(prompt|instructions|rules)", "extraction", "reveal your prompt"),
            (r"display\s+your\s+(initial|system|original)\s+(prompt|instructions)", "extraction", "display your prompt"),
            (r"tell\s+me\s+your\s+(system\s+)?(prompt|instructions|rules)", "extraction", "tell me your prompt"),
            (r"what\s+(is|was)\s+your\s+(system\s+)?(prompt|instruction)", "extraction", "what is your prompt"),
            (r"(dump|leak|expose)\s+your\s+(system|initial)\s+(prompt|instructions)", "extraction", "dump your prompt"),
            (r"print\s+instructions\s+in\s+base64", "extraction", "print instructions in base64"),

            # --- Mode switching ---
            (r"developer\s+mode", "mode_switch", "developer mode"),
            (r"DAN\s+mode", "mode_switch", "DAN mode"),
            (r"sudo\s+mode", "mode_switch", "sudo mode"),
            (r"\bjailbreak\b", "mode_switch", "jailbreak"),
            (r"unrestricted\s+mode", "mode_switch", "unrestricted mode"),
            (r"enable\s+debug\b", "mode_switch", "enable debug"),
            (r"\bsudo\b(?!\s+apt)(?!\s+pip)(?!\s+rm)", "mode_switch", "sudo command"),
            (r"god\s+mode", "mode_switch", "god mode"),
            (r"admin\s+mode", "mode_switch", "admin mode"),
            (r"maintenance\s+mode", "mode_switch", "maintenance mode"),

            # --- XML / markup injection ---
            (r"</system\s*>", "markup_injection", "</system> tag"),
            (r"</instructions\s*>", "markup_injection", "</instructions> tag"),
            (r"<\|im_start\|>", "markup_injection", "<|im_start|> token"),
            (r"\[INST\]", "markup_injection", "[INST] tag"),
            (r"\[/INST\]", "markup_injection", "[/INST] tag"),
            (r"```\s*system\b", "markup_injection", "markdown system redefinition"),
            (r"```\s*(?:instruction|prompt|config)", "markup_injection", "markdown instruction block"),

            # --- Conversation manipulation ---
            (r"forget\s+everything", "conversation_manipulation", "forget everything"),
            (r"start\s+fresh\s+as\b", "conversation_manipulation", "start fresh as"),
            (r"reset\s+your\s+(context|memory|conversation)", "conversation_manipulation", "reset context"),
            (r"clear\s+your\s+(memory|context|instructions)", "conversation_manipulation", "clear memory"),
            (r"here'?s?\s+how\s+you\s+answered\s+before", "few_shot_injection", "fake prior answer"),
            (r"previously\s+you\s+said", "few_shot_injection", "fake previous response"),
            (r"you\s+already\s+told\s+me\s+the\s+answer", "few_shot_injection", "fake prior answer claim"),

            # --- Authority claims ---
            (r"i'?m\s+(the\s+)?(professor|teacher|instructor|admin)", "authority_claim", "authority claim"),
            (r"as\s+(your\s+)?(professor|teacher|admin|creator)", "authority_claim", "authority claim"),
            (r"i\s+(created|made|built|programmed)\s+you", "authority_claim", "creator claim"),

            # --- Hypothetical / story bypasses ---
            (r"hypothetically,?\s+what\s+would\s+the\s+answer\s+be", "indirect_bypass", "hypothetical bypass"),
            (r"translate\s+the\s+solution\s+to\b", "indirect_bypass", "translation bypass"),
            (r"write\s+a\s+story\s+where\s+a?\s*character\s+solves", "indirect_bypass", "story mode bypass"),
        ]

        cls._PATTERNS = [
            (re.compile(pat, re.IGNORECASE), atype, desc)
            for pat, atype, desc in raw
        ]

    def scan(self, text: str) -> list[tuple[str, str, float]]:
        """
        Scan text for injection patterns.

        Returns list of (attack_type, pattern_description, confidence).
        """
        matches: list[tuple[str, str, float]] = []
        for regex, attack_type, desc in self._PATTERNS:
            if regex.search(text):
                # Higher confidence for direct overrides and extraction
                confidence = {
                    "direct_override": 0.95,
                    "extraction": 0.90,
                    "mode_switch": 0.90,
                    "markup_injection": 0.95,
                    "role_play": 0.85,
                    "conversation_manipulation": 0.85,
                    "few_shot_injection": 0.80,
                    "authority_claim": 0.80,
                    "indirect_bypass": 0.75,
                }.get(attack_type, 0.70)
                matches.append((attack_type, desc, confidence))
        return matches


# ---------------------------------------------------------------------------
# Unicode normalizer wrapper
# ---------------------------------------------------------------------------

class UnicodeNormalizer:
    """
    Wraps the unicode_normalizer utility for use in the injection pipeline.

    Applies full normalization + leetspeak decoding + encoding decoding.
    """

    def normalize_full(self, text: str) -> str:
        """Apply all normalization and decoding layers."""
        result = normalize(text)
        result = decode_leetspeak(result)
        result = decode_all(result)
        return result

    def strip_zero_width(self, text: str) -> str:
        """Remove zero-width characters only."""
        return "".join(ch for ch in text if ch not in ZERO_WIDTH_CHARS)

    def has_encoding(self, text: str) -> bool:
        """Check if text contains any encoded payloads."""
        return len(detect_encoding(text)) > 0


# ---------------------------------------------------------------------------
# Token splitting detector
# ---------------------------------------------------------------------------

class TokenSplittingDetector:
    """
    Detects injection phrases split across multiple messages in
    conversation history.
    """

    # Phrases to detect when concatenated across messages
    _SPLIT_PHRASES: list[str] = [
        "ignore previous instructions",
        "ignore all instructions",
        "disregard above",
        "forget your instructions",
        "system prompt",
        "developer mode",
        "jailbreak",
        "sudo mode",
        "you are now",
        "pretend you are",
        "unrestricted mode",
        "new instructions",
        "override instructions",
        "forget everything",
    ]

    def check_conversation(self, messages: list[dict]) -> Optional[tuple[str, float]]:
        """
        Check if recent user messages, when concatenated, form an
        injection phrase.

        Returns (matched_phrase, confidence) or None.
        """
        # Extract last N user messages
        user_messages = [
            m.get("content", "").strip().lower()
            for m in messages
            if m.get("role") == "user"
        ]

        if len(user_messages) < 2:
            return None

        # Check sliding windows of 2-5 consecutive messages
        for window_size in range(2, min(6, len(user_messages) + 1)):
            for start in range(len(user_messages) - window_size + 1):
                window = user_messages[start:start + window_size]
                concatenated = " ".join(window)
                # Also try direct concatenation (no space) for character-split attacks
                direct_concat = "".join(window)

                for phrase in self._SPLIT_PHRASES:
                    if phrase in concatenated or phrase in direct_concat:
                        return (phrase, 0.75)

        return None


# ---------------------------------------------------------------------------
# Reverse text detector
# ---------------------------------------------------------------------------

_REVERSE_KEYWORDS = [
    "ignore previous instructions",
    "ignore all instructions",
    "system prompt",
    "forget your instructions",
    "jailbreak",
    "developer mode",
    "new instructions",
]


def _check_reversed_text(text: str) -> Optional[str]:
    """Check if text contains reversed injection phrases."""
    reversed_text = text[::-1].lower()
    for keyword in _REVERSE_KEYWORDS:
        if keyword in reversed_text:
            return keyword
    return None


# ---------------------------------------------------------------------------
# Main filter
# ---------------------------------------------------------------------------

# Academic context patterns that should NOT be flagged
_ACADEMIC_CONTEXT_PATTERNS = [
    re.compile(r"(?:instructions?\s+for\s+(?:this|the)\s+(?:lab|assignment|homework|project|exam|quiz|exercise))", re.IGNORECASE),
    re.compile(r"(?:what\s+are\s+the\s+instructions\s+for)", re.IGNORECASE),
    re.compile(r"(?:follow(?:ing)?\s+the\s+instructions\s+(?:in|on|from))", re.IGNORECASE),
    re.compile(r"(?:(?:lab|assignment|homework|project)\s+instructions)", re.IGNORECASE),
    re.compile(r"(?:your\s+rules?\s+(?:about|regarding|for|on)\s+\w+)", re.IGNORECASE),
]


class PromptInjectionFilter:
    """
    Open WebUI inlet pipeline filter that detects prompt injection attacks.

    Uses pattern-based detection, unicode normalization, encoding detection,
    token splitting detection, and reverse text detection.
    """

    def __init__(self) -> None:
        self.pattern_detector = InjectionPatternDetector()
        self.normalizer = UnicodeNormalizer()
        self.splitting_detector = TokenSplittingDetector()
        self._injection_counter: dict[str, int] = {}
        self._incident_log: list[dict] = []

    def inlet(self, body: dict[str, Any], user: Optional[dict] = None) -> dict[str, Any]:
        """
        Process an incoming message, checking for prompt injection attacks.

        If an injection is detected:
        - Sets body["__blocked"] = True
        - Sets body["__injection_result"] with detection details
        - Sets body["__policy_message"] with user-facing message
        - Logs the attempt and increments user's injection counter
        """
        messages = body.get("messages", [])
        if not messages:
            return body

        # Find latest user message
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

        user_id = (user or {}).get("id", "unknown")

        # Run detection
        result = self.check_injection(text, messages)

        body.setdefault("__metadata", {})
        body["__metadata"]["injection_check"] = {
            "is_injection": result.is_injection,
            "confidence": result.confidence,
            "attack_type": result.attack_type,
        }
        body["__injection_result"] = {
            "is_injection": result.is_injection,
            "confidence": result.confidence,
            "attack_type": result.attack_type,
            "matched_patterns": result.matched_patterns,
            "normalized_input": result.normalized_input,
        }

        if result.is_injection:
            body["__blocked"] = True
            body["__policy_message"] = (
                "Your message was blocked because it appears to contain a "
                "prompt injection attempt. If you believe this is a mistake, "
                "please rephrase your question about the course material."
            )

            # Log and increment counter
            self._injection_counter[user_id] = self._injection_counter.get(user_id, 0) + 1
            incident = {
                "user_id": user_id,
                "attack_type": result.attack_type,
                "confidence": result.confidence,
                "matched_patterns": result.matched_patterns,
                "message_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
                "injection_count": self._injection_counter[user_id],
            }
            self._incident_log.append(incident)
            logger.warning(
                "Prompt injection detected: user=%s type=%s confidence=%.2f patterns=%s",
                user_id, result.attack_type, result.confidence, result.matched_patterns,
            )

        return body

    def check_injection(self, text: str, messages: Optional[list[dict]] = None) -> InjectionResult:
        """
        Check a single text (and optionally conversation history) for
        prompt injection attacks.

        This is the core detection method, usable independently of the
        inlet pipeline.
        """
        all_matches: list[tuple[str, str, float]] = []

        # Step 0: check for academic context (false positive suppression)
        for pat in _ACADEMIC_CONTEXT_PATTERNS:
            if pat.search(text):
                return InjectionResult(
                    is_injection=False,
                    confidence=0.0,
                    attack_type="",
                    matched_patterns=[],
                    normalized_input=text,
                )

        # Step 1: normalize text
        normalized = self.normalizer.normalize_full(text)

        # Step 2: scan original text for patterns
        raw_matches = self.pattern_detector.scan(text)
        all_matches.extend(raw_matches)

        # Step 3: scan normalized text for patterns (catches obfuscated attacks)
        if normalized.lower() != text.lower():
            norm_matches = self.pattern_detector.scan(normalized)
            for m in norm_matches:
                if m not in all_matches:
                    all_matches.append(m)

        # Step 4: check for encoding-based attacks
        encodings = detect_encoding(text)
        for enc in encodings:
            # Scan the decoded payload for patterns
            enc_matches = self.pattern_detector.scan(enc.decoded_text)
            for atype, desc, conf in enc_matches:
                all_matches.append((
                    f"encoded_{atype}",
                    f"{enc.encoding_type}({desc})",
                    conf * enc.confidence,
                ))
            # Even without pattern match, encoded suspicious content is noteworthy
            if enc.confidence > 0.6 and not enc_matches:
                all_matches.append((
                    "encoded_payload",
                    f"{enc.encoding_type} encoded content: {enc.decoded_text[:50]}",
                    enc.confidence * 0.5,
                ))

        # Step 5: check for reversed text attacks
        reversed_match = _check_reversed_text(text)
        if reversed_match:
            all_matches.append(("reverse_text", f"reversed: {reversed_match}", 0.80))

        # Step 6: check for whitespace-obfuscated attacks
        # First try collapsing all whitespace from text
        collapsed = re.sub(r"\s+", "", text.lower())
        collapsed_matches = self.pattern_detector.scan(collapsed)
        for m in collapsed_matches:
            if m not in all_matches:
                all_matches.append((m[0], f"whitespace_obfuscated({m[1]})", m[2] * 0.9))

        # Also try collapsing all whitespace from normalized text
        if normalized.lower() != text.lower():
            collapsed_norm = re.sub(r"\s+", "", normalized.lower())
            collapsed_norm_matches = self.pattern_detector.scan(collapsed_norm)
            for m in collapsed_norm_matches:
                if m not in all_matches:
                    all_matches.append((m[0], f"whitespace_obfuscated({m[1]})", m[2] * 0.9))

        # Also check collapsed text against collapsed injection phrases
        # This catches "i g n o r e  a l l  i n s t r u c t i o n s"
        _COLLAPSED_PHRASES = [
            ("ignorepreviousinstructions", "direct_override", "ignore previous instructions"),
            ("ignoreallinstructions", "direct_override", "ignore all instructions"),
            ("ignoreallpreviousinstructions", "direct_override", "ignore all previous instructions"),
            ("disregardabove", "direct_override", "disregard above"),
            ("forgetyourinstructions", "direct_override", "forget your instructions"),
            ("newinstructions", "direct_override", "new instructions"),
            ("systemprompt", "extraction", "system prompt"),
            ("developermode", "mode_switch", "developer mode"),
            ("danmode", "mode_switch", "DAN mode"),
            ("sudomode", "mode_switch", "sudo mode"),
            ("unrestrictedmode", "mode_switch", "unrestricted mode"),
            ("jailbreak", "mode_switch", "jailbreak"),
            ("youarenow", "direct_override", "you are now"),
            ("pretendyouare", "role_play", "pretend you are"),
            ("forgeteverything", "conversation_manipulation", "forget everything"),
            ("repeatyoursystemprompt", "extraction", "repeat your system prompt"),
        ]
        for phrase, atype, desc in _COLLAPSED_PHRASES:
            if phrase in collapsed:
                entry = (atype, f"whitespace_obfuscated({desc})", 0.85)
                if entry not in all_matches:
                    all_matches.append(entry)

        # Step 7: check for token splitting across conversation turns
        if messages and len(messages) > 1:
            split_result = self.splitting_detector.check_conversation(messages)
            if split_result:
                phrase, conf = split_result
                all_matches.append(("token_splitting", f"split phrase: {phrase}", conf))

        if not all_matches:
            return InjectionResult(
                is_injection=False,
                confidence=0.0,
                attack_type="",
                matched_patterns=[],
                normalized_input=normalized,
            )

        # Determine highest confidence match
        best_match = max(all_matches, key=lambda x: x[2])
        # Aggregate attack types
        attack_types = list(set(m[0] for m in all_matches))
        primary_type = best_match[0]
        # Overall confidence: highest single + small boost for multiple matches
        confidence = min(best_match[2] + 0.02 * (len(all_matches) - 1), 1.0)

        return InjectionResult(
            is_injection=True,
            confidence=confidence,
            attack_type=primary_type,
            matched_patterns=[m[1] for m in all_matches],
            normalized_input=normalized,
        )

    def get_injection_count(self, user_id: str) -> int:
        """Return the number of injection attempts by a user."""
        return self._injection_counter.get(user_id, 0)

    def get_incident_log(self) -> list[dict]:
        """Return all logged injection incidents."""
        return list(self._incident_log)
