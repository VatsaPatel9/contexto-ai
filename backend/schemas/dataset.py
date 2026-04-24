"""Pydantic schemas for dataset / document API endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: str
    title: str
    status: str
    chunk_count: int
    uploaded_by: Optional[str] = None
    visibility: str = "global"
    deleted_at: Optional[str] = None
    download_url: Optional[str] = None  # presigned R2 URL, valid for 1 hour


class DocumentListResponse(BaseModel):
    data: list[DocumentUploadResponse]
