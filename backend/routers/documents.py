"""Document upload, listing, and deletion endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session as DBSession
from supertokens_python.recipe.session import SessionContainer

import logging

from backend.auth.dependencies import get_user_roles, require_auth, require_permission
from backend.auth.roles import ADMIN, SUPER_ADMIN
from backend.config import Settings
from backend.database import get_db
from backend.dependencies import get_embeddings, get_settings, get_vectorstore
from backend.models.dataset import Dataset, Document, DocumentSegment
from backend.models.user_profile import get_or_create_profile
from backend.rag.extractors import extract_pdf_images, extract_text, is_pdf
from backend.rag.splitter import RecursiveCharacterTextSplitter
from backend.rag.vision import VisionProcessor
from backend.schemas.dataset import DocumentListResponse, DocumentUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------
# POST /api/datasets/{course_id}/documents/upload
# ------------------------------------------------------------------

@router.post(
    "/api/datasets/{course_id}/documents/upload",
    response_model=DocumentUploadResponse,
)
async def upload_document(
    course_id: str,
    file: UploadFile = File(...),
    session: SessionContainer = Depends(require_permission("upload_documents")),
    db: DBSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Upload a file, extract text, chunk, embed, and store in the vector DB."""
    user_id = session.get_user_id()
    roles = await get_user_roles(session)

    # Determine visibility based on role
    is_admin = SUPER_ADMIN in roles or ADMIN in roles
    visibility = "global" if is_admin else "private"

    # Enforce upload limit for non-admin users
    if not is_admin:
        profile = get_or_create_profile(db, user_id)
        if profile.upload_limit is None:
            raise HTTPException(status_code=403, detail="No upload permission granted")
        if profile.upload_count >= profile.upload_limit:
            raise HTTPException(
                status_code=403,
                detail=f"Upload limit reached ({profile.upload_count}/{profile.upload_limit}). "
                       "Contact your administrator to increase your limit.",
            )

    # 1. Get or create Dataset for course_id
    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        dataset = Dataset(
            course_id=course_id,
            name=f"Dataset for {course_id}",
        )
        db.add(dataset)
        db.commit()

    # Read file bytes
    file_bytes = await file.read()
    filename = file.filename or "upload.txt"

    # Create the Document record (status = processing)
    doc = Document(
        dataset_id=dataset.id,
        title=filename,
        content_type=file.content_type or "application/octet-stream",
        uploaded_by=user_id,
        visibility=visibility,
        status="processing",
    )
    db.add(doc)
    db.commit()  # commit so FK exists for segments

    try:
        # 2. Extract text
        raw_text = extract_text(file_bytes, filename)

        # 3. Split into chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        chunk_texts = splitter.split_text(raw_text)

        # 3b. Vision: extract and describe images from PDFs
        image_chunks: list[dict] = []  # {"text": str, "page_num": int, "index": int}
        if is_pdf(filename) and settings.enable_vision_extraction:
            try:
                pdf_images = extract_pdf_images(file_bytes)
                if pdf_images:
                    logger.info("Vision: found %d images in %s", len(pdf_images), filename)
                    vision = VisionProcessor(
                        api_key=settings.openai_api_key,
                        model=settings.vision_model,
                    )
                    described = vision.process_images(pdf_images, doc_title=filename)
                    for desc in described:
                        # Prefix so RAG context is clear
                        text = (
                            f"[Image/Diagram from page {desc['page_num']}]\n"
                            f"{desc['description']}"
                        )
                        image_chunks.append({
                            "text": text,
                            "page_num": desc["page_num"],
                            "index": desc["index"],
                        })
                    logger.info("Vision: %d image descriptions added", len(image_chunks))
            except Exception as exc:
                logger.warning("Vision extraction failed (continuing with text only): %s", exc)

        # Combine text chunks + image description chunks
        all_chunk_texts = list(chunk_texts)
        # Track metadata per chunk: None = text chunk, dict = image chunk
        chunk_meta: list[dict | None] = [None] * len(chunk_texts)
        for img_chunk in image_chunks:
            all_chunk_texts.append(img_chunk["text"])
            chunk_meta.append(img_chunk)

        if not all_chunk_texts:
            doc.status = "ready"
            doc.chunk_count = 0
            db.commit()
            return DocumentUploadResponse(
                id=str(doc.id),
                title=doc.title,
                status=doc.status,
                chunk_count=0,
                uploaded_by=user_id,
                visibility=visibility,
            )

        # 4. Embed all chunks (text + image descriptions)
        embeddings_client = get_embeddings(settings)
        vectors = embeddings_client.embed_documents(all_chunk_texts)

        # 5. Create DocumentSegment records
        segments: list[DocumentSegment] = []
        for i, (text, vec) in enumerate(zip(all_chunk_texts, vectors)):
            meta = chunk_meta[i]
            if meta is not None:
                # Image description chunk
                page_num = meta["page_num"]
                section = "[Image/Diagram]"
                metadata_ = {
                    "title": filename,
                    "source_type": "image",
                    "image_index": meta["index"],
                }
            else:
                # Regular text chunk
                page_num = raw_text[:raw_text.find(text) if text in raw_text else 0].count("\f") + 1
                section = ""
                metadata_ = {"title": filename, "source_type": "text"}

            seg = DocumentSegment(
                document_id=doc.id,
                dataset_id=dataset.id,
                content=text,
                position=i,
                page_num=page_num,
                section=section,
                tokens=len(text.split()),
                metadata_=metadata_,
                embedding=vec,
            )
            segments.append(seg)

        # 6. Store via vectorstore
        vectorstore = get_vectorstore()
        vectorstore.upsert_segments(segments)

        # 7. Update Document status
        doc.chunk_count = len(segments)
        doc.status = "ready"

        # 8. Increment upload count for non-admin users
        if not is_admin:
            profile.upload_count += 1

        db.commit()

    except ValueError as exc:
        doc.status = "error"
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        doc.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

    return DocumentUploadResponse(
        id=str(doc.id),
        title=doc.title,
        status=doc.status,
        chunk_count=doc.chunk_count,
        uploaded_by=user_id,
        visibility=visibility,
    )


