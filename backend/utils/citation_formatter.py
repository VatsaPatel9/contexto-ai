"""Citation formatting engine for the AI Tutor chatbot.

Provides utilities to inject inline citation markers into LLM response text,
generate deep-link URLs to the source viewer, strip citations for analytics,
and deduplicate citation entries.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class SourceChunk(BaseModel):
    """A retrieved chunk returned by the vector store with relevance score."""

    text: str
    doc_title: str
    doc_id: str
    page_num: int
    section: str
    score: float = Field(..., ge=0.0, le=1.0)
    content_type: Optional[str] = None


class Citation(BaseModel):
    """A resolved citation reference."""

    index: int
    doc_title: str
    doc_id: str
    page_num: int
    section: str


class SourceLink(BaseModel):
    """A clickable deep-link into the source viewer."""

    citation_index: int
    url: str
    display_text: str


# ---------------------------------------------------------------------------
# Citation marker pattern used throughout the system
# ---------------------------------------------------------------------------

_CITATION_PATTERN = re.compile(
    r"\[Source:\s*[^\]]+\]"
)


# ---------------------------------------------------------------------------
# CitationFormatter
# ---------------------------------------------------------------------------

class CitationFormatter:
    """Formats, injects, and manages citation markers in response text."""

    def __init__(self, source_base_url: str = "/source") -> None:
        self._source_base_url = source_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format_citations(
        self,
        response_text: str,
        source_chunks: list[SourceChunk],
    ) -> str:
        """Inject inline ``[Source: ...]`` markers into *response_text*.

        Each sentence in *response_text* is checked for overlap with the
        retrieved *source_chunks*.  When a sentence is attributable to one
        or more chunks, a citation marker is appended after that sentence.

        If *source_chunks* is empty, *response_text* is returned unchanged.
        """
        if not source_chunks:
            return response_text

        # Deduplicate chunks by (doc_id, page_num, section)
        seen: set[tuple[str, int, str]] = set()
        unique_chunks: list[SourceChunk] = []
        for chunk in source_chunks:
            key = (chunk.doc_id, chunk.page_num, chunk.section)
            if key not in seen:
                seen.add(key)
                unique_chunks.append(chunk)

        # Sort by score descending so highest-relevance chunks get lowest index
        unique_chunks.sort(key=lambda c: c.score, reverse=True)

        # Build citation index map
        citation_map: dict[tuple[str, int, str], int] = {}
        for idx, chunk in enumerate(unique_chunks, start=1):
            key = (chunk.doc_id, chunk.page_num, chunk.section)
            citation_map[key] = idx

        # Split response into sentences
        sentences = _split_sentences(response_text)
        if not sentences:
            return response_text

        annotated_parts: list[str] = []
        for sentence in sentences:
            best_chunk = self._find_best_matching_chunk(sentence, unique_chunks)
            if best_chunk is not None:
                key = (best_chunk.doc_id, best_chunk.page_num, best_chunk.section)
                marker = _build_marker(best_chunk)
                annotated_parts.append(f"{sentence} {marker}")
            else:
                annotated_parts.append(sentence)

        return " ".join(annotated_parts)

    def generate_source_links(
        self,
        citations: list[Citation],
    ) -> list[SourceLink]:
        """Create clickable deep-link objects for each citation."""
        links: list[SourceLink] = []
        for cit in citations:
            url = (
                f"{self._source_base_url}/{cit.doc_id}"
                f"#page={cit.page_num}&section={_url_encode_section(cit.section)}"
            )
            display = (
                f"[{cit.index}] {cit.doc_title}, "
                f"Section: {cit.section}, p.{cit.page_num}"
            )
            links.append(
                SourceLink(
                    citation_index=cit.index,
                    url=url,
                    display_text=display,
                )
            )
        return links

    def strip_citations(self, text: str) -> str:
        """Remove all ``[Source: ...]`` markers from *text*.

        Useful for producing clean text for analytics / embedding.
        """
        cleaned = _CITATION_PATTERN.sub("", text)
        # Collapse any double-spaces left behind
        cleaned = re.sub(r"  +", " ", cleaned)
        return cleaned.strip()

    def extract_citations(
        self,
        annotated_text: str,
        source_chunks: list[SourceChunk],
    ) -> list[Citation]:
        """Parse citation markers out of *annotated_text* and return Citation objects.

        Deduplicates by (doc_id, page_num, section).
        """
        markers = _CITATION_PATTERN.findall(annotated_text)
        seen: set[tuple[str, int, str]] = set()
        citations: list[Citation] = []
        index = 1

        for marker_text in markers:
            chunk = self._match_marker_to_chunk(marker_text, source_chunks)
            if chunk is None:
                continue
            key = (chunk.doc_id, chunk.page_num, chunk.section)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                Citation(
                    index=index,
                    doc_title=chunk.doc_title,
                    doc_id=chunk.doc_id,
                    page_num=chunk.page_num,
                    section=chunk.section,
                )
            )
            index += 1

        return citations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_best_matching_chunk(
        sentence: str,
        chunks: list[SourceChunk],
    ) -> SourceChunk | None:
        """Return the chunk with the highest word-overlap score for *sentence*.

        Returns ``None`` if no chunk has meaningful overlap.
        """
        sentence_words = set(sentence.lower().split())
        if len(sentence_words) < 3:
            return None

        best: SourceChunk | None = None
        best_overlap = 0.0

        for chunk in chunks:
            chunk_words = set(chunk.text.lower().split())
            if not chunk_words:
                continue
            overlap = len(sentence_words & chunk_words) / len(sentence_words)
            # Weight by retrieval score
            combined = overlap * chunk.score
            if combined > best_overlap and overlap > 0.15:
                best_overlap = combined
                best = chunk

        return best

    @staticmethod
    def _match_marker_to_chunk(
        marker_text: str,
        chunks: list[SourceChunk],
    ) -> SourceChunk | None:
        """Match a ``[Source: title, Section: X, p.Y]`` marker back to a chunk."""
        for chunk in chunks:
            if chunk.doc_title in marker_text:
                return chunk
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _build_marker(chunk: SourceChunk) -> str:
    """Build a human-readable citation marker string."""
    return (
        f"[Source: {chunk.doc_title}, "
        f"Section: {chunk.section}, "
        f"p.{chunk.page_num}]"
    )


def _split_sentences(text: str) -> list[str]:
    """Naively split *text* into sentences.

    Splits on sentence-ending punctuation followed by whitespace.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _url_encode_section(section: str) -> str:
    """Minimal URL encoding for a section name."""
    return section.replace(" ", "%20").replace("#", "%23")
