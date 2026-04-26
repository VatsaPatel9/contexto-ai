"""Per-user profile for admin-controlled settings and usage tracking."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from backend.database import Base


class UserProfile(Base):
    """Stores display name, upload limits, token usage counters, and token budgets per user."""

    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), unique=True, nullable=False, index=True)

    # Display name (user-settable; defaults to None, falls back to email)
    display_name = Column(String(255), nullable=True, default=None)

    # Upload limits (None = no upload permission granted)
    upload_limit = Column(Integer, nullable=True, default=None)
    upload_count = Column(Integer, nullable=False, default=0)

    # Token usage tracking
    tokens_in = Column(BigInteger, nullable=False, default=0)
    tokens_out = Column(BigInteger, nullable=False, default=0)
    token_limit = Column(BigInteger, nullable=True, default=None)  # None = unlimited

    # Terms-of-Service / Privacy acceptance — recorded at signup. The
    # constant ``CURRENT_TERMS_VERSION`` defines the version string the
    # server will accept; mismatch is treated as not-accepted.
    terms_version = Column(String(64), nullable=True, default=None)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True, default=None)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<UserProfile user_id={self.user_id!r} "
            f"uploads={self.upload_count}/{self.upload_limit} "
            f"tokens_in={self.tokens_in} tokens_out={self.tokens_out}>"
        )


def get_or_create_profile(db: Session, user_id: str) -> UserProfile:
    """Return the UserProfile for *user_id*, creating one if it doesn't exist."""
    profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile
