"""Admin endpoints for course (Dataset) creation and N-to-N user enrollment.

A *course* is a row in the ``datasets`` table. Each course has a
``course_id`` (string slug) and a ``created_by`` (admin user_id).
Students are enrolled via the ``user_courses`` table.

Access rules:
* super_admin can manage every course.
* admin can manage only courses they created (``Dataset.created_by``).
* enrollment lookup accepts either the student's email (resolved via
  SuperTokens) or their ``UserProfile.display_name``.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from supertokens_python.recipe.session import SessionContainer

from backend.auth.dependencies import get_user_roles, require_role
from backend.auth.roles import ADMIN, SUPER_ADMIN
from backend.database import get_db
from backend.models.dataset import Dataset
from backend.models.user_course import UserCourse
from backend.models.user_profile import UserProfile

router = APIRouter(prefix="/api/admin/courses", tags=["admin-courses"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CourseCreateRequest(BaseModel):
    course_id: str
    name: str
    description: Optional[str] = None


class CourseUpdateRequest(BaseModel):
    # All fields optional so the client can PATCH-style send only what
    # changed. ``course_id`` itself is intentionally not editable — it's
    # the URL slug used by every existing dataset / enrollment / upload.
    name: Optional[str] = None
    description: Optional[str] = None


class CourseResponse(BaseModel):
    course_id: str
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    member_count: int = 0


class EnrollMemberRequest(BaseModel):
    identifier: str  # email or display_name
    study_id: Optional[str] = None


class CourseMember(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    study_id: Optional[str] = None
    enrolled_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_user_id(identifier: str, db: DBSession) -> Optional[str]:
    """Resolve a user_id, email, or display_name to a SuperTokens user_id.

    Returns None if no user matches.
    """
    identifier = identifier.strip()
    if not identifier:
        return None

    # 1) Direct user_id (the picker sends this when clicking a candidate)
    try:
        from supertokens_python.asyncio import get_user
        user = await get_user(identifier)
        if user is not None:
            return user.id
    except Exception:
        pass

    # 2) By email (SuperTokens)
    if "@" in identifier:
        try:
            from supertokens_python.asyncio import list_users_by_account_info
            from supertokens_python.types.base import AccountInfoInput

            users = await list_users_by_account_info(
                "public", AccountInfoInput(email=identifier.lower())
            )
            for u in users:
                for lm in u.login_methods:
                    if lm.email and lm.email.lower() == identifier.lower():
                        return u.id
        except Exception:
            pass

    # 3) By display_name (case-insensitive exact match)
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.display_name.ilike(identifier))
        .first()
    )
    if profile:
        return profile.user_id

    return None


async def _resolve_member_label(user_id: str, db: DBSession) -> tuple[Optional[str], Optional[str]]:
    """Return (display_name, email) for a user_id."""
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    display_name = profile.display_name if profile else None

    email: Optional[str] = None
    try:
        from supertokens_python.asyncio import get_user
        user = await get_user(user_id)
        if user:
            for lm in user.login_methods:
                if lm.email:
                    email = lm.email
                    break
    except Exception:
        pass
    return display_name, email


def _ensure_owns_course(
    dataset: Dataset, caller_id: str, caller_roles: list[str]
) -> None:
    """Raise 403 if the caller may not manage this course."""
    if SUPER_ADMIN in caller_roles:
        return
    if dataset.created_by and dataset.created_by == caller_id:
        return
    raise HTTPException(
        status_code=403,
        detail="You can only manage courses you created.",
    )


# ---------------------------------------------------------------------------
# Course CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=CourseResponse)
async def create_course(
    body: CourseCreateRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Create a new course. The caller becomes its ``created_by`` owner."""
    course_id = body.course_id.strip()
    name = body.name.strip()
    if not course_id or not name:
        raise HTTPException(status_code=400, detail="course_id and name are required")

    existing = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Course with this course_id already exists")

    user_id = session.get_user_id()
    dataset = Dataset(
        course_id=course_id,
        name=name,
        description=body.description,
        created_by=user_id,
    )
    db.add(dataset)
    db.commit()

    return CourseResponse(
        course_id=dataset.course_id,
        name=dataset.name,
        description=dataset.description,
        created_by=dataset.created_by,
        member_count=0,
    )


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List courses. Super_admin sees all; admin sees only courses they created."""
    user_id = session.get_user_id()
    roles = await get_user_roles(session)

    q = db.query(Dataset)
    if SUPER_ADMIN not in roles:
        q = q.filter(Dataset.created_by == user_id)
    datasets = q.order_by(Dataset.created_at.desc()).all()

    out: list[CourseResponse] = []
    for ds in datasets:
        member_count = (
            db.query(UserCourse).filter(UserCourse.dataset_id == ds.id).count()
        )
        out.append(
            CourseResponse(
                course_id=ds.course_id,
                name=ds.name,
                description=ds.description,
                created_by=ds.created_by,
                member_count=member_count,
            )
        )
    return out


@router.delete("/{course_id}")
async def delete_course(
    course_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Delete a course (and cascade its documents, segments, enrollments)."""
    user_id = session.get_user_id()
    roles = await get_user_roles(session)

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")

    _ensure_owns_course(dataset, user_id, roles)

    db.delete(dataset)
    db.commit()
    return {"result": "success", "course_id": course_id}


