"""Content pack management service for the AI Tutor chatbot.

Handles validation, ingestion, chunking, embedding, and lifecycle management
of course content packs (syllabi, notes, worked examples, misconception guides,
solution skeletons). All operations are scoped by course_id for strict isolation.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums & value objects
# ---------------------------------------------------------------------------

class ContentType(str, Enum):
    SYLLABUS = "syllabus"
    NOTES = "notes"
    WORKED_EXAMPLE = "worked_example"
    MISCONCEPTION_GUIDE = "misconception_guide"
    SOLUTION_SKELETON = "solution_skeleton"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ContentPackSchema(BaseModel):
    """Validates an incoming content pack descriptor."""

    course_id: str = Field(..., min_length=1)
    content_type: ContentType
    title: str = Field(..., min_length=1)
    topics: list[str] = Field(..., min_length=1)
    difficulty: Optional[str] = None
    approved_by: str = Field(..., min_length=1)
    approved_at: datetime
    file_path: str = Field(..., min_length=1)

    @field_validator("approved_by")
    @classmethod
    def _approved_by_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("approved_by must not be blank")
        return v


class ChunkMetadata(BaseModel):
    course_id: str
    content_type: str
    topic: str
    difficulty: Optional[str] = None
    source_title: str
    page_num: int
    section: str


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata
    embedding: list[float] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    doc_id: str
    course_id: str
    title: str
    content_type: str
    topics: list[str]
    version: int
    created_at: datetime
    chunk_count: int


class VersionInfo(BaseModel):
    doc_id: str
    version: int
    created_at: datetime
    is_active: bool
    previous_version_id: Optional[str] = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    doc_id: str
    version: int
    chunk_count: int
    total_tokens: int
    status: str  # "success" | "error"
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Port interfaces (protocols) for external dependencies
# ---------------------------------------------------------------------------

class VectorStore(Protocol):
    """Abstract interface for a vector database backend."""

    def upsert(self, collection: str, vectors: list[dict[str, Any]]) -> None: ...
    def delete(self, collection: str, filter: dict[str, Any]) -> None: ...
    def query(
        self,
        collection: str,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_docs(self, collection: str, filter: dict[str, Any]) -> list[dict[str, Any]]: ...


class EmbeddingModel(Protocol):
    """Abstract interface for an embedding model."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class TextExtractor(Protocol):
    """Abstract interface for extracting raw text from file bytes."""

    def extract(self, file_bytes: bytes, file_path: str) -> str: ...


# ---------------------------------------------------------------------------
# Chunking utilities
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"^(#{1,6}\s+.+|[A-Z][A-Za-z0-9 ]{2,}:?\s*$)",
    re.MULTILINE,
)

# Rough token estimator: 1 token ~ 4 characters (GPT-style approximation).
_CHARS_PER_TOKEN = 4
_MAX_CHUNK_TOKENS = 512
_OVERLAP_TOKENS = 50


def estimate_tokens(text: str) -> int:
    """Return an approximate token count for *text*."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split *text* into ``(section_heading, section_body)`` pairs.

    A section starts at a Markdown heading (``# ...``) or an ALL-CAPS line.
    Text before the first heading is placed under the ``"Introduction"`` key.
    """
    positions: list[tuple[int, str]] = []
    for m in _SECTION_RE.finditer(text):
        positions.append((m.start(), m.group(0).strip().rstrip(":")))

    if not positions:
        return [("Introduction", text)]

    sections: list[tuple[str, str]] = []
    # Text before first heading
    if positions[0][0] > 0:
        sections.append(("Introduction", text[: positions[0][0]].strip()))

    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[start + len(heading) : end].strip()
        sections.append((heading, body))

    return sections


