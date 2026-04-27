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
        dataset_id: str | None,
        top_k: int = 5,
        score_threshold: float = 0.5,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search against document segments.

        Returns up to *top_k* results whose similarity score (1 - cosine
        distance) meets the *score_threshold*.  Each result is a dict with
        keys: ``content``, ``metadata``, ``score``, ``document_id``,
        ``page_num``, ``section``.

        Tri-state visibility filter on ``documents.uploader_role``:

        * ``baseline`` (super_admin uploads) — always included
        * ``course`` (admin uploads) — included for every dataset the
          caller is enrolled in (row in ``user_courses``). The retriever
          intentionally does NOT scope to a single "selected course":
          a learner enrolled in multiple courses asks one question and
          should get hits across all of them, plus baseline.
        * ``private`` (user uploads) — included only when uploaded by
          the requesting user, regardless of which dataset they live in.

        ``dataset_id`` is currently unused for filtering — it's kept on
        the signature for callers that haven't migrated yet. A real
        single-dataset scope can be reintroduced via a different param
        if we ever bring back per-course context.
        """
        del dataset_id  # not used in the filter anymore; see docstring.
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
            WHERE ds.embedding IS NOT NULL
              AND d.deleted_at IS NULL
              AND 1 - (ds.embedding <=> :query_embedding) >= :score_threshold
              AND (
                  d.uploader_role = 'baseline'
                  OR (
                      d.uploader_role = 'course'
                      AND ds.dataset_id IN (
                          SELECT dataset_id FROM user_courses WHERE user_id = :user_id
                      )
                  )
                  OR (
                      d.uploader_role = 'private'
                      AND d.uploaded_by = :user_id
                  )
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
