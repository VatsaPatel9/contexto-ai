"""OpenAI embedding wrapper with batching support."""

from __future__ import annotations

import openai


class OpenAIEmbeddings:
    """Synchronous wrapper around the OpenAI embeddings API.

    Uses the synchronous ``openai.OpenAI`` client so it can be called
    safely from background tasks and workers without an async event loop.
    """

    BATCH_SIZE = 100  # max texts per API call (conservative limit)

    def __init__(self, api_key: str, model: str = "text-embedding-ada-002") -> None:
        self.model = model
        self._client = openai.OpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts and return their vectors.

        Texts are sent in batches of up to :pyattr:`BATCH_SIZE` to stay
        within API limits.
        """
        all_embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
            response = self._client.embeddings.create(
                input=batch,
                model=self.model,
            )
            # Response data is ordered by index; sort to be safe
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend([item.embedding for item in sorted_data])
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string and return its vector."""
        response = self._client.embeddings.create(
            input=[text],
            model=self.model,
        )
        return response.data[0].embedding