# ------------------------------------------------------------------
# GET /api/datasets/{course_id}/documents
# ------------------------------------------------------------------

@router.get(
    "/api/datasets/{course_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    course_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """List documents.

    - Admins see ALL docs including soft-deleted (with deleted_at shown).
    - Users see only active (non-deleted) global + own private docs.
    """
    user_id = session.get_user_id()
    roles = await get_user_roles(session)
    is_admin = SUPER_ADMIN in roles or ADMIN in roles

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        return DocumentListResponse(data=[])

    q = db.query(Document).filter(Document.dataset_id == dataset.id)

    if not is_admin:
        # Users: only active docs, global + own private
        q = q.filter(
            Document.deleted_at.is_(None),
            (Document.visibility == "global")
            | ((Document.visibility == "private") & (Document.uploaded_by == user_id)),
        )
    # Admins: see everything (including soft-deleted)

    docs = q.order_by(Document.created_at.desc()).all()

    return DocumentListResponse(
        data=[
            DocumentUploadResponse(
                id=str(d.id),
                title=d.title,
                status=d.status,
                chunk_count=d.chunk_count or 0,
                uploaded_by=d.uploaded_by,
                visibility=d.visibility,
                deleted_at=d.deleted_at.isoformat() if d.deleted_at else None,
            )
            for d in docs
        ]
    )


# ------------------------------------------------------------------
# DELETE /api/datasets/{course_id}/documents/{document_id}
# ------------------------------------------------------------------

@router.delete("/api/datasets/{course_id}/documents/{document_id}")
async def delete_document(
    course_id: str,
    document_id: str,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Soft-delete a document.

    Sets ``deleted_at`` timestamp. The document stays in the DB for 30 days
    but is immediately excluded from RAG retrieval and user document lists.
    Admins can still see soft-deleted docs.
    """
    user_id = session.get_user_id()
    roles = await get_user_roles(session)
    is_admin = SUPER_ADMIN in roles or ADMIN in roles

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document ID")

    dataset = db.query(Dataset).filter(Dataset.course_id == course_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    doc = (
        db.query(Document)
        .filter(Document.id == doc_uuid, Document.dataset_id == dataset.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Document already deleted")

    # Authorization: admins can delete any, users only their own private docs
    if not is_admin:
        if doc.visibility != "private" or doc.uploaded_by != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # Soft delete — set timestamp, RAG query excludes deleted_at IS NOT NULL
    doc.deleted_at = datetime.now(timezone.utc)
    db.commit()

    return {"result": "success", "deleted_at": doc.deleted_at.isoformat()}