def chunk_text(
    text: str,
    *,
    max_tokens: int = _MAX_CHUNK_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
) -> list[tuple[str, str]]:
    """Chunk *text* into pieces of at most *max_tokens*, respecting sections.

    Returns a list of ``(section_heading, chunk_text)`` tuples.
    """
    sections = _split_into_sections(text)
    results: list[tuple[str, str]] = []

    for heading, body in sections:
        if not body.strip():
            continue

        # Split body into paragraphs first to respect natural boundaries.
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]

        current_chunk_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = estimate_tokens(para)

            if para_tokens > max_tokens:
                # Flush current chunk
                if current_chunk_parts:
                    results.append((heading, "\n\n".join(current_chunk_parts)))
                    current_chunk_parts = []
                    current_tokens = 0

                # Hard-split oversized paragraph by character budget
                char_budget = max_tokens * _CHARS_PER_TOKEN
                overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
                idx = 0
                while idx < len(para):
                    end = idx + char_budget
                    piece = para[idx:end]
                    results.append((heading, piece))
                    idx = end - overlap_chars
                continue

            if current_tokens + para_tokens > max_tokens and current_chunk_parts:
                results.append((heading, "\n\n".join(current_chunk_parts)))
                # Overlap: keep last part if it fits within overlap budget
                overlap_parts: list[str] = []
                overlap_tok = 0
                for p in reversed(current_chunk_parts):
                    pt = estimate_tokens(p)
                    if overlap_tok + pt <= overlap_tokens:
                        overlap_parts.insert(0, p)
                        overlap_tok += pt
                    else:
                        break
                current_chunk_parts = overlap_parts
                current_tokens = overlap_tok

            current_chunk_parts.append(para)
            current_tokens += para_tokens

        if current_chunk_parts:
            results.append((heading, "\n\n".join(current_chunk_parts)))

    return results


# ---------------------------------------------------------------------------
# Page-number heuristic
# ---------------------------------------------------------------------------

_PAGE_BREAK_RE = re.compile(r"\f|---\s*page\s*break\s*---", re.IGNORECASE)


def _detect_page(text: str, chunk_start: int, full_text: str) -> int:
    """Return a 1-based page number for *chunk_start* inside *full_text*."""
    prefix = full_text[:chunk_start]
    return len(_PAGE_BREAK_RE.findall(prefix)) + 1


# ---------------------------------------------------------------------------
# ContentPackService
# ---------------------------------------------------------------------------

