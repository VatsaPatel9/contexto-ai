"""Parameters endpoint returning UI configuration for the tutor frontend."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.config import Settings
from backend.dependencies import get_settings

router = APIRouter()


@router.get("/api/parameters")
def get_parameters(settings: Settings = Depends(get_settings)):
    """Return the tutor greeting, suggested starter questions, and course name."""
    course = settings.course_name
    return {
        "opening_statement": (
            f"Hi there! I'm your AI tutor for {course}. "
            "I'm here to help you learn and understand the material. "
            "What topic would you like to explore today?"
        ),
        "suggested_questions": [
            f"What are the main topics covered in {course}?",
            "Can you explain the key concepts from the last lecture?",
            "I'm working on a homework problem and need some guidance.",
        ],
        "course_name": course,
    }
