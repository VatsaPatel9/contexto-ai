"""
User flag state machine for tracking offensive-language violations.

State transitions (3 warnings, 4th = ban):
  clean -> warned         (1st offense — warning 1)
  warned -> warned        (2nd offense — warning 2)
  warned -> restricted    (3rd offense — warning 3, final warning)
  restricted -> suspended (4th offense — AUTO BAN)

  Any moderate/severe offense immediately escalates by one level.
  Admin can ban/unban at any time via admin_override().
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from backend.database import Base


class FlagLevel(str, Enum):
    CLEAN = "clean"
    WARNED = "warned"
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"


class UserFlag(Base):
    __tablename__ = "user_flags"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(128), unique=True, nullable=False, index=True)
    flag_level = Column(String(20), nullable=False, default=FlagLevel.CLEAN.value)
    offense_count_mild = Column(Integer, nullable=False, default=0)
    offense_count_severe = Column(Integer, nullable=False, default=0)
    last_offense_at = Column(DateTime, nullable=True)
    restricted_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UserFlag user_id={self.user_id!r} level={self.flag_level} "
            f"mild={self.offense_count_mild} severe={self.offense_count_severe}>"
        )


@dataclass
class RestrictionInfo:
    is_restricted: bool
    flag_level: str
    rate_limit_per_minute: int
    max_session_messages: int
    restricted_until: Optional[datetime] = None
    reason: str = ""


@dataclass
class OffenseRecord:
    user_id: str
    severity: str
    category: str
    message_hash: str
    new_flag_level: str
    offense_count_mild: int
    offense_count_severe: int


_RESTRICTION_PROFILES = {
    FlagLevel.CLEAN.value: RestrictionInfo(
        is_restricted=False, flag_level="clean",
        rate_limit_per_minute=30, max_session_messages=500,
    ),
    FlagLevel.WARNED.value: RestrictionInfo(
        is_restricted=False, flag_level="warned",
        rate_limit_per_minute=20, max_session_messages=300,
        reason="Previous policy warning on file.",
    ),
    FlagLevel.RESTRICTED.value: RestrictionInfo(
        is_restricted=True, flag_level="restricted",
        rate_limit_per_minute=5, max_session_messages=50,
        reason="Account restricted due to repeated policy violations.",
    ),
    FlagLevel.SUSPENDED.value: RestrictionInfo(
        is_restricted=True, flag_level="suspended",
        rate_limit_per_minute=0, max_session_messages=0,
        reason="Account suspended. Contact your advisor.",
    ),
}


class UserFlagService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _get_or_create(self, user_id: str) -> UserFlag:
        flag = self.session.query(UserFlag).filter_by(user_id=user_id).first()
        if flag is None:
            flag = UserFlag(user_id=user_id, flag_level=FlagLevel.CLEAN.value)
            self.session.add(flag)
            self.session.flush()
        return flag

    @staticmethod
    def _hash_message(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def record_offense(self, user_id: str, severity: str, category: str, message_hash: str) -> OffenseRecord:
        """Record an offense and advance the state machine.

        Progression (3 warnings, 4th = ban):
          clean      → warned     (warning 1)
          warned     → warned     (warning 2 — stays warned)
          warned     → restricted (warning 3 — on 3rd total offense)
          restricted → suspended  (offense 4 — AUTO BAN)

        Moderate/severe offenses skip one level ahead.
        """
        flag = self._get_or_create(user_id)
        now = datetime.now(timezone.utc)
        flag.last_offense_at = now
        flag.updated_at = now

        if severity in ("moderate", "severe"):
            flag.offense_count_severe += 1
        else:
            flag.offense_count_mild += 1

        total_offenses = flag.offense_count_mild + flag.offense_count_severe
        current = flag.flag_level

        if current == FlagLevel.CLEAN.value:
            # 1st offense → warned (warning 1)
            if severity in ("moderate", "severe"):
                # Severe jumps straight to restricted
                flag.flag_level = FlagLevel.RESTRICTED.value
                flag.restricted_until = now + timedelta(hours=24)
            else:
                flag.flag_level = FlagLevel.WARNED.value

        elif current == FlagLevel.WARNED.value:
            if severity in ("moderate", "severe"):
                # Severe while warned → restricted
                flag.flag_level = FlagLevel.RESTRICTED.value
                flag.restricted_until = now + timedelta(hours=24)
            elif total_offenses >= 3:
                # 3rd offense → restricted (warning 3, final warning)
                flag.flag_level = FlagLevel.RESTRICTED.value
                flag.restricted_until = now + timedelta(hours=12)
            # else: stays warned (warning 2)

        elif current == FlagLevel.RESTRICTED.value:
            # 4th offense (or any offense while restricted) → SUSPENDED (BAN)
            flag.flag_level = FlagLevel.SUSPENDED.value
            flag.restricted_until = None

        # Build note line
        note_line = f"[{now.isoformat()}] {severity}/{category} hash={message_hash}"
        if flag.flag_level == FlagLevel.SUSPENDED.value and current != FlagLevel.SUSPENDED.value:
            note_line += " AUTO_BAN"
        flag.notes = (flag.notes or "") + note_line + "\n"
        self.session.commit()

        return OffenseRecord(
            user_id=user_id, severity=severity, category=category,
            message_hash=message_hash, new_flag_level=flag.flag_level,
            offense_count_mild=flag.offense_count_mild,
            offense_count_severe=flag.offense_count_severe,
        )

    def get_flag(self, user_id: str) -> UserFlag:
        return self._get_or_create(user_id)

    def check_restricted(self, user_id: str) -> RestrictionInfo:
        flag = self._get_or_create(user_id)
        profile = _RESTRICTION_PROFILES.get(flag.flag_level, _RESTRICTION_PROFILES[FlagLevel.CLEAN.value])
        return RestrictionInfo(
            is_restricted=profile.is_restricted, flag_level=profile.flag_level,
            rate_limit_per_minute=profile.rate_limit_per_minute,
            max_session_messages=profile.max_session_messages,
            restricted_until=flag.restricted_until, reason=profile.reason,
        )

    def decay_flags(self) -> int:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        count = 0
        flags = self.session.query(UserFlag).filter(
            UserFlag.flag_level != FlagLevel.CLEAN.value,
            UserFlag.flag_level != FlagLevel.SUSPENDED.value,
        ).all()
        for flag in flags:
            last = flag.last_offense_at
            if last is None:
                continue
            last_naive = last.replace(tzinfo=None) if last.tzinfo else last
            cutoff_naive = cutoff.replace(tzinfo=None)
            if last_naive < cutoff_naive:
                if flag.flag_level == FlagLevel.RESTRICTED.value:
                    flag.flag_level = FlagLevel.WARNED.value
                    flag.restricted_until = None
                elif flag.flag_level == FlagLevel.WARNED.value:
                    flag.flag_level = FlagLevel.CLEAN.value
                flag.updated_at = now
                flag.notes = (flag.notes or "") + f"[{now.isoformat()}] auto-decay\n"
                count += 1
        self.session.commit()
        return count

    def admin_override(self, user_id: str, new_level: str, admin_id: str, reason: str) -> UserFlag:
        flag = self._get_or_create(user_id)
        now = datetime.now(timezone.utc)
        old_level = flag.flag_level
        flag.flag_level = new_level
        flag.updated_at = now
        if new_level in (FlagLevel.CLEAN.value, FlagLevel.WARNED.value):
            flag.restricted_until = None
        flag.notes = (
            (flag.notes or "") + f"[{now.isoformat()}] admin_override by={admin_id} "
            f"from={old_level} to={new_level} reason={reason}\n"
        )
        self.session.commit()
        return flag

    def get_flagged_users(self) -> list[UserFlag]:
        return (
            self.session.query(UserFlag)
            .filter(UserFlag.flag_level != FlagLevel.CLEAN.value)
            .order_by(UserFlag.updated_at.desc())
            .all()
        )