class ContentPackService:
    """Manages the full lifecycle of course content packs.

    Parameters
    ----------
    vector_store:
        Backend for storing and querying chunk embeddings.
    embedding_model:
        Model used to produce vector embeddings for text chunks.
    text_extractor:
        Utility that converts raw file bytes into plain text.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_model: EmbeddingModel,
        text_extractor: TextExtractor,
    ) -> None:
        self._store = vector_store
        self._embedder = embedding_model
        self._extractor = text_extractor
        # In-memory document registry (would be a database in production).
        self._documents: dict[str, dict[str, Any]] = {}
        # version_id -> doc record (for historical access)
        self._versions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_pack(self, pack: ContentPackSchema) -> ValidationResult:
        """Validate a content pack descriptor.

        Checks business rules beyond what Pydantic enforces.
        """
        errors: list[str] = []

        if not pack.approved_by or not pack.approved_by.strip():
            errors.append("Content must be approved before ingestion")

        if not pack.topics:
            errors.append("At least one topic is required")

        if pack.content_type in (
            ContentType.WORKED_EXAMPLE,
            ContentType.SOLUTION_SKELETON,
        ) and not pack.difficulty:
            errors.append(
                f"difficulty is required for content_type={pack.content_type.value}"
            )

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_document(
        self,
        pack: ContentPackSchema,
        file_bytes: bytes,
    ) -> IngestResult:
        """Extract, chunk, embed, and store a document.

        If a document with the same *course_id* + *title* already exists,
        a new version is created and the old version is kept for history.
        """
        validation = self.validate_pack(pack)
        if not validation.valid:
            return IngestResult(
                doc_id="",
                version=0,
                chunk_count=0,
                total_tokens=0,
                status="error",
                errors=validation.errors,
            )

        # --- Extract text ------------------------------------------------
        raw_text = self._extractor.extract(file_bytes, pack.file_path)
        if not raw_text or not raw_text.strip():
            return IngestResult(
                doc_id="",
                version=0,
                chunk_count=0,
                total_tokens=0,
                status="error",
                errors=["Extracted text is empty"],
            )

        # --- Determine version -------------------------------------------
        existing_id: str | None = None
        existing_version = 0
        for did, rec in self._documents.items():
            if rec["course_id"] == pack.course_id and rec["title"] == pack.title:
                existing_id = did
                existing_version = rec["version"]
                break

        new_version = existing_version + 1
        doc_id = existing_id or str(uuid.uuid4())

        # Archive old version if upgrading
        if existing_id:
            old_rec = dict(self._documents[existing_id])
            old_version_id = f"{existing_id}__v{existing_version}"
            old_rec["is_active"] = False
            self._versions[old_version_id] = old_rec

            # Remove old chunks from vector store
            self._store.delete(
                collection=pack.course_id,
                filter={"doc_id": existing_id},
            )

        # --- Chunk -------------------------------------------------------
        chunk_tuples = chunk_text(raw_text)
        texts = [ct[1] for ct in chunk_tuples]

        # --- Embed -------------------------------------------------------
        embeddings = self._embedder.embed(texts)

        # --- Build chunk records ----------------------------------------
        total_tokens = 0
        vectors: list[dict[str, Any]] = []
        primary_topic = pack.topics[0] if pack.topics else ""

        for idx, ((section, text), emb) in enumerate(
            zip(chunk_tuples, embeddings)
        ):
            tok = estimate_tokens(text)
            total_tokens += tok
            chunk_id = hashlib.sha256(
                f"{doc_id}:{new_version}:{idx}".encode()
            ).hexdigest()[:16]

            page_num = _detect_page(text, 0, raw_text)
            # Try to locate chunk in full text for page detection
            pos = raw_text.find(text[:80])
            if pos >= 0:
                page_num = _detect_page(text, pos, raw_text)

            meta = ChunkMetadata(
                course_id=pack.course_id,
                content_type=pack.content_type.value,
                topic=primary_topic,
                difficulty=pack.difficulty,
                source_title=pack.title,
                page_num=page_num,
                section=section,
            )
            vectors.append(
                {
                    "id": chunk_id,
                    "vector": emb,
                    "metadata": meta.model_dump(),
                    "text": text,
                    "doc_id": doc_id,
                }
            )

        # --- Store -------------------------------------------------------
        self._store.upsert(collection=pack.course_id, vectors=vectors)

        # --- Register document -------------------------------------------
        doc_record: dict[str, Any] = {
            "doc_id": doc_id,
            "course_id": pack.course_id,
            "title": pack.title,
            "content_type": pack.content_type.value,
            "topics": pack.topics,
            "difficulty": pack.difficulty,
            "version": new_version,
            "created_at": datetime.utcnow().isoformat(),
            "chunk_count": len(vectors),
            "is_active": True,
            "previous_version_id": (
                f"{doc_id}__v{existing_version}" if existing_id else None
            ),
        }
        self._documents[doc_id] = doc_record
        self._versions[f"{doc_id}__v{new_version}"] = dict(doc_record)

        return IngestResult(
            doc_id=doc_id,
            version=new_version,
            chunk_count=len(vectors),
            total_tokens=total_tokens,
            status="success",
        )

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    def remove_document(self, course_id: str, doc_id: str) -> bool:
        """Remove a document and its chunks from the index.

        Returns ``True`` if the document existed and was removed.
        """
        rec = self._documents.get(doc_id)
        if not rec or rec["course_id"] != course_id:
            return False

        self._store.delete(
            collection=course_id,
            filter={"doc_id": doc_id},
        )
        del self._documents[doc_id]
        return True

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_documents(self, course_id: str) -> list[DocumentInfo]:
        """List all active documents for *course_id*."""
        results: list[DocumentInfo] = []
        for rec in self._documents.values():
            if rec["course_id"] == course_id and rec.get("is_active", True):
                results.append(
                    DocumentInfo(
                        doc_id=rec["doc_id"],
                        course_id=rec["course_id"],
                        title=rec["title"],
                        content_type=rec["content_type"],
                        topics=rec["topics"],
                        version=rec["version"],
                        created_at=datetime.fromisoformat(rec["created_at"]),
                        chunk_count=rec["chunk_count"],
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def get_document_version(self, doc_id: str, version: int | None = None) -> VersionInfo | None:
        """Return version metadata for *doc_id*.

        If *version* is ``None``, returns the latest active version.
        """
        if version is not None:
            key = f"{doc_id}__v{version}"
            rec = self._versions.get(key)
            if not rec:
                return None
            return VersionInfo(
                doc_id=rec["doc_id"],
                version=rec["version"],
                created_at=datetime.fromisoformat(rec["created_at"]),
                is_active=rec.get("is_active", True),
                previous_version_id=rec.get("previous_version_id"),
            )

        rec = self._documents.get(doc_id)
        if not rec:
            return None
        return VersionInfo(
            doc_id=rec["doc_id"],
            version=rec["version"],
            created_at=datetime.fromisoformat(rec["created_at"]),
            is_active=rec.get("is_active", True),
            previous_version_id=rec.get("previous_version_id"),
        )
