"""Rate-limit tracking for password-reset email sends.

One row per successful generate-password-reset-token request. The
forgot-password endpoint counts the rows in the last 24h per user and
rejects if >=3 before calling SuperTokens. Only logged against users
that actually exist — enumeration probes for unknown emails don't
increment the counter.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from backend.database import Base


class PasswordResetAttempt(Base):
    __tablename__ = "password_reset_attempts"
    __table_args__ = (
        Index("ix_password_reset_attempts_user_id_created_at", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
