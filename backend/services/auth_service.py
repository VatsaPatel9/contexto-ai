"""
Authentication and Role-Based Access Control (RBAC) Service (LEGACY)

.. deprecated::
    This in-memory auth service is superseded by the SuperTokens integration
    in ``backend.auth``. It is retained for existing tests and as a reference
    for the FERPA-compliant permission matrix. New code should use
    ``backend.auth.dependencies`` for route protection and
    ``backend.auth.roles`` for role/permission definitions.

Provides role resolution, course enrollment checks, and a permission matrix
tailored for the AI Tutor chatbot. Designed to enforce FERPA-compliant
access boundaries between students, instructors, advisors, and admins.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TutorRole(str, Enum):
    student = "student"
    instructor = "instructor"
    advisor = "advisor"
    admin = "admin"


class CourseEnrollment(BaseModel):
    user_id: str
    course_id: str
    role: TutorRole
    enrolled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class APIKeyRecord(BaseModel):
    key: str
    user_id: str
    course_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Session(BaseModel):
    user_id: str
    created_at: float = Field(default_factory=time.time)
    last_active: float = Field(default_factory=time.time)
    timeout_seconds: int = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------

PERMISSION_MATRIX: dict[TutorRole, set[str]] = {
    TutorRole.student: {
        "chat",
        "view_own_history",
        "give_feedback",
        "export_own_data",
    },
    TutorRole.instructor: {
        "chat",
        "view_own_history",
        "give_feedback",
        "export_own_data",
        "upload_content",
        "view_course_analytics",
        "manage_course_content",
    },
    TutorRole.advisor: {
        "chat",
        "view_own_history",
        "give_feedback",
        "export_own_data",
        "view_student_engagement",
        "receive_escalations",
    },
    TutorRole.admin: {
        "chat",
        "view_own_history",
        "give_feedback",
        "export_own_data",
        "upload_content",
        "view_course_analytics",
        "manage_course_content",
        "view_student_engagement",
        "receive_escalations",
        "user_management",
        "flag_management",
        "all",
    },
}


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------

class AuthService:
    """
    In-memory auth service for the AI Tutor chatbot.

    In production this would be backed by a database; here we use dicts
    so the service is fully testable without infrastructure.
    """

    def __init__(self) -> None:
        # user_id -> TutorRole (primary role)
        self._user_roles: dict[str, TutorRole] = {}
        # user_id -> list of CourseEnrollment
        self._enrollments: dict[str, list[CourseEnrollment]] = {}
        # advisor_id -> list of assigned student user_ids
        self._advisor_caseloads: dict[str, list[str]] = {}
        # student_id -> set of advisor_ids that have consent to view identity
        self._identity_consent: dict[str, set[str]] = {}
        # api_key -> APIKeyRecord
        self._api_keys: dict[str, APIKeyRecord] = {}
        # user_id -> Session
        self._sessions: dict[str, Session] = {}

    # -- Registration helpers ------------------------------------------------

    def register_user(self, user_id: str, role: TutorRole) -> None:
        self._user_roles[user_id] = role

    def enroll(self, user_id: str, course_id: str, role: TutorRole) -> CourseEnrollment:
        enrollment = CourseEnrollment(user_id=user_id, course_id=course_id, role=role)
        self._enrollments.setdefault(user_id, []).append(enrollment)
        return enrollment

    def assign_advisor(self, advisor_id: str, student_ids: list[str]) -> None:
        self._advisor_caseloads[advisor_id] = student_ids

    def grant_identity_consent(self, student_id: str, advisor_id: str) -> None:
        self._identity_consent.setdefault(student_id, set()).add(advisor_id)

    def register_api_key(self, key: str, user_id: str, course_id: Optional[str] = None) -> APIKeyRecord:
        record = APIKeyRecord(key=key, user_id=user_id, course_id=course_id)
        self._api_keys[key] = record
        return record

    def create_session(self, user_id: str, timeout_seconds: int = 1800) -> Session:
        session = Session(user_id=user_id, timeout_seconds=timeout_seconds)
        self._sessions[user_id] = session
        return session

    def touch_session(self, user_id: str) -> None:
        if user_id in self._sessions:
            self._sessions[user_id].last_active = time.time()

    # -- Query methods -------------------------------------------------------

    def get_user_role(self, user_id: str) -> TutorRole:
        """Return the primary role for *user_id*."""
        if user_id not in self._user_roles:
            raise ValueError(f"Unknown user: {user_id}")
        return self._user_roles[user_id]

    def get_user_courses(self, user_id: str) -> list[CourseEnrollment]:
        """Return all course enrollments for *user_id*."""
        return list(self._enrollments.get(user_id, []))

    def check_course_access(self, user_id: str, course_id: str) -> bool:
        """Return True if *user_id* is enrolled in *course_id*."""
        # Admins have access to all courses
        if self._user_roles.get(user_id) == TutorRole.admin:
            return True
        return any(
            e.course_id == course_id
            for e in self._enrollments.get(user_id, [])
        )

    def check_permission(self, user_id: str, permission: str) -> bool:
        """Return True if *user_id* has the given *permission*."""
        role = self.get_user_role(user_id)
        allowed = PERMISSION_MATRIX.get(role, set())
        return permission in allowed or "all" in allowed

    def get_advisor_caseload(self, advisor_id: str) -> list[str]:
        """Return student user_ids assigned to *advisor_id*."""
        return list(self._advisor_caseloads.get(advisor_id, []))

    def can_view_student_identity(self, viewer_id: str, student_id: str) -> bool:
        """
        Return True only if *viewer_id* is an advisor assigned to
        *student_id* AND the student has given consent.
        """
        # Admins can always view
        if self._user_roles.get(viewer_id) == TutorRole.admin:
            return True

        role = self._user_roles.get(viewer_id)
        if role != TutorRole.advisor:
            return False

        # Must be in caseload
        caseload = self._advisor_caseloads.get(viewer_id, [])
        if student_id not in caseload:
            return False

        # Must have consent
        consented_advisors = self._identity_consent.get(student_id, set())
        return viewer_id in consented_advisors

    def validate_api_key(self, key: str, course_id: Optional[str] = None) -> bool:
        """
        Validate an API key. If the key is scoped to a course, the
        requested *course_id* must match.
        """
        record = self._api_keys.get(key)
        if record is None:
            return False
        if record.course_id is not None and course_id is not None:
            return record.course_id == course_id
        return True

    def is_session_valid(self, user_id: str) -> bool:
        """Return True if the user's session has not timed out."""
        session = self._sessions.get(user_id)
        if session is None:
            return False
        elapsed = time.time() - session.last_active
        return elapsed < session.timeout_seconds

    def require_permission(self, user_id: str, permission: str) -> None:
        """Raise PermissionError if *user_id* lacks *permission*."""
        if not self.check_permission(user_id, permission):
            role = self.get_user_role(user_id)
            raise PermissionError(
                f"User {user_id} with role {role.value} lacks permission '{permission}'"
            )
