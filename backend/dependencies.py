"""FastAPI dependency providers for the AI Tutor backend."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import SessionLocal, get_db  # noqa: F401 — re-export
from backend.llm.client import LLMClient
from backend.rag.embeddings import OpenAIEmbeddings
from backend.rag.vectorstore import PgVectorStore
from backend.rag.retriever import Retriever


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance (reads .env once)."""
    return Settings()


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Create an LLMClient using the provided (or default) settings."""
    if settings is None:
        settings = get_settings()
    return LLMClient(api_key=settings.openai_api_key, model=settings.llm_model)


def get_embeddings(settings: Settings | None = None) -> OpenAIEmbeddings:
    """Create an OpenAIEmbeddings instance."""
    if settings is None:
        settings = get_settings()
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
    )


def get_vectorstore() -> PgVectorStore:
    """Create a PgVectorStore backed by the default session factory."""
    return PgVectorStore(session_factory=SessionLocal)


def get_retriever(
    embeddings: OpenAIEmbeddings | None = None,
    vectorstore: PgVectorStore | None = None,
) -> Retriever:
    """Create a Retriever wiring embeddings to the vector store."""
    if embeddings is None:
        embeddings = get_embeddings()
    if vectorstore is None:
        vectorstore = get_vectorstore()
    return Retriever(embeddings=embeddings, vectorstore=vectorstore)
