"""Scheduled cleanup jobs.

Hard-deletes documents that were soft-deleted more than 30 days ago.
Intended to run daily at midnight via the background scheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.dataset import Document, DocumentSegment
from backend.services.storage import delete_document as r2_delete_document

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


def hard_delete_expired_documents(db: Session) -> int:
    """Permanently remove documents soft-deleted more than 30 days ago.

    Deletes the document rows and their segments (via cascade).
    Returns the number of documents hard-deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    expired = (
        db.query(Document)
        .filter(
            Document.deleted_at.isnot(None),
            Document.deleted_at < cutoff,
        )
        .all()
    )

    if not expired:
        logger.info("Cleanup: no expired documents to hard-delete")
        return 0

    settings = Settings()
    count = 0
    for doc in expired:
        doc_id = str(doc.id)
        title = doc.title
        # Remove the original file from R2 before dropping the row.
        if doc.file_path:
            try:
                r2_delete_document(settings, doc.file_path)
            except Exception as exc:
                logger.warning("R2 cleanup failed for doc %s (continuing): %s", doc_id, exc)
        # Segments are cascade-deleted by the ORM relationship
        db.delete(doc)
        count += 1
        logger.info("Cleanup: hard-deleted document %s (%s)", doc_id, title)

    db.commit()
    logger.info("Cleanup: hard-deleted %d expired documents", count)
    return count
