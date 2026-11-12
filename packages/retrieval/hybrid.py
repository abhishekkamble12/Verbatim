"""Hybrid retrieval over Postgres: pgvector dense + full-text sparse, fused with RRF.

Contextual headers ('doc title > section > chunk') are applied when chunks are embedded at ingestion
time (packages/ingestion/pipeline.py). The stored chunk text stays plain.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from packages.llm_gateway.gateway import generate_embedding
from packages.retrieval.repository import ChunkRepository


@dataclass
class RetrievalConfig:
    use_dense: bool = True
    use_sparse: bool = True
    rrf_k: int = 60
    candidates: int = 20
    top_k: int = 8


def build_contextual_header(doc_title: str | None, section: str | None, chunk_text: str) -> str:
    """Prepend 'doc title > section > chunk text' for embedding."""
    parts = [p.strip() for p in (doc_title, section if section != "General" else None) if p and p.strip()]
    return " > ".join([*parts, chunk_text])


def apply_rrf_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: RRF(d) = sum over rankings of 1 / (k + rank(d))."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_retrieve(
    session: Session,
    query: str,
    user_id: str,
    notebook_id: str,
    config: RetrievalConfig | None = None,
    embed_fn: Callable[[str], tuple[list[float], bool]] = generate_embedding,
) -> list[dict[str, Any]]:
    """Top chunks for `query` inside one user's notebook. Returns [] when nothing matches."""
    config = config or RetrievalConfig()
    repo = ChunkRepository()
    by_id: dict[str, dict[str, Any]] = {}
    rankings: list[list[str]] = []

    if config.use_dense:
        vector, _ = embed_fn(query)
        dense = repo.dense_search(session, vector, user_id, notebook_id, config.candidates)
        by_id.update({c["id"]: c for c in dense})
        rankings.append([c["id"] for c in dense])
    if config.use_sparse:
        sparse = repo.sparse_search(session, query, user_id, notebook_id, config.candidates)
        by_id.update({c["id"]: c for c in sparse})
        rankings.append([c["id"] for c in sparse])

    scores = apply_rrf_fusion(rankings, k=config.rrf_k)
    top = sorted(scores, key=scores.get, reverse=True)[: config.top_k]
    return [{**by_id[i], "score": scores[i]} for i in top]
