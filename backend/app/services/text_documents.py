"""UTF-8 plain-text extraction that reuses PDF chunking and retrieval provenance."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid5

from app.services.pdf_documents import DOCUMENT_NAMESPACE, ExtractedDocument, NoExtractableTextError, PageText

MAX_TXT_BYTES = 2 * 1024 * 1024
MAX_TXT_CHARACTERS = 1_000_000


class TextDocumentError(Exception):
    """Raised when a plain-text document cannot be ingested safely."""


class TextTooLargeError(TextDocumentError):
    """Raised when a text document exceeds processing limits."""


class UnsupportedTextTypeError(TextDocumentError):
    """Raised when an upload is not a supported text document."""


def extract_txt(filename: str, content: bytes, max_bytes: int = MAX_TXT_BYTES) -> ExtractedDocument:
    if Path(filename).suffix.lower() != ".txt":
        raise UnsupportedTextTypeError("Unsupported file type. Upload a .txt file.")
    limit = min(max_bytes, MAX_TXT_BYTES)
    if len(content) > limit:
        raise TextTooLargeError(f"Text document exceeds the {limit // (1024 * 1024) or 1} MiB limit.")
    if not content:
        raise TextDocumentError("The uploaded text document is empty.")
    if content.startswith(b"%PDF-") or content[:2] == b"PK":
        raise TextDocumentError("The uploaded file is not plain text.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TextDocumentError("Text documents must be valid UTF-8.") from exc
    if "\x00" in text:
        raise TextDocumentError("Text documents containing null bytes are not accepted.")
    normalized = " ".join(text.split())
    if not normalized:
        raise NoExtractableTextError("The text document contains no extractable text.")
    if len(normalized) > MAX_TXT_CHARACTERS:
        raise TextTooLargeError("Extracted text exceeds the processing limit.")
    digest = sha256(content).hexdigest()
    return ExtractedDocument(
        document_id=uuid5(DOCUMENT_NAMESPACE, digest),
        filename=Path(filename).name,
        page_count=1,
        pages=[PageText(page_number=1, text=normalized)],
    )
