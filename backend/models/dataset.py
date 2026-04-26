"""Dataset, Document, and DocumentSegment ORM models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from backend.database import Base


class Dataset(Base):
    """A named collection of documents scoped to a course."""

    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)  # admin user_id who owns this course
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    documents = relationship(
        "Document", back_populates="dataset", cascade="all, delete-orphan"
    )


class Document(Base):
    """A single uploaded document (PDF, DOCX, etc.) belonging to a dataset."""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_path = Column(String(1024), nullable=True)
    uploaded_by = Column(String(255), nullable=True)  # SuperTokens user ID
    visibility = Column(
        String(20), nullable=False, default="global"
    )  # legacy: "global" | "private". Kept for backwards compat; retrieval uses uploader_role.
    uploader_role = Column(
        String(20), nullable=True, default="private"
    )  # "baseline" (super_admin, visible to all) | "course" (admin, visible to enrolled users) | "private" (user, uploader only)
    topics = Column(JSONB, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    chunk_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="processing")  # processing / ready / error
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    deleted_at = Column(
        DateTime(timezone=True), nullable=True, default=None
    )  # None = active, timestamp = soft-deleted (hard-deleted after 30 days)

    dataset = relationship("Dataset", back_populates="documents")
    segments = relationship(
        "DocumentSegment", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentSegment(Base):
    """A single chunk of a document with its vector embedding."""

    __tablename__ = "document_segments"
    __table_args__ = (
        Index("ix_document_segments_dataset_id", "dataset_id"),
        Index("ix_document_segments_document_id", "document_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    page_num = Column(Integer, nullable=False, default=0)
    section = Column(String(512), nullable=False, default="")
    tokens = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSONB, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    document = relationship("Document", back_populates="segments")
