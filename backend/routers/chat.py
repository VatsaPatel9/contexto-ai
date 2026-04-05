"""Chat, conversation, and message API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession
from supertokens_python.recipe.session import SessionContainer

from backend.auth.dependencies import require_auth
from backend.config import Settings
from backend.database import get_db, SessionLocal
from backend.dependencies import get_llm_client, get_retriever, get_settings
from backend.models.conversation import Conversation, Message
from backend.pipeline.orchestrator import process_chat_message
from backend.schemas.chat import (
    ChatRequest,
    ConversationListResponse,
    ConversationResponse,
    FeedbackRequest,
    MessageListResponse,
    MessageResponse,
)

router = APIRouter()


def _ts(dt: datetime | None) -> int:
    """Convert a datetime to a unix timestamp integer."""
    if dt is None:
        return 0
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt.tzinfo is None else int(dt.timestamp())


def _verify_conversation_ownership(
    conv: Conversation, user_id: str
) -> None:
    """Raise 403 if the conversation does not belong to the user."""
    if conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ------------------------------------------------------------------
# POST /api/chat-messages
# ------------------------------------------------------------------

@router.post("/api/chat-messages")
async def chat_messages(
    body: ChatRequest,
    session: SessionContainer = Depends(require_auth()),
    settings: Settings = Depends(get_settings),
):
    """Accept a chat message and return an SSE streaming response."""
    user_id = session.get_user_id()

    llm = get_llm_client(settings)

    retriever = None
    if settings.openai_api_key:
        try:
            retriever = get_retriever()
        except Exception:
            retriever = None

    async def event_stream():
        # Create DB session inside the stream so it lives as long as streaming does
        db = SessionLocal()
        try:
            async for event in process_chat_message(
                query=body.query,
                conversation_id=body.conversation_id,
                course_id=body.course_id,
                user_id=user_id,
                db=db,
                retriever=retriever,
                llm=llm,
                settings=settings,
            ):
                yield event
        finally:
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------
# GET /api/conversations
# ------------------------------------------------------------------

@router.get("/api/conversations", response_model=ConversationListResponse)
def list_conversations(
    session: SessionContainer = Depends(require_auth()),
    course_id: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """List conversations for the authenticated user, optionally filtered by course."""
    user_id = session.get_user_id()
    q = db.query(Conversation).filter(Conversation.user_id == user_id)
    if course_id:
        q = q.filter(Conversation.course_id == course_id)
    q = q.order_by(Conversation.updated_at.desc())

    total = q.count()
    conversations = q.limit(limit).all()

    return ConversationListResponse(
        data=[
            ConversationResponse(
                id=str(c.id),
                name=c.name or "",
                course_id=c.course_id,
                created_at=_ts(c.created_at),
                updated_at=_ts(c.updated_at),
            )
            for c in conversations
        ],
        has_more=total > limit,
    )


# ------------------------------------------------------------------
# GET /api/conversations/{conversation_id}
# ------------------------------------------------------------------

@router.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Return a single conversation by ID (ownership verified)."""
    user_id = session.get_user_id()
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _verify_conversation_ownership(conv, user_id)

    return ConversationResponse(
        id=str(conv.id),
        name=conv.name or "",
        course_id=conv.course_id,
        created_at=_ts(conv.created_at),
        updated_at=_ts(conv.updated_at),
    )


# ------------------------------------------------------------------
# DELETE /api/conversations/{conversation_id}
# ------------------------------------------------------------------

@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Delete a conversation and all its messages (ownership verified)."""
    user_id = session.get_user_id()
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _verify_conversation_ownership(conv, user_id)

    db.delete(conv)
    db.commit()
    return {"result": "success"}


# ------------------------------------------------------------------
# GET /api/messages
# ------------------------------------------------------------------

@router.get("/api/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: str = Query(...),
    session: SessionContainer = Depends(require_auth()),
    limit: int = Query(20, ge=1, le=100),
    first_id: str = Query(None),
    db: DBSession = Depends(get_db),
):
    """List messages in a conversation with cursor-based pagination (ownership verified)."""
    user_id = session.get_user_id()
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    # Verify ownership
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _verify_conversation_ownership(conv, user_id)

    q = db.query(Message).filter(Message.conversation_id == conv_uuid)

    # Cursor-based pagination: messages created before the cursor
    if first_id:
        try:
            cursor_uuid = uuid.UUID(first_id)
            cursor_msg = db.query(Message).filter(Message.id == cursor_uuid).first()
            if cursor_msg:
                q = q.filter(Message.created_at < cursor_msg.created_at)
        except ValueError:
            pass

    q = q.order_by(Message.created_at.desc())

    total = q.count()
    messages = q.limit(limit).all()

    # Return in chronological order
    messages.reverse()

    return MessageListResponse(
        data=[
            MessageResponse(
                id=str(m.id),
                role=m.role,
                content=m.content,
                message_type=m.message_type,
                created_at=_ts(m.created_at),
                retriever_resources=m.retrieval_sources,
            )
            for m in messages
        ],
        has_more=total > limit,
    )


# ------------------------------------------------------------------
# POST /api/messages/{message_id}/feedbacks
# ------------------------------------------------------------------

@router.post("/api/messages/{message_id}/feedbacks")
def submit_feedback(
    message_id: str,
    body: FeedbackRequest,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Store a like/dislike rating on a message."""
    user_id = session.get_user_id()
    try:
        msg_uuid = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    msg = db.query(Message).filter(Message.id == msg_uuid).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Store feedback in the retrieval_sources JSONB field under a "feedback" key
    sources = msg.retrieval_sources or {}
    if isinstance(sources, list):
        sources = {"retriever_resources": sources}
    sources["feedback"] = {"rating": body.rating, "user": user_id}
    msg.retrieval_sources = sources
    db.commit()

    return {"result": "success"}
