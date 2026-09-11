"""Shared archive-level safety checks for XLSX ingestion."""

from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


MAX_WORKBOOK_PARTS = 5_000
MAX_WORKBOOK_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


class WorkbookArchiveError(Exception):
    """Raised when an XLSX archive is malformed or contains unsafe content."""


class WorkbookArchiveTooLargeError(WorkbookArchiveError):
    """Raised before parsing when an XLSX archive expands past safe limits."""


def validate_workbook_archive(content: bytes) -> None:
    """Reject oversized, traversing, macro-enabled, or active XLSX archives."""

    try:
        with ZipFile(BytesIO(content)) as archive:
            parts = archive.infolist()
            if (
                len(parts) > MAX_WORKBOOK_PARTS
                or sum(item.file_size for item in parts) > MAX_WORKBOOK_UNCOMPRESSED_BYTES
            ):
                raise WorkbookArchiveTooLargeError(
                    "The XLSX archive expands beyond supported safety limits."
                )
            for item in parts:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise WorkbookArchiveError(
                        "The XLSX archive contains an unsafe internal path."
                    )
                if path.name.casefold() == "vbaproject.bin":
                    raise WorkbookArchiveError("Macro-enabled workbooks are not accepted.")
                lowered = item.filename.casefold()
                if lowered.startswith(
                    ("xl/activex/", "xl/embeddings/", "xl/externallinks/")
                ):
                    raise WorkbookArchiveError(
                        "Workbooks containing embedded or externally linked active content are not accepted."
                    )
    except BadZipFile as exc:
        raise WorkbookArchiveError(
            "The XLSX file is not a valid workbook archive."
        ) from exc
