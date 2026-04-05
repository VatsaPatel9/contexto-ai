"""
FERPA Privacy Compliance Service

Provides pseudonymization, de-identification, data retention management,
and student data export/deletion in compliance with FERPA regulations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEMESTER_LENGTH_DAYS: int = 120
GRACE_PERIOD_DAYS: int = 30
DEFAULT_RETENTION_DAYS: int = SEMESTER_LENGTH_DAYS + GRACE_PERIOD_DAYS

# Fields that are considered PII and must be stripped during de-identification
PII_FIELDS = {
    "user_id", "email", "name", "first_name", "last_name",
    "student_id", "phone", "address", "ssn", "ip_address",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class StudentDataExport(BaseModel):
    """Complete data export for a student (FERPA right of access)."""
    user_id: str
    export_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    conversations: list[dict] = Field(default_factory=list)
    feedback: list[dict] = Field(default_factory=list)
    usage_stats: dict = Field(default_factory=dict)


class DeletionResult(BaseModel):
    """Result of a student data deletion request."""
    conversations_deleted: int = 0
    feedback_deleted: int = 0
    flags_cleared: int = 0
    success: bool = False


# ---------------------------------------------------------------------------
# In-memory data store (test / development only)
# ---------------------------------------------------------------------------

@dataclass
class _DataStore:
    """Simple in-memory backing store for the privacy service."""
    # user_id -> list of conversation dicts
    conversations: dict[str, list[dict]] = field(default_factory=dict)
    # user_id -> list of feedback dicts
    feedback: dict[str, list[dict]] = field(default_factory=dict)
    # user_id -> usage stats dict
    usage_stats: dict[str, dict] = field(default_factory=dict)
    # user_id -> list of flag dicts
    flags: dict[str, list[dict]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PrivacyService
# ---------------------------------------------------------------------------

class PrivacyService:
    """
    Central service for FERPA-compliant data handling.

    By default uses an in-memory data store suitable for testing. In
    production, swap the backing store for a real database adapter.
    """

    def __init__(
        self,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        salt: str = "default-tutor-salt",
    ) -> None:
        self.retention_days = retention_days
        self.salt = salt
        self._store = _DataStore()

    # -- Data ingestion helpers (for testing) --------------------------------

    def add_conversation(self, user_id: str, conversation: dict) -> None:
        self._store.conversations.setdefault(user_id, []).append(conversation)

    def add_feedback(self, user_id: str, fb: dict) -> None:
        self._store.feedback.setdefault(user_id, []).append(fb)

    def set_usage_stats(self, user_id: str, stats: dict) -> None:
        self._store.usage_stats[user_id] = stats

    def add_flag(self, user_id: str, flag: dict) -> None:
        self._store.flags.setdefault(user_id, []).append(flag)

    # -- Pseudonymization ---------------------------------------------------

    def pseudonymize_user(self, user_id: str, salt: Optional[str] = None) -> str:
        """
        Return a deterministic, irreversible opaque hash for *user_id*.

        Uses SHA-256 of (user_id + salt). The same inputs always yield
        the same output, but the hash cannot be reversed to recover
        the original user_id.
        """
        effective_salt = salt if salt is not None else self.salt
        raw = f"{user_id}{effective_salt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -- De-identification --------------------------------------------------

    def deidentify_analytics(self, records: list[dict]) -> list[dict]:
        """
        De-identify a list of analytics records:
        - Replace ``user_id`` with a pseudonymized hash.
        - Strip all other PII fields.
        """
        result = []
        for record in records:
            clean: dict[str, Any] = {}
            for key, value in record.items():
                if key == "user_id":
                    clean["user_hash"] = self.pseudonymize_user(str(value))
                elif key not in PII_FIELDS:
                    clean[key] = value
                # PII fields other than user_id are simply dropped
            result.append(clean)
        return result

    def deidentify_conversation(self, conversation: dict) -> dict:
        """
        Remove PII from a single conversation dict for export or logging.
        """
        clean: dict[str, Any] = {}
        for key, value in conversation.items():
            if key == "user_id":
                clean["user_hash"] = self.pseudonymize_user(str(value))
            elif key in PII_FIELDS:
                continue  # strip
            elif key == "messages" and isinstance(value, list):
                # Scrub message-level PII fields but keep content
                clean_messages = []
                for msg in value:
                    clean_msg = {
                        k: v for k, v in msg.items() if k not in PII_FIELDS
                    }
                    clean_messages.append(clean_msg)
                clean["messages"] = clean_messages
            else:
                clean[key] = value
        return clean

    # -- Data retention -----------------------------------------------------

    def check_data_retention(self, conversation_created_at: datetime) -> bool:
        """
        Return True if the conversation is **past** the retention period
        and should be purged.
        """
        now = datetime.now(timezone.utc)
        # Ensure timezone-aware comparison
        if conversation_created_at.tzinfo is None:
            conversation_created_at = conversation_created_at.replace(tzinfo=timezone.utc)
        age = now - conversation_created_at
        return age > timedelta(days=self.retention_days)

    def purge_expired_conversations(self, grace_days: int = 0) -> int:
        """
        Delete conversations that exceed the retention period plus an
        optional *grace_days* buffer. Returns the number of conversations
        deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.retention_days + grace_days
        )
        total_deleted = 0

        for user_id in list(self._store.conversations.keys()):
            convos = self._store.conversations[user_id]
            remaining = []
            for c in convos:
                created = c.get("created_at")
                if created is None:
                    remaining.append(c)
                    continue
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff:
                    total_deleted += 1
                else:
                    remaining.append(c)
            self._store.conversations[user_id] = remaining

        return total_deleted

    # -- Student data export (FERPA right of access) -------------------------

    def export_student_data(self, user_id: str) -> StudentDataExport:
        """
        Export all stored data for a student, fulfilling the FERPA right
        of access. Returns conversations, feedback, and usage statistics.
        """
        return StudentDataExport(
            user_id=user_id,
            conversations=list(self._store.conversations.get(user_id, [])),
            feedback=list(self._store.feedback.get(user_id, [])),
            usage_stats=dict(self._store.usage_stats.get(user_id, {})),
        )

    # -- Student data deletion (FERPA right of deletion) ---------------------

    def delete_student_data(self, user_id: str) -> DeletionResult:
        """
        Delete all stored data for a student, fulfilling the FERPA right
        of deletion. Returns a summary of what was removed.
        """
        convos_deleted = len(self._store.conversations.pop(user_id, []))
        feedback_deleted = len(self._store.feedback.pop(user_id, []))
        flags_cleared = len(self._store.flags.pop(user_id, []))
        self._store.usage_stats.pop(user_id, None)

        return DeletionResult(
            conversations_deleted=convos_deleted,
            feedback_deleted=feedback_deleted,
            flags_cleared=flags_cleared,
            success=True,
        )
