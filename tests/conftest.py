import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from packages.llm_gateway import gateway
from packages.retrieval.db import DEV_DATABASE_URL
from tests import fakes

os.environ.setdefault("AUTH_MODE", "local")


@pytest.fixture(autouse=True)
def fake_llm(request, monkeypatch, tmp_path):
    """No test may reach a real model, and fake output must never land in the real disk cache."""
    monkeypatch.setattr(gateway, "DEFAULT_CACHE", gateway.DiskCache(str(tmp_path / "llm_cache")))
    if request.node.get_closest_marker("real_gateway"):
        return
    monkeypatch.setattr(gateway, "_call_external_provider", fakes.scripted_chat)
    monkeypatch.setattr(gateway, "_call_external_embedding", fakes.hash_embedding)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure tests run with clean rate limiting buckets."""
    from services.api.rate_limit import rate_limiter

    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture(scope="session")
def pg_url():
    """A throwaway `citeguard_test` database, built from scratch with `alembic upgrade head`.

    Skipped when Postgres is not running (start it with `make up`).
    """
    from alembic import command
    from alembic.config import Config

    base = make_url(os.environ.get("TEST_DATABASE_URL", DEV_DATABASE_URL))
    test_url = base.set(database="citeguard_test")
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS citeguard_test WITH (FORCE)"))
            conn.execute(text("CREATE DATABASE citeguard_test"))
    except OperationalError:
        pytest.skip("Postgres is not running (make up)")
    finally:
        admin.dispose()

    rendered = test_url.render_as_string(hide_password=False)
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = rendered
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL")
        else:
            os.environ["DATABASE_URL"] = old
    return rendered


@pytest.fixture
def db_session(pg_url):
    """A session on the migrated test database with every table emptied first."""
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"))
        names = ", ".join(row[0] for row in tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()
