"""Database engine and session helpers. The URL comes from DATABASE_URL (SSM-provided in prod)."""

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

# Local docker-compose credentials only. Prod sets DATABASE_URL.
DEV_DATABASE_URL = "postgresql+psycopg://citeguard:citeguard_dev_password@localhost:5432/citeguard"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(os.environ.get("DATABASE_URL", DEV_DATABASE_URL), pool_pre_ping=True)


def new_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
