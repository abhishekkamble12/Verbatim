"""PDF parsing with PyMuPDF, structure detection, and text layer validation."""

from pathlib import Path

from pydantic import BaseModel, Field


class NoTextLayerError(Exception):
    """Raised when a PDF contains no extractable text layer (e.g., scanned image)."""
    pass


class ParsedPage(BaseModel):
    page_number: int
    text: str
    primary_section: str = "General"
    headings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    file_path: str
    total_pages: int
    pages: list[ParsedPage]
    title: str | None = None


def parse_pdf(file_path: str | Path) -> ParsedDocument:
    """Parse a digital PDF file, validating text layer and extracting structure."""
    import pymupdf

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found at {path}")

    doc = pymupdf.open(str(path))
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise NoTextLayerError(f"PDF file '{path.name}' contains zero pages.")

    pages = []
    total_text_length = 0
    current_section = "Introduction"
    doc_title = doc.metadata.get("title") or path.stem

    for page_idx in range(total_pages):
        page = doc[page_idx]
        page_num = page_idx + 1

        # Extract plain text
        # Some PDFs extract with NUL characters, which Postgres text columns reject. Removed here,
        # before chunking, so character offsets stay consistent with the stored text.
        page_text = page.get_text("text").replace("\x00", "")
        total_text_length += len(page_text.strip())

        # Extract headings by inspecting text blocks / spans
        headings = []
        try:
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") == 0:  # text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            size = span.get("size", 10)
                            flags = span.get("flags", 0)  # flag & 2 is bold
                            span_text = span.get("text", "").replace("\x00", "").strip()
                            if span_text and (size >= 13 or (flags & 2 and size >= 11)):
                                if len(span_text) < 100:
                                    headings.append(span_text)
                                    current_section = span_text
        except Exception:
            pass

        pages.append(
            ParsedPage(
                page_number=page_num,
                text=page_text,
                primary_section=headings[0] if headings else current_section,
                headings=headings,
            )
        )

    doc.close()

    # Strict check: refuse scanned PDFs with no text layer
    if total_text_length < 20:
        raise NoTextLayerError(
            f"PDF '{path.name}' has no extractable digital text layer (total characters: {total_text_length}). "
            "CiteGuard requires digital text PDFs; OCR is not supported."
        )

    return ParsedDocument(
        file_path=str(path),
        total_pages=total_pages,
        pages=pages,
        title=doc_title,
    )