@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: str,
    body: CourseUpdateRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Update mutable fields on a course (currently ``name`` and ``description``).

    Authorization mirrors delete: super_admin can edit any course; admin
    can edit only courses they created. ``course_id`` is the URL slug
    and is not mutable here — change it via DB migration if you really
    need to rename the slug.
    """
    user_id = session.get_user_id()
    roles = await get_user_roles(session)

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")

    _ensure_owns_course(dataset, user_id, roles)

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        if len(name) > 512:
            raise HTTPException(status_code=400, detail="Name too long (max 512 chars)")
        dataset.name = name

    if body.description is not None:
        # Empty string clears the description; trim whitespace so blank
        # input doesn't sneak through as a single-space description.
        cleaned = body.description.strip()
        dataset.description = cleaned if cleaned else None

    db.commit()

    member_count = (
        db.query(UserCourse).filter(UserCourse.dataset_id == dataset.id).count()
    )
    return CourseResponse(
        course_id=dataset.course_id,
        name=dataset.name,
        description=dataset.description,
        created_by=dataset.created_by,
        member_count=member_count,
    )


# ---------------------------------------------------------------------------
# Members (enrollments)
# ---------------------------------------------------------------------------

@router.get("/{course_id}/members", response_model=list[CourseMember])
async def list_members(
    course_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List all students enrolled in a course."""
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_owns_course(dataset, caller_id, caller_roles)

    rows = (
        db.query(UserCourse)
        .filter(UserCourse.dataset_id == dataset.id)
        .order_by(UserCourse.enrolled_at.desc())
        .all()
    )

    out: list[CourseMember] = []
    for r in rows:
        display_name, email = await _resolve_member_label(r.user_id, db)
        out.append(
            CourseMember(
                user_id=r.user_id,
                display_name=display_name,
                email=email,
                study_id=r.study_id,
                enrolled_at=r.enrolled_at.isoformat(),
            )
        )
    return out


@router.post("/{course_id}/members", response_model=CourseMember)
async def enroll_member(
    course_id: str,
    body: EnrollMemberRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Enroll a user in a course. ``identifier`` may be an email or display_name."""
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_owns_course(dataset, caller_id, caller_roles)

    target_user_id = await _resolve_user_id(body.identifier, db)
    if not target_user_id:
        raise HTTPException(
            status_code=404,
            detail=f"No user found matching '{body.identifier}'",
        )

    existing = (
        db.query(UserCourse)
        .filter(
            UserCourse.user_id == target_user_id,
            UserCourse.dataset_id == dataset.id,
        )
        .first()
    )
    if existing:
        # Idempotent — update study_id if provided
        if body.study_id is not None:
            existing.study_id = body.study_id
            db.commit()
        enrollment = existing
    else:
        enrollment = UserCourse(
            user_id=target_user_id,
            dataset_id=dataset.id,
            study_id=body.study_id,
            enrolled_by=caller_id,
        )
        db.add(enrollment)
        db.commit()

    display_name, email = await _resolve_member_label(target_user_id, db)
    return CourseMember(
        user_id=target_user_id,
        display_name=display_name,
        email=email,
        study_id=enrollment.study_id,
        enrolled_at=enrollment.enrolled_at.isoformat(),
    )


@router.delete("/{course_id}/members/{user_id}")
async def unenroll_member(
    course_id: str,
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Remove a user from a course."""
    caller_id = session.get_user_id()
    caller_roles = await get_user_roles(session)

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_owns_course(dataset, caller_id, caller_roles)

    deleted = (
        db.query(UserCourse)
        .filter(
            UserCourse.user_id == user_id,
            UserCourse.dataset_id == dataset.id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()

    if deleted == 0:
        raise HTTPException(status_code=404, detail="User is not enrolled in this course")
    return {"result": "success", "course_id": course_id, "user_id": user_id}
