"""Repository layer enforcing multi-tenant isolation on all chunk queries.

Every method requires user_id AND notebook_id and puts both in the WHERE clause.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.retrieval.models import Chunk, Source


class SecurityAccessDeniedError(Exception):
    """Raised when an operation attempts to bypass user_id or notebook_id isolation."""


class ChunkRepository:
    """Multi-tenant chunk repository where every query requires user_id and notebook_id."""

    @staticmethod
    def _validate_tenant_scope(user_id: str, notebook_id: str) -> None:
        if not user_id or not str(user_id).strip():
            raise SecurityAccessDeniedError("Multi-tenant isolation violation: user_id is strictly required.")
        if not notebook_id or not str(notebook_id).strip():
            raise SecurityAccessDeniedError("Multi-tenant isolation violation: notebook_id is strictly required.")

    def add_chunk(self, session: Session, chunk: Chunk) -> Chunk:
        self._validate_tenant_scope(chunk.user_id, chunk.notebook_id)
        session.add(chunk)
        session.flush()
        return chunk

    def get_chunk_by_id(self, session: Session, chunk_id: str, user_id: str, notebook_id: str) -> Chunk | None:
        self._validate_tenant_scope(user_id, notebook_id)
        stmt = select(Chunk).where(
            Chunk.id == chunk_id,
            Chunk.user_id == user_id,
            Chunk.notebook_id == notebook_id,
        )
        return session.execute(stmt).scalar_one_or_none()

    def list_chunks(self, session: Session, user_id: str, notebook_id: str, limit: int = 50) -> list[Chunk]:
        self._validate_tenant_scope(user_id, notebook_id)
        stmt = select(Chunk).where(Chunk.user_id == user_id, Chunk.notebook_id == notebook_id).limit(limit)
        return list(session.execute(stmt).scalars().all())

    def dense_search(
        self,
        session: Session,
        query_embedding: list[float],
        user_id: str,
        notebook_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Nearest chunks by cosine distance (pgvector HNSW index)."""
        self._validate_tenant_scope(user_id, notebook_id)
        distance = Chunk.embedding.cosine_distance(query_embedding)
        stmt = (
            self._select_with_title()
            .where(Chunk.user_id == user_id, Chunk.notebook_id == notebook_id, Chunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        return [self._to_dict(c, title) for c, title in session.execute(stmt).all()]

    def sparse_search(
        self,
        session: Session,
        query: str,
        user_id: str,
        notebook_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text matches ranked by ts_rank (GIN index on the generated tsvector)."""
        self._validate_tenant_scope(user_id, notebook_id)
        tsquery = func.websearch_to_tsquery("english", query)
        stmt = (
            self._select_with_title()
            .where(Chunk.user_id == user_id, Chunk.notebook_id == notebook_id, Chunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank(Chunk.tsv, tsquery).desc())
            .limit(limit)
        )
        return [self._to_dict(c, title) for c, title in session.execute(stmt).all()]

    @staticmethod
    def _select_with_title():
        return select(Chunk, Source.title).outerjoin(Source, Source.id == Chunk.source_id)

    @staticmethod
    def _to_dict(chunk: Chunk, doc_title: str | None) -> dict[str, Any]:
        return {
            "id": chunk.id,
            "text": chunk.text,
            "section": chunk.section,
            "doc_title": doc_title,
            "page_number": chunk.page_number,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
        }
