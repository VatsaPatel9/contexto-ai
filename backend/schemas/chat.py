"""Pydantic schemas for chat-related API endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    course_id: str = "BIO101"
    user: str = "anonymous"
    response_mode: str = "streaming"
    inputs: dict = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    id: str
    name: str
    course_id: str
    created_at: int
    updated_at: int


class ConversationListResponse(BaseModel):
    data: list[ConversationResponse]
    has_more: bool


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    message_type: Optional[str] = None
    created_at: int
    retriever_resources: Optional[list[dict]] = None
    feedback: Optional[str] = None  # 'like' | 'dislike' | None


class MessageListResponse(BaseModel):
    data: list[MessageResponse]
    has_more: bool


class FeedbackRequest(BaseModel):
    rating: str  # "like" | "dislike"
    user: Optional[str] = None  # Deprecated: user_id now comes from session
