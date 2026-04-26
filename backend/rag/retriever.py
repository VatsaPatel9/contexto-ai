"""High-level retriever that ties embeddings and the vector store together."""

from __future__ import annotations

from backend.rag.embeddings import OpenAIEmbeddings
from backend.rag.vectorstore import PgVectorStore
from backend.utils.citation_formatter import SourceChunk


class Retriever:
    """Embed a user query and retrieve the most relevant source chunks.

    Combines :class:`OpenAIEmbeddings` for query vectorisation with
    :class:`PgVectorStore` for cosine-similarity search, then converts
    raw result dicts into :class:`SourceChunk` objects ready for the
    citation formatter.
    """

    def __init__(
        self,
        embeddings: OpenAIEmbeddings,
        vectorstore: PgVectorStore,
    ) -> None:
        self._embeddings = embeddings
        self._vectorstore = vectorstore

    def retrieve(
        self,
        query: str,
        dataset_id: str | None,
        top_k: int = 5,
        score_threshold: float = 0.5,
        user_id: str | None = None,
    ) -> list[SourceChunk]:
        """Retrieve the top-matching source chunks for *query*.

        Steps:
            1. Embed *query* via the OpenAI embeddings client.
            2. Search pgvector for the nearest neighbours in *dataset_id*.
            3. Convert each raw result dict into a :class:`SourceChunk`.

        When *user_id* is provided, private documents are filtered so only
        the uploader's own documents are included in results.

        Returns an ordered list (highest score first) of at most *top_k*
        :class:`SourceChunk` instances.
        """
        query_embedding = self._embeddings.embed_query(query)

        raw_results = self._vectorstore.search(
            query_embedding=query_embedding,
            dataset_id=dataset_id,
            top_k=top_k,
            score_threshold=score_threshold,
            user_id=user_id,
        )

        chunks: list[SourceChunk] = []
        for result in raw_results:
            metadata = result.get("metadata") or {}
            chunks.append(
                SourceChunk(
                    text=result["content"],
                    doc_title=metadata.get("title", ""),
                    doc_id=result["document_id"],
                    page_num=result["page_num"],
                    section=result["section"],
                    score=result["score"],
                )
            )
        return chunks
