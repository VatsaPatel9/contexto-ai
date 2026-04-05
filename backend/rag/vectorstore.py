"""pgvector-backed vector store for document segment retrieval."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session, sessionmaker

from backend.models.dataset import DocumentSegment


class PgVectorStore:
    """Thin abstraction over pgvector for upserting and searching embeddings.

    Uses raw SQL for the cosine-distance search because SQLAlchemy's ORM
    does not natively support the ``<=>`` operator.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_segments(self, segments: list[DocumentSegment]) -> None:
        """Bulk-insert document segments that already have embeddings set.

        Segments are added via the ORM and flushed in a single transaction.
        """
        session: Session = self._session_factory()
        try:
            session.add_all(segments)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def search(
        self,
        query_embedding: list[float],
        dataset_id: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search against document segments.

        Returns up to *top_k* results whose similarity score (1 - cosine
        distance) meets the *score_threshold*.  Each result is a dict with
        keys: ``content``, ``metadata``, ``score``, ``document_id``,
        ``page_num``, ``section``.

        When *user_id* is provided, results are filtered by document
        visibility: global documents are always included, while private
        documents are only included if uploaded by the requesting user.
        """
        query_sql = sa_text("""
            SELECT
                ds.id,
                ds.content,
                ds.metadata,
                ds.document_id,
                ds.page_num,
                ds.section,
                1 - (ds.embedding <=> :query_embedding) AS score
            FROM document_segments ds
            JOIN documents d ON d.id = ds.document_id
            WHERE ds.dataset_id = :dataset_id
              AND ds.embedding IS NOT NULL
              AND d.deleted_at IS NULL
              AND 1 - (ds.embedding <=> :query_embedding) >= :score_threshold
              AND (
                  d.visibility = 'global'
                  OR (d.visibility = 'private' AND d.uploaded_by = :user_id)
              )
            ORDER BY ds.embedding <=> :query_embedding
            LIMIT :top_k
        """)

        session: Session = self._session_factory()
        try:
            # pgvector expects the embedding as a string representation of a list
            embedding_str = str(query_embedding)
            rows = session.execute(
                query_sql,
                {
                    "query_embedding": embedding_str,
                    "dataset_id": str(dataset_id),
                    "score_threshold": score_threshold,
                    "top_k": top_k,
                    "user_id": user_id or "",
                },
            ).fetchall()

            results: list[dict[str, Any]] = []
            for row in rows:
                results.append(
                    {
                        "content": row.content,
                        "metadata": row.metadata or {},
                        "score": float(row.score),
                        "document_id": str(row.document_id),
                        "page_num": row.page_num,
                        "section": row.section,
                    }
                )
            return results
        finally:
            session.close()

    def delete_by_document(self, document_id: str) -> int:
        """Delete all segments belonging to a document. Returns the count deleted."""
        session: Session = self._session_factory()
        try:
            count = (
                session.query(DocumentSegment)
                .filter(DocumentSegment.document_id == document_id)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
