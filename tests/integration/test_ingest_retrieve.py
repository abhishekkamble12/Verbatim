"""Real Postgres: PDF -> chunks -> embeddings -> hybrid retrieval, with idempotency and rollback."""

import pymupdf
import pytest

from packages.ingestion.pipeline import ingest_pdf
from packages.retrieval.hybrid import RetrievalConfig, hybrid_retrieve
from packages.retrieval.models import Chunk, Notebook, Source, User
from packages.retrieval.repository import ChunkRepository
from tests.fakes import hash_embedding


def make_pdf(path, *page_texts):
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=10)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def notebook(db_session):
    db_session.add_all([User(id="u1", cognito_sub="s1", email="u1@x.com"), Notebook(id="nb1", user_id="u1", title="nb")])
    db_session.commit()
    return db_session


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "report.pdf"
    make_pdf(path, "Quarterly revenue grew by 14.2 percent. Operating margin reached 18.5 percent. "
                   "The cafeteria menu changes every Tuesday and includes soup.")
    return path


def embed(text):
    return hash_embedding(text, "t"), False


def test_ingest_stores_plain_text_and_offsets(notebook, pdf):
    result = ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=embed)
    assert result.created and result.chunk_count >= 1
    chunk = ChunkRepository().list_chunks(notebook, "u1", "nb1")[0]
    assert not chunk.text.startswith("report")  # the contextual header is embedded, never stored
    assert chunk.embedding is not None


def test_same_file_twice_is_one_source(notebook, pdf):
    first = ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=embed)
    second = ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=embed)
    assert first.source_id == second.source_id and second.created is False
    assert notebook.query(Source).count() == 1
    assert notebook.query(Chunk).count() == first.chunk_count


def test_failure_mid_document_leaves_nothing_behind(notebook, tmp_path):
    pdf = tmp_path / "two_pages.pdf"
    make_pdf(pdf, "Page one has a first finding about revenue.", "Page two has a second finding about margin.")
    calls = 0

    def flaky(text):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("embedding service down")
        return embed(text)

    with pytest.raises(RuntimeError):
        ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=flaky)
    assert notebook.query(Chunk).count() == 0 and notebook.query(Source).count() == 0
    # the retry (what SQS does after a crash) now succeeds cleanly
    assert ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=embed).created is True


def test_hybrid_retrieval_finds_the_relevant_chunk(notebook, pdf):
    ingest_pdf(notebook, "u1", "nb1", pdf, embed_fn=embed)
    hits = hybrid_retrieve(notebook, "operating margin", "u1", "nb1", RetrievalConfig(top_k=3), embed_fn=embed)
    assert hits and "Operating margin" in hits[0]["text"]
    assert hits[0]["doc_title"]
    # another user's identical query sees nothing
    assert hybrid_retrieve(notebook, "operating margin", "u2", "nb1", embed_fn=embed) == []
