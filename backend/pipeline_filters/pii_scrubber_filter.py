"""
PII Scrubber Pipeline Filter

Detects and removes Personally Identifiable Information (PII) from student
messages before they are sent to the LLM, and verifies no PII leaks in
bot responses. This is a critical component of FERPA compliance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PIIType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    STUDENT_ID = "STUDENT_ID"
    SSN = "SSN"
    NAME = "NAME"
    ADDRESS = "ADDRESS"


@dataclass
class PIIDetection:
    """Record of a single PII detection event."""
    pii_type: PIIType
    original_length: int
    position: int
    replacement_token: str


@dataclass
class ScrubResult:
    """Result of scrubbing text for PII."""
    scrubbed_text: str
    detections: list[PIIDetection] = field(default_factory=list)

    @property
    def pii_found(self) -> bool:
        return len(self.detections) > 0


class PIIDetector:
    """
    Detects PII in text using regex patterns.

    Each pattern is designed to catch common PII formats while avoiding
    false positives on academic content like math expressions and course codes.
    """

    # Email: standard email pattern
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
    )

    # Phone: US formats — (555) 123-4567, 555-123-4567, 555.123.4567, +1-555-123-4567
    PHONE_PATTERN = re.compile(
        r'(?<!\d)'                          # not preceded by digit
        r'(?:\+1[\s\-.]?)?'                 # optional +1 prefix
        r'(?:\(?\d{3}\)?[\s\-.]?)'          # area code
        r'\d{3}[\s\-.]?'                    # exchange
        r'\d{4}'                            # subscriber
        r'(?!\d)'                           # not followed by digit
    )

    # Student ID: 3 letters followed by 6-8 digits (e.g., ABC123456)
    # or "student ID" / "student id" followed by alphanumeric identifier
    STUDENT_ID_PATTERN = re.compile(
        r'\b[A-Za-z]{3}\d{6,8}\b'
        r'|'
        r'(?i:student\s+(?:id|ID|Id))\s*(?::?\s*)([A-Za-z0-9]{4,12})',
        re.IGNORECASE,
    )

    # SSN: 123-45-6789 or 123 45 6789
    SSN_PATTERN = re.compile(
        r'\b\d{3}[\-\s]\d{2}[\-\s]\d{4}\b'
    )

    # Name: preceded by "my name is" / "I'm" / "I am" / "this is"
    # The prefix is case-insensitive via inline flag; the name capture
    # requires Title Case words to avoid matching regular sentences.
    NAME_PATTERN = re.compile(
        r"(?i:my\s+name\s+is|I'?\s*m|I\s+am|this\s+is)\s+"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
    )

    # Address: house number + street name + street suffix
    _STREET_SUFFIXES = (
        r"St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Dr(?:ive)?|Ln|Lane|"
        r"Rd|Road|Ct|Court|Pl|Place|Way|Cir(?:cle)?|Pkwy|Parkway|"
        r"Ter(?:race)?|Hwy|Highway"
    )
    ADDRESS_PATTERN = re.compile(
        rf'\b\d{{1,6}}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){{0,2}}'
        rf'\s+(?:{_STREET_SUFFIXES})\b\.?',
        re.IGNORECASE,
    )

    # Course code pattern — used to AVOID false positives
    COURSE_CODE_PATTERN = re.compile(
        r'\b[A-Z]{2,5}\s?\d{3,4}[A-Z]?\b'
    )

    def detect_all(self, text: str) -> list[tuple[PIIType, re.Match]]:
        """Return all PII matches found in *text*, sorted by position."""
        matches: list[tuple[PIIType, re.Match]] = []

        for m in self.EMAIL_PATTERN.finditer(text):
            matches.append((PIIType.EMAIL, m))

        for m in self.PHONE_PATTERN.finditer(text):
            matched = m.group()
            # Filter out short numeric runs that are not real phones
            digits = re.sub(r'\D', '', matched)
            if len(digits) < 10:
                continue
            # Reject if this is part of a math expression (preceded by operator)
            pre = text[max(0, m.start() - 3): m.start()]
            if re.search(r'[=+\-*/^]\s*$', pre):
                continue
            matches.append((PIIType.PHONE, m))

        for m in self.SSN_PATTERN.finditer(text):
            # Reject SSN-like sequences inside math context
            pre = text[max(0, m.start() - 3): m.start()]
            if re.search(r'[=+*/^]\s*$', pre):
                continue
            matches.append((PIIType.SSN, m))

        for m in self.STUDENT_ID_PATTERN.finditer(text):
            full_match = m.group()
            # Do not flag things that look like course codes (2-5 letters + 3-4 digits)
            if self.COURSE_CODE_PATTERN.fullmatch(full_match.strip()):
                continue
            matches.append((PIIType.STUDENT_ID, m))

        for m in self.NAME_PATTERN.finditer(text):
            matches.append((PIIType.NAME, m))

        for m in self.ADDRESS_PATTERN.finditer(text):
            # Reject if this overlaps with a course code
            if self.COURSE_CODE_PATTERN.search(m.group()):
                continue
            matches.append((PIIType.ADDRESS, m))

        matches.sort(key=lambda pair: pair[1].start())
        return matches


class PIIScrubber:
    """Replaces detected PII with safe placeholder tokens."""

    REPLACEMENT_MAP = {
        PIIType.EMAIL: "[EMAIL]",
        PIIType.PHONE: "[PHONE]",
        PIIType.STUDENT_ID: "[STUDENT_ID]",
        PIIType.SSN: "[SSN]",
        PIIType.NAME: "[NAME]",
        PIIType.ADDRESS: "[ADDRESS]",
    }

    def __init__(self, detector: Optional[PIIDetector] = None) -> None:
        self.detector = detector or PIIDetector()

    def scrub(self, text: str) -> ScrubResult:
        """
        Scrub all PII from *text* and return the scrubbed version together
        with metadata about what was removed.
        """
        raw_matches = self.detector.detect_all(text)
        if not raw_matches:
            return ScrubResult(scrubbed_text=text, detections=[])

        detections: list[PIIDetection] = []
        # Process replacements from end to start so positions stay valid
        result = text
        for pii_type, match in reversed(raw_matches):
            token = self.REPLACEMENT_MAP[pii_type]

            # For NAME, only replace the captured name group, not the prefix
            if pii_type == PIIType.NAME and match.lastindex and match.lastindex >= 1:
                start = match.start(1)
                end = match.end(1)
                original_length = end - start
            else:
                start = match.start()
                end = match.end()
                original_length = end - start

            detections.append(PIIDetection(
                pii_type=pii_type,
                original_length=original_length,
                position=start,
                replacement_token=token,
            ))
            result = result[:start] + token + result[end:]

        # Reverse detections so they are in document order
        detections.reverse()
        return ScrubResult(scrubbed_text=result, detections=detections)


class PIIScrubberFilter:
    """
    Open WebUI-compatible pipeline filter that scrubs PII on inlet
    (student -> LLM) and verifies no PII leaks on outlet (LLM -> student).
    """

    def __init__(self) -> None:
        self.scrubber = PIIScrubber()
        self.name = "PII Scrubber Filter"
        self.type = "filter"
        # Mapping from conversation_id -> list of detections for audit
        self._audit_log: dict[str, list[PIIDetection]] = {}

    def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        """
        Process incoming user message. Strip PII before it reaches the LLM.

        Args:
            body: The request body containing ``messages``.
            user: Optional user context dict.

        Returns:
            Modified body with PII replaced by tokens.
        """
        messages = body.get("messages", [])
        for message in messages:
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            result = self.scrubber.scrub(content)
            if result.pii_found:
                message["content"] = result.scrubbed_text
                # Audit trail
                conv_id = body.get("conversation_id", "unknown")
                self._audit_log.setdefault(conv_id, []).extend(result.detections)
        return body

    def outlet(self, body: dict, user: Optional[dict] = None) -> dict:
        """
        Process outgoing bot response. Ensure no PII leaked into the
        LLM's reply (defense in depth).

        Args:
            body: The response body containing ``messages``.
            user: Optional user context dict.

        Returns:
            Modified body with any PII replaced by tokens.
        """
        messages = body.get("messages", [])
        for message in messages:
            if message.get("role") != "assistant":
                continue
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            result = self.scrubber.scrub(content)
            if result.pii_found:
                message["content"] = result.scrubbed_text
        return body
