"""Database URL handling.

Render's Postgres addon publishes ``postgres://`` URLs. SQLAlchemy 2 and
psycopg2 want ``postgresql+psycopg2://``. Local development keeps SQLite when
``DATABASE_URL`` is unset. Nothing in here loads sample interviews.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import init_db


def normalize_database_url(url: str | None) -> str:
    raw = (url or "").strip() or "sqlite:///./test.db"
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg2://" + raw[len("postgresql://") :]
    return raw


def create_db_engine(url: str | None = None):
    normalized = normalize_database_url(url if url is not None else os.getenv("DATABASE_URL"))
    kwargs = {"pool_pre_ping": True}
    if normalized.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(normalized, **kwargs)
    return engine, normalized


def build_session_factory(url: str | None = None):
    engine, normalized = create_db_engine(url)
    init_db(engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine), normalized
