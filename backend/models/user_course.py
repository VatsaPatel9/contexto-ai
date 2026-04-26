"""User-to-course membership (N-to-N enrollments)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.database import Base


class UserCourse(Base):
    """A user is enrolled as a student in a course (Dataset)."""

    __tablename__ = "user_courses"
    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", name="uq_user_courses_user_dataset"),
        Index("ix_user_courses_user_id", "user_id"),
        Index("ix_user_courses_dataset_id", "dataset_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    study_id = Column(String(255), nullable=True)
    enrolled_by = Column(String(255), nullable=True)
    enrolled_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
