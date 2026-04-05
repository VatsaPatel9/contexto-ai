"""Text extraction from uploaded files (PDF, DOCX, TXT, MD)."""

from __future__ import annotations

import io


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from raw file bytes based on the file extension.

    Supported formats:
        - ``.pdf``  -- extracted page-by-page via *pdfplumber*, pages joined with \\f
        - ``.docx`` -- paragraphs extracted via *python-docx*, joined with \\n
        - ``.txt``, ``.md`` -- decoded as UTF-8

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = _get_extension(filename)

    if ext == ".pdf":
        return _extract_pdf(file_bytes)
    elif ext == ".docx":
        return _extract_docx(file_bytes)
    elif ext in (".txt", ".md"):
        return file_bytes.decode("utf-8")
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Accepted: .pdf, .docx, .txt, .md"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_extension(filename: str) -> str:
    """Return the lowercased file extension including the leading dot."""
    dot_index = filename.rfind(".")
    if dot_index == -1:
        return ""
    return filename[dot_index:].lower()


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF using pdfplumber, one page at a time.

    Pages are separated by a form-feed character (\\f) so downstream
    code can reconstruct page boundaries.
    """
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\f".join(pages)


def _extract_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file using python-docx."""
    import docx

    document = docx.Document(io.BytesIO(file_bytes))
    paragraphs: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Image extraction (for vision pipeline)
# ---------------------------------------------------------------------------

_MIN_IMAGE_SIZE = 50  # pixels — skip images smaller than 50x50
_MIN_IMAGE_BYTES = 5_000  # 5 KB — skip tiny graphics


def extract_pdf_images(file_bytes: bytes) -> list[dict]:
    """Extract embedded images from a PDF using PyMuPDF.

    Returns a list of dicts with keys:
        ``image_bytes`` (bytes), ``page_num`` (int), ``index`` (int),
        ``width`` (int), ``height`` (int).

    Filters out images that are too small (icons, bullets, decorations).
    """
    import fitz  # PyMuPDF

    results: list[dict] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    img_index = 0
    for page_num, page in enumerate(doc, start=1):
        image_list = page.get_images(full=True)
        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            if not base_image or not base_image.get("image"):
                continue

            img_bytes = base_image["image"]
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)

            # Skip tiny images (icons, bullets, decorations)
            if width < _MIN_IMAGE_SIZE or height < _MIN_IMAGE_SIZE:
                continue
            if len(img_bytes) < _MIN_IMAGE_BYTES:
                continue

            results.append({
                "image_bytes": img_bytes,
                "page_num": page_num,
                "index": img_index,
                "width": width,
                "height": height,
            })
            img_index += 1

    doc.close()
    return results


def is_pdf(filename: str) -> bool:
    """Return True if the filename has a .pdf extension."""
    return _get_extension(filename) == ".pdf"
