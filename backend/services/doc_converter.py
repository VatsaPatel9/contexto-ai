"""Convert Office documents (docx, doc, pptx, ppt) to PDF via LibreOffice.

We shell out to LibreOffice's headless CLI rather than using python-uno or
docx2pdf because:
  1. It's the most faithful OSS converter for Office formats.
  2. Each invocation can be isolated via a per-call `UserInstallation` dir
     so concurrent uploads don't step on each other.
  3. No long-lived process to manage from Python.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# File extensions (lowercased, including leading dot) that should be run
# through LibreOffice before the rest of the upload pipeline touches them.
CONVERTIBLE_EXTENSIONS: set[str] = {
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".odt",
    ".odp",
    ".rtf",
}

LIBREOFFICE_BIN = shutil.which("soffice") or shutil.which("libreoffice") or "soffice"
CONVERSION_TIMEOUT_SECONDS = 180


def is_convertible(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in CONVERTIBLE_EXTENSIONS


def convert_to_pdf(source_bytes: bytes, filename: str) -> bytes:
    """Convert an Office document to PDF and return the PDF bytes.

    Raises :class:`RuntimeError` if LibreOffice fails or times out.
    """
    ext = Path(filename).suffix.lower() or ".docx"

    with tempfile.TemporaryDirectory(prefix="contexto_doc_") as tmp:
        input_path = os.path.join(tmp, f"input{ext}")
        with open(input_path, "wb") as fh:
            fh.write(source_bytes)

        # Isolate this conversion's LibreOffice profile so parallel
        # soffice invocations don't clobber each other's lock files.
        user_profile = f"-env:UserInstallation=file://{tmp}/lo_profile_{uuid.uuid4()}"

        try:
            result = subprocess.run(
                [
                    LIBREOFFICE_BIN,
                    user_profile,
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    input_path,
                ],
                capture_output=True,
                timeout=CONVERSION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error("LibreOffice conversion timed out for %s", filename)
            raise RuntimeError("Document conversion timed out") from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                "LibreOffice conversion failed (rc=%s) for %s: %s",
                result.returncode,
                filename,
                stderr,
            )
            raise RuntimeError(f"Document conversion failed: {stderr or 'unknown error'}")

        pdf_path = os.path.join(tmp, "input.pdf")
        if not os.path.exists(pdf_path):
            raise RuntimeError("LibreOffice produced no PDF output")

        with open(pdf_path, "rb") as fh:
            return fh.read()
