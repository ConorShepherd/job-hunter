"""Extract plain text from a CV PDF."""
from __future__ import annotations

from pypdf import PdfReader


class CVParseError(RuntimeError):
    pass


def extract_text(pdf_path: str) -> str:
    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:
        raise CVParseError(f"Could not open '{pdf_path}' as a PDF: {exc}") from exc

    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise CVParseError(
            f"No extractable text found in '{pdf_path}' (it may be a scanned/image-only PDF)."
        )
    return text
