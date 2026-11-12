from pathlib import Path

import pytest

from packages.ingestion.chunker import DocumentChunk, chunk_page_text
from packages.ingestion.pdf_parser import NoTextLayerError, parse_pdf
from packages.ingestion.url_parser import parse_html_content


def create_sample_pdf(file_path: Path, pages_content: list[tuple[str, list[tuple[str, str]]]]):
    """Helper to create synthetic test PDFs using pymupdf.
    pages_content is a list of pages. Each page has (title, list of (heading, paragraph)).
    """
    import pymupdf

    doc = pymupdf.open()
    for _page_title, sections in pages_content:
        page = doc.new_page()
        y = 50
        for heading, body in sections:
            # Insert bold heading
            page.insert_text((50, y), heading, fontsize=16, fontname="helv", color=(0, 0, 0))
            y += 30
            # Insert body text
            rect = pymupdf.Rect(50, y, 550, y + 150)
            page.insert_textbox(rect, body, fontsize=10, fontname="helv", color=(0, 0, 0))
            y += 160
    doc.save(str(file_path))
    doc.close()


def test_refuse_pdf_without_text_layer(tmp_path: Path):
    """Verify that a PDF without extractable text raises NoTextLayerError."""
    import pymupdf

    pdf_path = tmp_path / "empty.pdf"
    doc = pymupdf.open()
    doc.new_page()  # Blank page with zero text
    doc.save(str(pdf_path))
    doc.close()

    with pytest.raises(NoTextLayerError) as exc_info:
        parse_pdf(pdf_path)
    assert "no extractable" in str(exc_info.value).lower()


def test_pdf_offset_roundtrip_sample_1(tmp_path: Path):
    """Test offset round-trip on PDF sample 1: single-page document with multiple sections."""
    pdf_path = tmp_path / "sample1.pdf"
    content = [
        (
            "Executive Overview",
            [
                (
                    "1. Introduction",
                    "CiteGuard is an evidence-first research workspace. It links every claim to an exact source quote. "
                    "When evidence is absent or insufficient, the system abstains honestly. "
                    "This architecture ensures high reliability and zero fabricated answers."
                ),
                (
                    "2. Performance Metrics",
                    "In our benchmark evaluation across eight categories, deterministic verification prevented numerical drift. "
                    "Operating margins increased by 14.2% while false acceptance dropped below 1.5%. "
                    "All measurements were verified on the held-out development split."
                ),
            ],
        )
    ]
    create_sample_pdf(pdf_path, content)

    parsed_doc = parse_pdf(pdf_path)
    assert len(parsed_doc.pages) == 1
    page = parsed_doc.pages[0]

    chunks = chunk_page_text(page_text=page.text, page_number=page.page_number, section=page.primary_section)
    assert len(chunks) > 0

    # Strict invariant check: page_text[start:end] == chunk.text
    for chunk in chunks:
        assert isinstance(chunk, DocumentChunk)
        sliced = page.text[chunk.start_char:chunk.end_char]
        assert sliced == chunk.text, f"Offset mismatch: expected '{sliced}', got '{chunk.text}'"
        assert chunk.sha256 is not None
        assert len(chunk.sha256) == 64


def test_pdf_offset_roundtrip_sample_2(tmp_path: Path):
    """Test offset round-trip on PDF sample 2: multi-page document with diverse paragraphs."""
    pdf_path = tmp_path / "sample2.pdf"
    content = [
        (
            "Page One",
            [
                (
                    "System Architecture",
                    "The backend utilizes PostgreSQL 16 with pgvector extension for dense embeddings. "
                    "Sparse keyword retrieval is powered by generated tsvector columns indexed with GIN. "
                    "Reciprocal Rank Fusion fuses both candidate sets with a constant of 60."
                ),
            ],
        ),
        (
            "Page Two",
            [
                (
                    "Verification Engine",
                    "Verification is executed in two stages. First, a deterministic rule checks numbers, units, and dates. "
                    "Second, an LLM entailment classifier verifies relational and semantic claim validity. "
                    "Any unverified claim is excised from the final response."
                ),
            ],
        ),
    ]
    create_sample_pdf(pdf_path, content)

    parsed_doc = parse_pdf(pdf_path)
    assert len(parsed_doc.pages) == 2

    for page in parsed_doc.pages:
        chunks = chunk_page_text(page_text=page.text, page_number=page.page_number, section=page.primary_section)
        assert len(chunks) > 0
        for chunk in chunks:
            sliced = page.text[chunk.start_char:chunk.end_char]
            assert sliced == chunk.text, f"Page {page.page_number} offset mismatch: '{sliced}' vs '{chunk.text}'"


def test_sentence_boundary_chunking():
    """Verify that chunks never split in the middle of a sentence."""
    text = (
        "First sentence here. Second sentence starts now and is quite detailed. "
        "Third sentence contains critical facts regarding the experiment. "
        "Fourth sentence summarizes the outcomes."
    )
    chunks = chunk_page_text(page_text=text, page_number=1, section="Intro", max_tokens=15, overlap_tokens=5)
    for c in chunks:
        # Every chunk should start with a capitalized word or start of sentence and end with punctuation
        assert c.text[0].isupper() or c.text.strip()[0].isupper()
        assert c.text.endswith(".")


def test_url_parser_trafilatura():
    """Test HTML parsing and extraction using Trafilatura."""
    html_sample = """
    <!DOCTYPE html>
    <html>
      <head><title>Research Note</title></head>
      <body>
        <article>
          <h1>Breakthrough in Quantum Computing</h1>
          <p>Researchers achieved quantum supremacy using superconducting qubits in a dilution refrigerator.</p>
        </article>
      </body>
    </html>
    """
    result = parse_html_content(html_sample)
    assert "quantum supremacy" in result.text.lower()
    assert result.title is not None



def test_nul_bytes_are_removed_from_extracted_text(tmp_path: Path, monkeypatch):
    # Some real PDFs (arXiv 2505.13949) extract with NUL characters; Postgres rejects them in text columns.
    import pymupdf

    pdf = tmp_path / "nul.pdf"
    create_sample_pdf(pdf, [("p1", [("Results", "Accuracy rose from 0.824 to 0.894 on the benchmark.")])])
    original = pymupdf.Page.get_text

    def with_nul(self, option="text", **kwargs):
        out = original(self, option, **kwargs)
        return out.replace("Accuracy", "Accu\x00racy") if isinstance(out, str) else out

    monkeypatch.setattr(pymupdf.Page, "get_text", with_nul)
    page = parse_pdf(pdf).pages[0]
    assert "\x00" not in page.text
    assert "Accuracy rose" in page.text
