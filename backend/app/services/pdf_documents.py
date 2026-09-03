"""Safe, in-memory PDF text extraction and deterministic chunking."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid5

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DOCUMENT_NAMESPACE = UUID("ba42ea1e-9c5d-4fde-90b3-809bb0119685")
MAX_PDF_PAGES = 500
MAX_EXTRACTED_CHARACTERS = 5_000_000


class PdfDocumentError(Exception):
    """Base error for invalid or unsupported PDF documents."""


class PdfTooLargeError(PdfDocumentError):
    """Raised when a PDF exceeds configured processing limits."""


class NoExtractableTextError(PdfDocumentError):
    """Raised when a PDF requires OCR or contains no usable text."""


class UnsupportedPdfTypeError(PdfDocumentError):
    """Raised when an upload is not named as a PDF."""


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class TextChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    document_id: UUID
    filename: str
    page_count: int
    pages: list[PageText]


def extract_pdf(filename: str, content: bytes, max_bytes: int) -> ExtractedDocument:
    if Path(filename).suffix.lower() != ".pdf":
        raise UnsupportedPdfTypeError("Unsupported file type. Upload a .pdf file.")
    if len(content) > max_bytes:
        raise PdfTooLargeError(f"PDF exceeds the {max_bytes // (1024 * 1024)} MiB limit.")
    if not content:
        raise PdfDocumentError("The uploaded PDF is empty.")
    if not content.startswith(b"%PDF-"):
        raise PdfDocumentError("The uploaded file is not a valid PDF.")

    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise PdfDocumentError("Encrypted PDFs are not supported.")
        if not reader.pages:
            raise PdfDocumentError("The PDF contains no pages.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfTooLargeError(f"PDF exceeds the {MAX_PDF_PAGES}-page processing limit.")
        pages = []
        total_characters = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            total_characters += len(text)
            if total_characters > MAX_EXTRACTED_CHARACTERS:
                raise PdfTooLargeError("Extracted PDF text exceeds the processing limit.")
            pages.append(PageText(page_number=page_number, text=text))
    except PdfDocumentError:
        raise
    except (PdfReadError, ValueError, TypeError, OSError) as exc:
        raise PdfDocumentError("The uploaded PDF is malformed or unreadable.") from exc
    except Exception as exc:
        raise PdfDocumentError("PDF text extraction failed.") from exc

    if not any(page.text for page in pages):
        raise NoExtractableTextError("The PDF contains no extractable text. OCR is not implemented.")
    digest = sha256(content).hexdigest()
    return ExtractedDocument(
        document_id=uuid5(DOCUMENT_NAMESPACE, digest),
        filename=Path(filename).name,
        page_count=len(pages),
        pages=pages,
    )


def chunk_document(document: ExtractedDocument, chunk_size: int, overlap: int) -> list[TextChunk]:
    if chunk_size <= 0:
        raise PdfDocumentError("Chunk size must be greater than zero.")
    if overlap < 0 or overlap >= chunk_size:
        raise PdfDocumentError("Chunk overlap must be non-negative and smaller than chunk size.")

    chunks = []
    for page in document.pages:
        if not page.text:
            continue
        start = 0
        chunk_index = 0
        while start < len(page.text):
            end = min(start + chunk_size, len(page.text))
            if end < len(page.text):
                word_break = page.text.rfind(" ", start + chunk_size // 2, end)
                if word_break > start:
                    end = word_break
            text = page.text[start:end].strip()
            if text:
                chunk_id = uuid5(document.document_id, f"page:{page.page_number}:chunk:{chunk_index}:{text}")
                chunks.append(
                    TextChunk(
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        filename=document.filename,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=text,
                    )
                )
                chunk_index += 1
            if end >= len(page.text):
                break
            start = max(end - overlap, start + 1)
            while start < len(page.text) and page.text[start].isspace():
                start += 1
    return chunks


def _normalize_text(text: str) -> str:
    return " ".join(text.split())
