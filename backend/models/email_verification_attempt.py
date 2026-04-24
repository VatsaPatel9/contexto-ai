"""Rate-limit tracking for email-verification resends.

One row per successful generate-verify-token request. The resend
endpoint counts the rows in the last 24h and rejects if >=3 before
calling SuperTokens.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from backend.database import Base


class EmailVerificationAttempt(Base):
    __tablename__ = "email_verification_attempts"
    __table_args__ = (
        Index("ix_email_verification_attempts_user_id_created_at", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
