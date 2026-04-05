"""
Analytics and interaction logging service for the AI Tutor chatbot.

Provides event logging, pattern detection, engagement statistics,
and CSV export with de-identified data (no PII).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    message_sent = "message_sent"
    message_received = "message_received"
    hint_given = "hint_given"
    attempt_detected = "attempt_detected"
    ask_without_attempt = "ask_without_attempt"
    escalation_triggered = "escalation_triggered"
    feedback_given = "feedback_given"
    session_start = "session_start"
    session_end = "session_end"
    offensive_blocked = "offensive_blocked"
    injection_blocked = "injection_blocked"


class PatternType(str, Enum):
    attempt_first_then_ask = "attempt_first_then_ask"
    ask_first = "ask_first"
    hint_progression = "hint_progression"
    direct_conceptual = "direct_conceptual"
    escalated = "escalated"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class InteractionEvent(BaseModel):
    event_type: EventType
    timestamp: datetime
    course_id: str
    user_hash: str
    topic: Optional[str] = None
    hint_level: Optional[int] = None
    pattern_type: Optional[str] = None
    session_id: str
    message_hash: str
    metadata: dict = Field(default_factory=dict)


class EngagementStats(BaseModel):
    total_sessions: int
    avg_session_duration_min: float
    total_messages: int
    unique_topics: int
    avg_messages_per_session: float
    most_active_day: Optional[str] = None


class HintStats(BaseModel):
    avg_hints_per_problem: float
    pct_resolved_at_hint_1: float
    pct_resolved_at_hint_2: float
    pct_resolved_at_hint_3: float
    pct_escalated: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AnalyticsService:
    """In-memory analytics store with pluggable backend support."""

    def __init__(self) -> None:
        self._events: list[InteractionEvent] = []

    # -- core ---------------------------------------------------------------

    def log_event(self, event: InteractionEvent) -> None:
        """Store an interaction event."""
        self._events.append(event)

    def get_events(self) -> list[InteractionEvent]:
        return list(self._events)

    # -- pattern detection --------------------------------------------------

    def detect_pattern(self, conversation_events: list[InteractionEvent]) -> PatternType:
        """Classify the interaction pattern of a conversation event sequence."""
        types = [e.event_type for e in conversation_events]

        # Escalation takes priority
        if EventType.escalation_triggered in types:
            return PatternType.escalated

        # Hint progression: two or more hint_given events present
        hint_events = [e for e in conversation_events if e.event_type == EventType.hint_given]
        if len(hint_events) >= 2:
            return PatternType.hint_progression

        # Attempt first: attempt_detected appears before the first message_sent
        first_msg_idx = None
        first_attempt_idx = None
        for i, t in enumerate(types):
            if t == EventType.message_sent and first_msg_idx is None:
                first_msg_idx = i
            if t == EventType.attempt_detected and first_attempt_idx is None:
                first_attempt_idx = i

        if first_attempt_idx is not None:
            if first_msg_idx is None or first_attempt_idx < first_msg_idx:
                return PatternType.attempt_first_then_ask

        # Ask first: message_sent without prior attempt
        if EventType.message_sent in types:
            return PatternType.ask_first

        return PatternType.direct_conceptual

    # -- topic distribution -------------------------------------------------

    def get_topic_distribution(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> dict[str, int]:
        start, end = date_range
        counts: dict[str, int] = {}
        for ev in self._events:
            if ev.course_id == course_id and start <= ev.timestamp <= end and ev.topic:
                counts[ev.topic] = counts.get(ev.topic, 0) + 1
        return counts

    # -- pattern breakdown --------------------------------------------------

    def get_pattern_breakdown(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> dict[str, float]:
        start, end = date_range
        filtered = [
            e for e in self._events
            if e.course_id == course_id and start <= e.timestamp <= end
        ]
        # Group by session
        sessions: dict[str, list[InteractionEvent]] = {}
        for ev in filtered:
            sessions.setdefault(ev.session_id, []).append(ev)

        if not sessions:
            return {}

        pattern_counts: dict[str, int] = {}
        for sess_events in sessions.values():
            sess_events.sort(key=lambda e: e.timestamp)
            pattern = self.detect_pattern(sess_events)
            pattern_counts[pattern.value] = pattern_counts.get(pattern.value, 0) + 1

        total = sum(pattern_counts.values())
        return {k: v / total for k, v in pattern_counts.items()}

    # -- escalation rate ----------------------------------------------------

    def get_escalation_rate(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> float:
        start, end = date_range
        filtered = [
            e for e in self._events
            if e.course_id == course_id and start <= e.timestamp <= end
        ]
        sessions: dict[str, list[InteractionEvent]] = {}
        for ev in filtered:
            sessions.setdefault(ev.session_id, []).append(ev)

        if not sessions:
            return 0.0

        escalated = sum(
            1 for evts in sessions.values()
            if any(e.event_type == EventType.escalation_triggered for e in evts)
        )
        return escalated / len(sessions)

    # -- engagement stats ---------------------------------------------------

    def get_engagement_stats(
        self, user_hash: str, date_range: tuple[datetime, datetime]
    ) -> EngagementStats:
        start, end = date_range
        filtered = [
            e for e in self._events
            if e.user_hash == user_hash and start <= e.timestamp <= end
        ]

        sessions: dict[str, list[InteractionEvent]] = {}
        for ev in filtered:
            sessions.setdefault(ev.session_id, []).append(ev)

        total_sessions = len(sessions)
        message_events = [
            e for e in filtered
            if e.event_type in (EventType.message_sent, EventType.message_received)
        ]
        total_messages = len(message_events)
        unique_topics = len({e.topic for e in filtered if e.topic})

        # session durations
        durations: list[float] = []
        for evts in sessions.values():
            starts = [e for e in evts if e.event_type == EventType.session_start]
            ends = [e for e in evts if e.event_type == EventType.session_end]
            if starts and ends:
                dur = (ends[-1].timestamp - starts[0].timestamp).total_seconds() / 60.0
                durations.append(dur)

        avg_duration = sum(durations) / len(durations) if durations else 0.0
        avg_msgs = total_messages / total_sessions if total_sessions else 0.0

        # most active day
        day_counts: dict[str, int] = {}
        for ev in filtered:
            day = ev.timestamp.strftime("%A")
            day_counts[day] = day_counts.get(day, 0) + 1
        most_active = max(day_counts, key=day_counts.get) if day_counts else None  # type: ignore[arg-type]

        return EngagementStats(
            total_sessions=total_sessions,
            avg_session_duration_min=round(avg_duration, 2),
            total_messages=total_messages,
            unique_topics=unique_topics,
            avg_messages_per_session=round(avg_msgs, 2),
            most_active_day=most_active,
        )

    # -- hint stats ---------------------------------------------------------

    def get_hint_progression_stats(self, course_id: str) -> HintStats:
        filtered = [e for e in self._events if e.course_id == course_id]

        # Group hint events by session
        sessions: dict[str, list[InteractionEvent]] = {}
        for ev in filtered:
            sessions.setdefault(ev.session_id, []).append(ev)

        total_problems = 0
        total_hints = 0
        resolved_at: dict[int, int] = {1: 0, 2: 0, 3: 0}
        escalated_count = 0

        for evts in sessions.values():
            hints = [e for e in evts if e.event_type == EventType.hint_given]
            if not hints:
                continue
            total_problems += 1
            total_hints += len(hints)
            max_hint = max(h.hint_level or 0 for h in hints)
            has_escalation = any(
                e.event_type == EventType.escalation_triggered for e in evts
            )
            if has_escalation:
                escalated_count += 1
            elif max_hint in resolved_at:
                resolved_at[max_hint] += 1
            # If max_hint > 3, treat as resolved at 3
            elif max_hint > 3:
                resolved_at[3] += 1

        if total_problems == 0:
            return HintStats(
                avg_hints_per_problem=0.0,
                pct_resolved_at_hint_1=0.0,
                pct_resolved_at_hint_2=0.0,
                pct_resolved_at_hint_3=0.0,
                pct_escalated=0.0,
            )

        return HintStats(
            avg_hints_per_problem=round(total_hints / total_problems, 2),
            pct_resolved_at_hint_1=round(resolved_at[1] / total_problems, 4),
            pct_resolved_at_hint_2=round(resolved_at[2] / total_problems, 4),
            pct_resolved_at_hint_3=round(resolved_at[3] / total_problems, 4),
            pct_escalated=round(escalated_count / total_problems, 4),
        )

    # -- CSV export ---------------------------------------------------------

    def export_csv(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> str:
        """Export de-identified CSV. user_hash is kept; no PII fields."""
        start, end = date_range
        filtered = [
            e for e in self._events
            if e.course_id == course_id and start <= e.timestamp <= end
        ]
        filtered.sort(key=lambda e: e.timestamp)

        output = io.StringIO()
        writer = csv.writer(output)
        headers = [
            "event_type", "timestamp", "course_id", "user_hash",
            "topic", "hint_level", "pattern_type", "session_id", "message_hash",
        ]
        writer.writerow(headers)
        for ev in filtered:
            writer.writerow([
                ev.event_type.value,
                ev.timestamp.isoformat(),
                ev.course_id,
                ev.user_hash,
                ev.topic or "",
                ev.hint_level if ev.hint_level is not None else "",
                ev.pattern_type or "",
                ev.session_id,
                ev.message_hash,
            ])
        return output.getvalue()
