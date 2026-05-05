"""Exam, question, and option models for course-level assessments.

Phase 1 only persists the *authoring* surface: the exam itself, its
questions, and the option rows under each question. Per-student attempt
and response models land in Phase 2 alongside the student-facing UI.

Course identity follows the rest of the schema — exams hang off the
``datasets.id`` UUID via ``dataset_id``. The public ``course_id`` slug
on ``Dataset`` is what URLs and the frontend speak; the router resolves
the slug to the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class ExamState(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"        # post-deadline; computed lazily, not stored
    ARCHIVED = "archived"


class QuestionType(str, Enum):
    MCQ = "mcq"
    TRUE_FALSE = "true_false"


class Exam(Base):
    """A course-scoped exam, authored by an admin/super_admin.

    State transitions:
      draft → published (one-way; questions lock at publish)
      published → archived (soft hide; existing attempts kept)
      ``deleted_at`` set => soft-deleted; treated as gone everywhere.

    ``deadline_at`` is always stored UTC. The browser picks the admin's
    local time, converts to UTC for transit/storage; clients render in
    the viewer's local TZ. ``time_limit_minutes`` null => untimed.
    """

    __tablename__ = "exams"
    __table_args__ = (
        Index("ix_exams_dataset_id", "dataset_id"),
        Index("ix_exams_state", "state"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )

    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)

    created_by = Column(String(255), nullable=False)  # SuperTokens user_id of authoring admin
    state = Column(String(20), nullable=False, default=ExamState.DRAFT.value)

    deadline_at = Column(DateTime(timezone=True), nullable=False)
    time_limit_minutes = Column(Integer, nullable=True, default=60)

    published_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    questions = relationship(
        "ExamQuestion",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="ExamQuestion.position",
    )


class ExamQuestion(Base):
    """A single question (MCQ or T/F) belonging to an exam.

    Equal weight across the exam — Phase 1 doesn't expose per-question
    points. ``position`` is the canonical author-defined order; per-student
    shuffle (Phase 2) seeds off the attempt, not this column.
    """

    __tablename__ = "exam_questions"
    __table_args__ = (
        Index("ix_exam_questions_exam_id", "exam_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
    )

    position = Column(Integer, nullable=False, default=0)
    type = Column(String(20), nullable=False)  # ``QuestionType`` value
    text = Column(Text, nullable=False)
    explanation = Column(Text, nullable=True)  # shown post-deadline only

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    exam = relationship("Exam", back_populates="questions")
    options = relationship(
        "ExamQuestionOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="ExamQuestionOption.position",
    )


class ExamQuestionOption(Base):
    """One choice under a question. 4 rows per MCQ, 2 per T/F.

    MCQ supports multi-correct (partial credit); T/F has exactly one
    ``is_correct=True`` row. Validation lives in the router, not the
    schema, so legacy rows from drafts-in-progress aren't rejected.
    """

    __tablename__ = "exam_question_options"
    __table_args__ = (
        Index("ix_exam_question_options_question_id", "question_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exam_questions.id", ondelete="CASCADE"),
        nullable=False,
    )

    position = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)

    question = relationship("ExamQuestion", back_populates="options")


class ExamAttempt(Base):
    """A student's single attempt at an exam.

    There's at most one *active* (un-submitted) attempt per (exam, user).
    Phase 4 will allow admins to grant retakes, which inserts another row
    after the previous one is submitted; the unique constraint covers
    only the active state, so closed attempts can stack up.

    ``due_at`` freezes the effective end time at start: ``min(deadline_at,
    started_at + time_limit_minutes)``. Auto-submission at deadline is
    "lazy" — when any endpoint is touched after ``due_at`` and the attempt
    hasn't been submitted, it is force-graded with whatever responses
    were autosaved.

    ``question_order_seed`` / ``option_order_seed`` make the per-attempt
    shuffle deterministic across page refreshes without storing the full
    permutation.
    """

    __tablename__ = "exam_attempts"
    __table_args__ = (
        Index("ix_exam_attempts_exam_id", "exam_id"),
        Index("ix_exam_attempts_user_id", "user_id"),
        # One active attempt per user per exam — enforced via partial
        # index in PostgreSQL since SQLAlchemy's UniqueConstraint can't
        # express a WHERE clause directly. We create the partial index
        # in init_db() once the table exists.
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String(255), nullable=False)

    started_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=False)

    # Per-attempt shuffle seeds. 31-bit non-negative ints fit Python's
    # ``random.Random`` and JSON without surprises.
    question_order_seed = Column(Integer, nullable=False)
    option_order_seed = Column(Integer, nullable=False)

    # Grading results (set at submit / lazy auto-submit).
    score_pct = Column(Float, nullable=True)            # 0..100
    score_raw = Column(Float, nullable=True)            # sum of partial scores
    total_points = Column(Integer, nullable=True)       # number of questions at submit time

    # Phase 4 hooks — null until an admin overrides.
    manual_override_score = Column(Float, nullable=True)
    override_by = Column(String(255), nullable=True)
    override_reason = Column(Text, nullable=True)
    override_at = Column(DateTime(timezone=True), nullable=True)

    responses = relationship(
        "ExamResponse",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class ExamResponse(Base):
    """A student's answer to one question on one attempt.

    Upserted as the student moves through the exam (auto-save on every
    selection change). At submission, ``is_correct`` and ``partial_score``
    are computed and frozen.

    ``selected_option_ids`` is a Postgres text[] of option-id UUIDs as
    strings — keeping it as strings avoids the JSON-vs-array dance in
    SQLAlchemy and lets us scan the column with ``= ANY`` if we ever need
    to. Length is always ≤ number of options on the question.
    """

    __tablename__ = "exam_responses"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "question_id", name="uq_exam_responses_attempt_question"
        ),
        Index("ix_exam_responses_attempt_id", "attempt_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exam_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exam_questions.id", ondelete="CASCADE"),
        nullable=False,
    )

    selected_option_ids = Column(ARRAY(String), nullable=False, default=list)
    is_correct = Column(Boolean, nullable=True)        # null until graded
    partial_score = Column(Float, nullable=True)       # 0..1, null until graded

    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    attempt = relationship("ExamAttempt", back_populates="responses")


class ExamAttemptGrant(Base):
    """A retake permission issued by an admin to a specific (exam, user).

    Without a grant, a user gets exactly one attempt per exam: once
    submitted, ``start_attempt`` rejects with 409. A grant flips that
    one-shot rule for one new attempt; on consumption, the grant is
    marked closed and ``start_attempt`` is back to its default behaviour
    until another grant is issued.

    Multiple grants per (exam, user) are allowed but unusual — the
    common case is a single grant after a documented technical issue.
    Grants are FIFO-consumed (oldest unconsumed first) so the audit
    trail stays linear.
    """

    __tablename__ = "exam_attempt_grants"
    __table_args__ = (
        Index("ix_exam_attempt_grants_exam_id", "exam_id"),
        Index("ix_exam_attempt_grants_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String(255), nullable=False)

    granted_by = Column(String(255), nullable=False)  # admin user_id
    granted_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason = Column(Text, nullable=True)

    consumed = Column(Boolean, nullable=False, default=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    # ``consumed_by_attempt_id`` is FK-soft (no constraint): we want the
    # audit row to outlive the attempt if the attempt is somehow purged.
    consumed_by_attempt_id = Column(UUID(as_uuid=True), nullable=True)
