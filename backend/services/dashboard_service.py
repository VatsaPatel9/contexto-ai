"""
Dashboard aggregation service for instructors, advisors, and admins.

Composes data from AnalyticsService and FeedbackService into
role-specific dashboard views.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.services.analytics_service import (
    AnalyticsService,
    EventType,
    InteractionEvent,
)
from backend.services.feedback_service import AggregateFeedback, FeedbackService


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class StudentEngagement(BaseModel):
    user_hash: str
    total_sessions: int
    last_active: datetime
    engagement_level: str  # high / medium / low / inactive


class InstructorDashboard(BaseModel):
    topic_heatmap: dict[str, int]
    pattern_breakdown: dict[str, float]
    escalation_rate: float
    total_sessions: int
    total_messages: int
    avg_session_duration: float
    feedback_summary: AggregateFeedback
    top_misconceptions: list[str] = Field(default_factory=list)


class AdvisorDashboard(BaseModel):
    student_count: int
    engagement_summary: list[StudentEngagement]
    escalation_count: int
    at_risk_students: list[str]


class AdminDashboard(BaseModel):
    total_users: int
    total_sessions: int
    flagged_users: int
    injection_attempts: int
    offensive_incidents: int
    system_health: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class DashboardService:
    def __init__(
        self,
        analytics: AnalyticsService,
        feedback: FeedbackService,
    ) -> None:
        self._analytics = analytics
        self._feedback = feedback

    # -- helpers ------------------------------------------------------------

    def _filter_events(
        self,
        date_range: tuple[datetime, datetime],
        course_id: Optional[str] = None,
    ) -> list[InteractionEvent]:
        start, end = date_range
        return [
            e for e in self._analytics.get_events()
            if start <= e.timestamp <= end
            and (course_id is None or e.course_id == course_id)
        ]

    @staticmethod
    def _classify_engagement(total_sessions: int, last_active: datetime, now: datetime) -> str:
        days_since = (now - last_active).days
        if days_since > 14:
            return "inactive"
        if total_sessions >= 10:
            return "high"
        if total_sessions >= 4:
            return "medium"
        return "low"

    # -- instructor ---------------------------------------------------------

    def get_instructor_dashboard(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> InstructorDashboard:
        events = self._filter_events(date_range, course_id)

        # Sessions
        sessions: dict[str, list[InteractionEvent]] = {}
        for ev in events:
            sessions.setdefault(ev.session_id, []).append(ev)
        total_sessions = len(sessions)

        # Messages
        msg_types = {EventType.message_sent, EventType.message_received}
        total_messages = sum(1 for e in events if e.event_type in msg_types)

        # Avg session duration
        durations: list[float] = []
        for evts in sessions.values():
            starts = [e for e in evts if e.event_type == EventType.session_start]
            ends = [e for e in evts if e.event_type == EventType.session_end]
            if starts and ends:
                dur = (ends[-1].timestamp - starts[0].timestamp).total_seconds() / 60.0
                durations.append(dur)
        avg_dur = round(sum(durations) / len(durations), 2) if durations else 0.0

        # Topic heatmap
        topic_heatmap = self._analytics.get_topic_distribution(course_id, date_range)

        # Pattern breakdown
        pattern_breakdown = self._analytics.get_pattern_breakdown(course_id, date_range)

        # Escalation rate
        escalation_rate = self._analytics.get_escalation_rate(course_id, date_range)

        # Feedback
        feedback_summary = self._feedback.get_aggregate_feedback(course_id, date_range)

        # Top misconceptions: topics with highest escalation counts
        topic_escalations: dict[str, int] = {}
        for ev in events:
            if ev.event_type == EventType.escalation_triggered and ev.topic:
                topic_escalations[ev.topic] = topic_escalations.get(ev.topic, 0) + 1
        top_misconceptions = sorted(topic_escalations, key=topic_escalations.get, reverse=True)[:5]  # type: ignore[arg-type]

        return InstructorDashboard(
            topic_heatmap=topic_heatmap,
            pattern_breakdown=pattern_breakdown,
            escalation_rate=escalation_rate,
            total_sessions=total_sessions,
            total_messages=total_messages,
            avg_session_duration=avg_dur,
            feedback_summary=feedback_summary,
            top_misconceptions=top_misconceptions,
        )

    # -- advisor ------------------------------------------------------------

    def get_advisor_dashboard(
        self, advisor_id: str, date_range: tuple[datetime, datetime]
    ) -> AdvisorDashboard:
        """
        Build advisor dashboard.  Since there is no advisor->student mapping
        in-memory, we derive it from events whose metadata contains
        ``advisor_id``.  If no such metadata exists, all users are included.
        """
        all_events = self._filter_events(date_range)

        # Determine relevant user hashes
        advisor_events = [
            e for e in all_events
            if e.metadata.get("advisor_id") == advisor_id
        ]
        if advisor_events:
            relevant = advisor_events
        else:
            relevant = all_events

        users: dict[str, list[InteractionEvent]] = {}
        for ev in relevant:
            users.setdefault(ev.user_hash, []).append(ev)

        _, now = date_range
        engagement_summary: list[StudentEngagement] = []
        at_risk: list[str] = []
        escalation_count = 0

        for uhash, evts in users.items():
            sess_ids = {e.session_id for e in evts}
            last_ts = max(e.timestamp for e in evts)
            level = self._classify_engagement(len(sess_ids), last_ts, now)
            engagement_summary.append(StudentEngagement(
                user_hash=uhash,
                total_sessions=len(sess_ids),
                last_active=last_ts,
                engagement_level=level,
            ))
            if level in ("low", "inactive"):
                at_risk.append(uhash)
            escalation_count += sum(
                1 for e in evts if e.event_type == EventType.escalation_triggered
            )

        return AdvisorDashboard(
            student_count=len(users),
            engagement_summary=engagement_summary,
            escalation_count=escalation_count,
            at_risk_students=at_risk,
        )

    # -- admin --------------------------------------------------------------

    def get_admin_dashboard(
        self, date_range: tuple[datetime, datetime]
    ) -> AdminDashboard:
        events = self._filter_events(date_range)

        user_hashes = {e.user_hash for e in events}
        session_ids = {e.session_id for e in events}
        injection_attempts = sum(
            1 for e in events if e.event_type == EventType.injection_blocked
        )
        offensive_incidents = sum(
            1 for e in events if e.event_type == EventType.offensive_blocked
        )

        # Flagged users: those with any injection or offensive event
        flagged = {
            e.user_hash for e in events
            if e.event_type in (EventType.injection_blocked, EventType.offensive_blocked)
        }

        return AdminDashboard(
            total_users=len(user_hashes),
            total_sessions=len(session_ids),
            flagged_users=len(flagged),
            injection_attempts=injection_attempts,
            offensive_incidents=offensive_incidents,
            system_health={"status": "ok", "event_count": len(events)},
        )
