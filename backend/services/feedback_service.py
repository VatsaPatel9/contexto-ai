"""
Feedback collection service for the AI Tutor chatbot.

Collects per-message ratings (clarity, usefulness, trust, learning impact),
thumbs up/down, and free-text comments.  Provides aggregate statistics
and survey-prompt logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FeedbackRating(BaseModel):
    message_id: str
    user_hash: str
    course_id: str
    clarity: int = Field(..., ge=1, le=4)
    usefulness: int = Field(..., ge=1, le=4)
    trust: int = Field(..., ge=1, le=4)
    learning_impact: int = Field(..., ge=1, le=4)
    thumbs: Optional[Literal["up", "down"]] = None
    comment: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    topic: Optional[str] = None

    @field_validator("clarity", "usefulness", "trust", "learning_impact", mode="before")
    @classmethod
    def _check_range(cls, v: int) -> int:
        if not isinstance(v, int) or v < 1 or v > 4:
            raise ValueError("Rating must be an integer between 1 and 4")
        return v


class TopicFeedback(BaseModel):
    count: int
    avg_clarity: float
    avg_usefulness: float


class AggregateFeedback(BaseModel):
    total_ratings: int
    avg_clarity: float
    avg_usefulness: float
    avg_trust: float
    avg_learning_impact: float
    pct_thumbs_up: float
    feedback_by_topic: dict[str, TopicFeedback] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FeedbackService:
    """In-memory feedback store with aggregation helpers."""

    def __init__(self, survey_interval: int = 5) -> None:
        self._store: dict[str, FeedbackRating] = {}  # message_id -> rating
        self._survey_interval = survey_interval

    # -- core ---------------------------------------------------------------

    def submit_feedback(self, rating: FeedbackRating) -> bool:
        """Store feedback for a message. Returns True on success."""
        self._store[rating.message_id] = rating
        return True

    def get_feedback_for_message(self, message_id: str) -> Optional[FeedbackRating]:
        return self._store.get(message_id)

    # -- aggregation --------------------------------------------------------

    def get_aggregate_feedback(
        self, course_id: str, date_range: tuple[datetime, datetime]
    ) -> AggregateFeedback:
        start, end = date_range
        filtered = [
            r for r in self._store.values()
            if r.course_id == course_id and start <= r.timestamp <= end
        ]

        if not filtered:
            return AggregateFeedback(
                total_ratings=0,
                avg_clarity=0.0,
                avg_usefulness=0.0,
                avg_trust=0.0,
                avg_learning_impact=0.0,
                pct_thumbs_up=0.0,
                feedback_by_topic={},
            )

        n = len(filtered)
        avg_c = sum(r.clarity for r in filtered) / n
        avg_u = sum(r.usefulness for r in filtered) / n
        avg_t = sum(r.trust for r in filtered) / n
        avg_l = sum(r.learning_impact for r in filtered) / n

        thumbs_total = [r for r in filtered if r.thumbs is not None]
        thumbs_up = [r for r in thumbs_total if r.thumbs == "up"]
        pct_up = len(thumbs_up) / len(thumbs_total) if thumbs_total else 0.0

        # Per-topic breakdown
        topic_data: dict[str, list[FeedbackRating]] = {}
        for r in filtered:
            topic_key = r.topic or "unknown"
            topic_data.setdefault(topic_key, []).append(r)

        feedback_by_topic: dict[str, TopicFeedback] = {}
        for topic, ratings in topic_data.items():
            tc = len(ratings)
            feedback_by_topic[topic] = TopicFeedback(
                count=tc,
                avg_clarity=round(sum(r.clarity for r in ratings) / tc, 2),
                avg_usefulness=round(sum(r.usefulness for r in ratings) / tc, 2),
            )

        return AggregateFeedback(
            total_ratings=n,
            avg_clarity=round(avg_c, 2),
            avg_usefulness=round(avg_u, 2),
            avg_trust=round(avg_t, 2),
            avg_learning_impact=round(avg_l, 2),
            pct_thumbs_up=round(pct_up, 4),
            feedback_by_topic=feedback_by_topic,
        )

    # -- survey logic -------------------------------------------------------

    def should_show_survey(self, user_hash: str, interaction_count: int) -> bool:
        """Return True every Nth interaction (configurable, default N=5)."""
        return interaction_count > 0 and interaction_count % self._survey_interval == 0

    def get_survey_prompt(self) -> str:
        return "Did this help you learn?"
