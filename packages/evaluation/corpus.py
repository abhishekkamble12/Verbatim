"""Evaluation corpus: your real PDFs in data/corpus/, ingested into Postgres, judged by gold passages.

Relevance rule: a retrieved chunk is relevant to a question when it contains one of that question's
`gold_passages` (after lowercasing and collapsing whitespace). Write gold passages as short, exact
spans (ideally one sentence) copied from the document, so they fall inside one chunk.
"""

import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from packages.ingestion.pipeline import ingest_pdf
from packages.retrieval.models import Notebook, User

CORPUS_DIR = "data/corpus"
EVAL_USER = "eval_user"


class NoCorpusError(RuntimeError):
    """Raised when there are no PDFs to evaluate on."""


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def ranked_gold_ids(retrieved: list[dict], gold_passages: list[str]) -> list[str]:
    """Rank list for the metric functions: each retrieved chunk becomes the gold passage it
    contains (e.g. 'gold-0'), or its own id when it contains none, so non-relevant chunks never match."""
    passages = [normalize(p) for p in gold_passages]
    ranked = []
    for chunk in retrieved:
        text = normalize(chunk["text"])
        hit = next((f"gold-{i}" for i, p in enumerate(passages) if p and p in text), None)
        ranked.append(hit or chunk["id"])
    return ranked


def gold_ids_for(gold_passages: list[str]) -> list[str]:
    return [f"gold-{i}" for i in range(len(gold_passages))]


def ingest_corpus(
    session: Session,
    corpus_dir: str = CORPUS_DIR,
    **ingest_options,
) -> str:
    """Ingest every PDF in corpus_dir into a fresh notebook and return its id."""
    pdfs = sorted(Path(corpus_dir).glob("*.pdf"))
    if not pdfs:
        raise NoCorpusError(
            f"No PDFs found in {corpus_dir}/. Put the 20-30 documents your golden questions are about there "
            "(roadmap T1.5). Evaluation does not run on made-up data."
        )
    if session.get(User, EVAL_USER) is None:
        session.add(User(id=EVAL_USER, cognito_sub=EVAL_USER, email="eval@citeguard.local"))
        session.commit()
    notebook_id = f"eval_{uuid.uuid4().hex[:8]}"
    session.add(Notebook(id=notebook_id, user_id=EVAL_USER, title="evaluation corpus"))
    session.commit()
    for pdf in pdfs:
        ingest_pdf(session, EVAL_USER, notebook_id, pdf, **ingest_options)
    return notebook_id
