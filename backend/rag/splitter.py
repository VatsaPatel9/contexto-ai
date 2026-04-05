"""Recursive character text splitter for chunking documents."""

from __future__ import annotations


class RecursiveCharacterTextSplitter:
    """Split text into overlapping chunks using a hierarchy of separators.

    The algorithm tries the first separator; if any resulting piece is still
    longer than *chunk_size* it recurses with the next separator.  Overlap
    from the previous chunk is prepended so that retrieval context is not
    lost at chunk boundaries.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", " ", ""]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def split_text(self, text: str) -> list[str]:
        """Split *text* into a list of chunk strings."""
        raw_chunks = self._split_recursive(text, self.separators)
        return self._merge_with_overlap(raw_chunks)

    def split_documents(
        self,
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> list[dict]:
        """Split multiple texts and return a list of ``{content, metadata}`` dicts.

        If *metadatas* is provided it must be the same length as *texts*; each
        metadata dict is copied onto every chunk produced from the
        corresponding text.
        """
        results: list[dict] = []
        for idx, text in enumerate(texts):
            meta = metadatas[idx] if metadatas else {}
            chunks = self.split_text(text)
            for chunk in chunks:
                results.append({"content": chunk, "metadata": dict(meta)})
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split *text* using the given separator hierarchy."""
        if len(text) <= self.chunk_size:
            return [text] if text else []

        # Pick the best separator (the first one that actually appears)
        separator = ""
        remaining_separators: list[str] = []
        for i, sep in enumerate(separators):
            if sep == "":
                separator = sep
                remaining_separators = []
                break
            if sep in text:
                separator = sep
                remaining_separators = separators[i + 1 :]
                break

        # Split on the chosen separator
        if separator:
            pieces = text.split(separator)
        else:
            # Empty-string separator means character-level split
            pieces = list(text)

        # Greedily merge small pieces back together so each is <= chunk_size
        good_chunks: list[str] = []
        current = ""
        for piece in pieces:
            candidate = (
                piece
                if not current
                else current + separator + piece
            )
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    good_chunks.append(current)
                # If this single piece is still too big, recurse
                if len(piece) > self.chunk_size and remaining_separators:
                    good_chunks.extend(
                        self._split_recursive(piece, remaining_separators)
                    )
                else:
                    current = piece
                    continue
                current = ""
        if current:
            good_chunks.append(current)

        return good_chunks

    def _merge_with_overlap(self, chunks: list[str]) -> list[str]:
        """Prepend overlap from the previous chunk to each subsequent chunk."""
        if not chunks or self.chunk_overlap <= 0:
            return chunks

        merged: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = prev[-self.chunk_overlap :] if len(prev) > self.chunk_overlap else prev
            combined = overlap_text + chunks[i]
            # If adding overlap would exceed chunk_size, trim the overlap
            if len(combined) > self.chunk_size:
                excess = len(combined) - self.chunk_size
                overlap_text = overlap_text[excess:]
                combined = overlap_text + chunks[i]
            merged.append(combined)
        return merged
