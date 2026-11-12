import pytest

from packages.retrieval.models import Chunk, Notebook, User
from packages.retrieval.repository import ChunkRepository, SecurityAccessDeniedError
from tests.fakes import hash_embedding


def _seed(session, user, nb, chunk_id, text):
    session.add_all([
        User(id=user, cognito_sub=f"sub_{user}", email=f"{user}@example.com"),
        Notebook(id=nb, user_id=user, title=nb),
    ])
    session.flush()
    session.add(Chunk(
        id=chunk_id, user_id=user, notebook_id=nb, text=text, page_number=1, section="S",
        start_char=0, end_char=len(text), token_count=8, sha256=chunk_id.ljust(64, "0"),
        embedding=hash_embedding(text, "t"),
    ))
    session.commit()


@pytest.fixture
def two_tenants(db_session):
    _seed(db_session, "user_a", "nb_a", "chunk_a", "Confidential quarterly earnings for User A.")
    _seed(db_session, "user_b", "nb_b", "chunk_b", "Public research notes about earnings for User B.")
    return db_session


def test_get_by_id_is_tenant_scoped(two_tenants):
    repo = ChunkRepository()
    assert repo.get_chunk_by_id(two_tenants, "chunk_a", "user_a", "nb_a").id == "chunk_a"
    assert repo.get_chunk_by_id(two_tenants, "chunk_a", "user_b", "nb_b") is None
    # right notebook, wrong user
    assert repo.get_chunk_by_id(two_tenants, "chunk_a", "user_b", "nb_a") is None


def test_search_cannot_see_other_tenants(two_tenants):
    """Both dense and sparse search on real Postgres: user B asking for 'earnings' never gets A's chunk."""
    repo = ChunkRepository()
    sparse = repo.sparse_search(two_tenants, "earnings", "user_b", "nb_b")
    assert [c["id"] for c in sparse] == ["chunk_b"]
    dense = repo.dense_search(two_tenants, hash_embedding("Confidential quarterly earnings for User A.", "t"), "user_b", "nb_b")
    assert [c["id"] for c in dense] == ["chunk_b"]  # A's chunk is the closest vector overall, but filtered out


def test_missing_scope_raises(two_tenants):
    repo = ChunkRepository()
    with pytest.raises(SecurityAccessDeniedError):
        repo.get_chunk_by_id(two_tenants, "chunk_a", "", "nb_a")
    with pytest.raises(SecurityAccessDeniedError):
        repo.sparse_search(two_tenants, "earnings", "user_a", "")
    with pytest.raises(SecurityAccessDeniedError):
        repo.dense_search(two_tenants, [0.0] * 1024, "", "nb_a")


def test_list_chunks_filters_both_ids(two_tenants):
    repo = ChunkRepository()
    assert [c.id for c in repo.list_chunks(two_tenants, "user_b", "nb_b")] == ["chunk_b"]
    assert repo.list_chunks(two_tenants, "user_b", "nb_a") == []
