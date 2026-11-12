"""Ingest a document into Postgres: parse -> chunk -> embed -> insert, all in one transaction.

A crash or error rolls the whole document back, and a document with the same SHA-256 in the same
notebook is skipped. Together that makes a retried SQS message safe (no partial or duplicate chunks).
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ingestion.chunker import DocumentChunk, chunk_fixed, chunk_page_text
from packages.ingestion.pdf_parser import parse_pdf
from packages.ingestion.url_parser import parse_url
from packages.llm_gateway.gateway import generate_embedding
from packages.retrieval.hybrid import build_contextual_header
from packages.retrieval.models import Chunk, Page, Source

EmbedFn = Callable[[str], tuple[list[float], bool]]


@dataclass
class IngestResult:
    source_id: str
    created: bool  # False when the same file was already ingested into this notebook
    chunk_count: int


def _ingest(
    session: Session,
    user_id: str,
    notebook_id: str,
    title: str,
    source_type: str,
    sha256: str,
    pages: list[tuple[int, str, str]],
    file_path: str | None = None,
    url: str | None = None,
    contextual_headers: bool = True,
    chunking: Literal["structure", "fixed"] = "structure",
    embed_fn: EmbedFn = generate_embedding,
) -> IngestResult:
    existing = session.execute(
        select(Source).where(Source.user_id == user_id, Source.notebook_id == notebook_id, Source.sha256 == sha256)
    ).scalar_one_or_none()
    if existing:
        count = session.execute(select(Chunk.id).where(Chunk.source_id == existing.id)).all()
        return IngestResult(existing.id, created=False, chunk_count=len(count))

    chunker = chunk_page_text if chunking == "structure" else chunk_fixed
    try:
        source = Source(
            id=f"src_{uuid.uuid4().hex[:12]}", user_id=user_id, notebook_id=notebook_id, title=title,
            source_type=source_type, file_path=file_path, url=url, sha256=sha256,
        )
        session.add(source)
        session.flush()
        total = 0
        for page_number, text, section in pages:
            session.add(Page(id=f"pg_{uuid.uuid4().hex[:12]}", source_id=source.id, page_number=page_number,
                             text=text, primary_section=section))
            chunks: list[DocumentChunk] = chunker(text, page_number=page_number, section=section)
            for ch in chunks:
                embed_text = build_contextual_header(title, ch.section, ch.text) if contextual_headers else ch.text
                vector, _ = embed_fn(embed_text)
                session.add(Chunk(
                    id=f"chk_{uuid.uuid4().hex[:12]}", user_id=user_id, notebook_id=notebook_id, source_id=source.id,
                    page_number=ch.page_number, section=ch.section, text=ch.text,  # stored text stays plain
                    start_char=ch.start_char, end_char=ch.end_char, token_count=ch.token_count,
                    sha256=ch.sha256, embedding=vector,
                ))
                total += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return IngestResult(source.id, created=True, chunk_count=total)


def ingest_pdf(
    session: Session, user_id: str, notebook_id: str, pdf_path: str | Path, file_path: str | None = None, **options
) -> IngestResult:
    """`file_path` is where the original lives for later download (the S3 key); it defaults to the local path."""
    path = Path(pdf_path)
    doc = parse_pdf(path)  # raises NoTextLayerError for scanned PDFs
    pages = [(p.page_number, p.text, p.primary_section) for p in doc.pages]
    return _ingest(
        session, user_id, notebook_id, doc.title or path.stem, "pdf",
        hashlib.sha256(path.read_bytes()).hexdigest(), pages, file_path=file_path or str(path), **options,
    )


def ingest_url(session: Session, user_id: str, notebook_id: str, url: str, **options) -> IngestResult:
    doc = parse_url(url)
    sha = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
    return _ingest(
        session, user_id, notebook_id, doc.title or url, "url", sha, [(1, doc.text, "General")], url=url, **options
    )
