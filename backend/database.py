"""Database engine, session factory, and startup helpers."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from backend.config import Settings

settings = Settings()

_db_url = settings.database_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(_db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create only our 6 tables. Fast — no introspection of existing tables."""
    from backend.models.conversation import Conversation, Message  # noqa: F401
    from backend.models.dataset import Dataset, Document, DocumentSegment  # noqa: F401
    from backend.models.user_flags import UserFlag  # noqa: F401
    from backend.models.user_profile import UserProfile  # noqa: F401

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Only create tables defined on OUR Base — ignores anything else in the DB
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # Ensure new columns exist on pre-existing tables (lightweight migration)
    _add_column_if_missing(engine, "user_profiles", "display_name", "VARCHAR(255)")
    _add_column_if_missing(engine, "documents", "deleted_at", "TIMESTAMPTZ")
    _add_column_if_missing(engine, "datasets", "course_id", "VARCHAR(255)")
    _add_column_if_missing(engine, "messages", "feedback", "VARCHAR(20)")

    # Backfill: copy any feedback that was previously stashed inside
    # messages.retrieval_sources -> 'feedback' -> 'rating' into the new
    # dedicated column. Safe to run every startup (only updates rows
    # that still have the legacy shape and no value in the new column).
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                UPDATE messages
                SET feedback = retrieval_sources->'feedback'->>'rating'
                WHERE feedback IS NULL
                  AND retrieval_sources ? 'feedback'
                  AND retrieval_sources->'feedback'->>'rating' IN ('like', 'dislike')
                """
            )
        )
        conn.commit()


def _add_column_if_missing(eng, table: str, column: str, col_type: str) -> None:
    """Add a column to an existing table if it doesn't already exist."""
    with eng.connect() as conn:
        result = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        if result.fetchone() is None:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            conn.commit()
