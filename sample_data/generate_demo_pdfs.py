"""Generate deterministic text-only PDF fixtures for repository demos."""

from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def write_pdf(path: Path, text: str) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    path.write_bytes(output.getvalue())


if __name__ == "__main__":
    write_pdf(Path(__file__).with_name("syllabus.pdf"), "Grading policy: An A requires at least 90%. The final exam is 30% of the course grade.")
    write_pdf(Path(__file__).with_name("commission_policy.pdf"), "Monthly commission policy: Salespeople earn a commission rate of 5% of completed net sales after discounts.")
