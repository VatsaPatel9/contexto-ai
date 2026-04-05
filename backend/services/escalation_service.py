"""
Escalation service for detecting risk signals and alerting advisors.

Risk types:
  - frustration: student is frustrated with the tutor or material
  - distress: student expresses emotional distress or self-harm language
  - repeated_failure: student has failed the same concept multiple times
  - integrity_concern: student may be trying to cheat
  - offensive_language: flagged by offensive language filter
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RiskType(str, Enum):
    FRUSTRATION = "frustration"
    DISTRESS = "distress"
    REPEATED_FAILURE = "repeated_failure"
    INTEGRITY_CONCERN = "integrity_concern"
    OFFENSIVE_LANGUAGE = "offensive_language"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskSignal:
    """A detected risk signal."""
    risk_type: str
    severity: str
    evidence: str
    message_excerpt: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EscalationRecord:
    """Record of an escalation event."""
    id: str
    user_id: str
    reason: str
    severity: str
    risk_signals: list[RiskSignal]
    created_at: str
    webhook_sent: bool = False
    advisor_alerted: bool = False


CRISIS_RESOURCES = {
    "suicide_prevention": {
        "name": "988 Suicide and Crisis Lifeline",
        "phone": "988",
        "text": "Text HOME to 741741",
        "url": "https://988lifeline.org/",
    },
    "crisis_text_line": {
        "name": "Crisis Text Line",
        "text": "Text HOME to 741741",
        "url": "https://www.crisistextline.org/",
    },
    "campus_counseling": {
        "name": "Campus Counseling Center",
        "note": "Please reach out to your university's counseling services.",
    },
}

# ---------------------------------------------------------------------------
# Pattern libraries for risk detection
# ---------------------------------------------------------------------------

_FRUSTRATION_PATTERNS = [
    re.compile(r"\b(this is (so )?(stupid|dumb|pointless|useless|impossible))\b", re.I),
    re.compile(r"\b(i (hate|can'?t stand) (this|math|school|class|homework))\b", re.I),
    re.compile(r"\b(i('?m| am) (so )?(frustrated|angry|mad|furious|fed up))\b", re.I),
    re.compile(r"\b(what('?s| is) the point)\b", re.I),
    re.compile(r"\b(i give up|i quit|forget it|screw this)\b", re.I),
    re.compile(r"\b(you('?re| are) (useless|no help|terrible|the worst))\b", re.I),
    re.compile(r"\b(nothing (works|makes sense))\b", re.I),
    re.compile(r"\b(i('?ve| have) been (trying|working on) (this )?for hours)\b", re.I),
]

_DISTRESS_PATTERNS = [
    re.compile(r"\b(i want to (die|kill myself|end it( all)?|disappear))\b", re.I),
    re.compile(r"\b(i('?m| am) (going to|gonna) (kill|hurt|harm) (myself|me))\b", re.I),
    re.compile(r"\b(i don'?t want to (be alive|live|exist|be here))\b", re.I),
    re.compile(r"\b(nobody (cares|would (miss|notice)))\b", re.I),
    re.compile(r"\b(i('?m| am) (so )?(hopeless|worthless|broken))\b", re.I),
    re.compile(r"\b(self[- ]?harm|cut(ting)? myself|suicid(e|al))\b", re.I),
    re.compile(r"\b(i can'?t (take|do) (this|it) anymore)\b", re.I),
    re.compile(r"\b(everything is (pointless|meaningless))\b", re.I),
    re.compile(r"\b(the world would be better without me)\b", re.I),
]

_INTEGRITY_PATTERNS = [
    re.compile(r"\b(just (give|tell) me the answer)\b", re.I),
    re.compile(r"\b(do (my|this) (homework|assignment|exam|test|quiz) for me)\b", re.I),
    re.compile(r"\b(write (my|this|the) (essay|paper|code|program) for me)\b", re.I),
    re.compile(r"\b(i need (the|all) (the )?answers)\b", re.I),
    re.compile(r"\b(copy|cheat|plagiari[sz]e)\b", re.I),
    re.compile(r"\b(don'?t (teach|explain|help).*(just|only) (answer|solve))\b", re.I),
    re.compile(r"\b(answer key|solution manual)\b", re.I),
    re.compile(r"\b((bypass|skip|ignore) (the )?(hint|tutoring|learning))\b", re.I),
]

_REPEATED_FAILURE_THRESHOLD = 3  # same topic failed N times in conversation


class EscalationService:
    """Handles risk detection, escalation, and advisor alerts."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        advisor_webhook_url: Optional[str] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.advisor_webhook_url = advisor_webhook_url
        self._escalation_log: list[EscalationRecord] = []

    # ---- risk detection ----

    def detect_risk_signals(
        self,
        message: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> list[RiskSignal]:
        """Scan a message (and optionally conversation history) for risk signals."""
        signals: list[RiskSignal] = []

        # Frustration
        for pat in _FRUSTRATION_PATTERNS:
            m = pat.search(message)
            if m:
                signals.append(RiskSignal(
                    risk_type=RiskType.FRUSTRATION.value,
                    severity=Severity.LOW.value,
                    evidence=m.group(0),
                    message_excerpt=message[:200],
                ))
                break  # one frustration signal per message

        # Distress (always high/critical)
        for pat in _DISTRESS_PATTERNS:
            m = pat.search(message)
            if m:
                signals.append(RiskSignal(
                    risk_type=RiskType.DISTRESS.value,
                    severity=Severity.CRITICAL.value,
                    evidence=m.group(0),
                    message_excerpt=message[:200],
                ))
                break

        # Integrity concern
        for pat in _INTEGRITY_PATTERNS:
            m = pat.search(message)
            if m:
                signals.append(RiskSignal(
                    risk_type=RiskType.INTEGRITY_CONCERN.value,
                    severity=Severity.MEDIUM.value,
                    evidence=m.group(0),
                    message_excerpt=message[:200],
                ))
                break

        # Repeated failure detection (from conversation history)
        if conversation_history:
            failure_count = 0
            for entry in conversation_history:
                content = entry.get("content", "")
                if re.search(r"\b(i (still )?don'?t (get|understand)|wrong again|still wrong|incorrect)\b",
                             content, re.I):
                    failure_count += 1
            if failure_count >= _REPEATED_FAILURE_THRESHOLD:
                signals.append(RiskSignal(
                    risk_type=RiskType.REPEATED_FAILURE.value,
                    severity=Severity.MEDIUM.value,
                    evidence=f"Student expressed confusion/failure {failure_count} times in conversation",
                    message_excerpt=message[:200],
                ))

        return signals

    # ---- escalation ----

    def escalate(
        self,
        user_id: str,
        reason: str,
        severity: str,
        context: Optional[dict] = None,
        risk_signals: Optional[list[RiskSignal]] = None,
    ) -> EscalationRecord:
        """Create an escalation record and optionally send webhook."""
        now = datetime.now(timezone.utc)
        record = EscalationRecord(
            id=hashlib.sha256(f"{user_id}{now.isoformat()}".encode()).hexdigest()[:16],
            user_id=user_id,
            reason=reason,
            severity=severity,
            risk_signals=risk_signals or [],
            created_at=now.isoformat(),
        )

        self._escalation_log.append(record)
        logger.warning(
            "Escalation created: user=%s severity=%s reason=%s",
            user_id, severity, reason,
        )

        # Send webhook if configured
        if self.webhook_url:
            record.webhook_sent = self._send_webhook(self.webhook_url, {
                "event": "escalation",
                "escalation_id": record.id,
                "user_id": user_id,
                "reason": reason,
                "severity": severity,
                "risk_signals": [
                    {"type": s.risk_type, "severity": s.severity, "evidence": s.evidence}
                    for s in record.risk_signals
                ],
                "context": context or {},
                "timestamp": record.created_at,
            })

        return record

    # ---- advisor alert ----

    def send_advisor_alert(
        self,
        user_hash: str,
        risk_type: str,
        severity: str,
        conversation_summary: str,
    ) -> bool:
        """Send an alert to the academic advisor via webhook."""
        payload = {
            "event": "advisor_alert",
            "student_hash": user_hash,
            "risk_type": risk_type,
            "severity": severity,
            "summary": conversation_summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_required": severity in (Severity.HIGH.value, Severity.CRITICAL.value),
        }

        if self.advisor_webhook_url:
            return self._send_webhook(self.advisor_webhook_url, payload)

        # Log locally if no webhook configured
        logger.info("Advisor alert (no webhook): %s", json.dumps(payload))
        return True

    # ---- crisis resources ----

    @staticmethod
    def send_crisis_resources(user_id: str) -> dict:
        """Return crisis hotline information for distress signals.

        This method returns the resources dict; the caller (pipeline filter or
        Open WebUI function) is responsible for displaying it to the user.
        """
        logger.critical(
            "Crisis resources triggered for user=%s — immediate advisor notification recommended",
            user_id,
        )
        return {
            "type": "crisis_resources",
            "message": (
                "It sounds like you might be going through a really tough time. "
                "You are not alone, and there are people who want to help."
            ),
            "resources": CRISIS_RESOURCES,
            "user_id": user_id,
        }

    # ---- internal ----

    @staticmethod
    def _send_webhook(url: str, payload: dict) -> bool:
        """POST JSON to a webhook URL. Returns True on success."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except Exception:
            logger.exception("Webhook delivery failed: %s", url)
            return False

    def get_escalation_log(self) -> list[EscalationRecord]:
        """Return all escalation records (for testing / admin)."""
        return list(self._escalation_log)

    # ---- convenience: full pipeline ----

    def assess_and_escalate(
        self,
        user_id: str,
        message: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> list[RiskSignal]:
        """Detect risks and auto-escalate if needed. Returns signals found."""
        signals = self.detect_risk_signals(message, conversation_history)
        if not signals:
            return []

        max_severity = max(
            signals,
            key=lambda s: [Severity.LOW.value, Severity.MEDIUM.value,
                           Severity.HIGH.value, Severity.CRITICAL.value].index(s.severity),
        )

        self.escalate(
            user_id=user_id,
            reason="; ".join(f"{s.risk_type}: {s.evidence}" for s in signals),
            severity=max_severity.severity,
            risk_signals=signals,
            context={"message_preview": message[:300]},
        )

        # Distress -> crisis resources
        if any(s.risk_type == RiskType.DISTRESS.value for s in signals):
            self.send_crisis_resources(user_id)

        # High/critical -> advisor alert
        if max_severity.severity in (Severity.HIGH.value, Severity.CRITICAL.value):
            user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:12]
            self.send_advisor_alert(
                user_hash=user_hash,
                risk_type=max_severity.risk_type,
                severity=max_severity.severity,
                conversation_summary=message[:500],
            )

        return signals
