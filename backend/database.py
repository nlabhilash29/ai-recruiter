"""Database URL handling.

Render's Postgres addon publishes ``postgres://`` URLs. SQLAlchemy 2 and
psycopg2 want ``postgresql+psycopg2://``. Local development keeps SQLite when
``DATABASE_URL`` is unset. Nothing in here loads sample interviews.
"""

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models import init_db

_ADDED_COLUMNS = {
    "interview_sessions": {
        "question_mode": "VARCHAR(32) DEFAULT 'preset'",
        "main_question_target": "INTEGER DEFAULT 5",
        "role_family": "VARCHAR(64)",
        "rubric": "TEXT",
        "dimension_scores": "TEXT",
        "recommendation": "TEXT",
    },
    "interview_questions": {
        "main_index": "INTEGER",
        "is_follow_up": "BOOLEAN DEFAULT FALSE",
        "dimension": "VARCHAR(64)",
    },
    "candidate_responses": {
        "evidence": "TEXT",
        "dimension_scores": "TEXT",
    },
}


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


def ensure_columns(engine) -> None:
    """Add columns introduced after the first deploy. Old rows stay readable."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, declaration in columns.items():
                if name in present:
                    continue
                column_type = declaration
                if dialect == "sqlite" and column_type.startswith("BOOLEAN"):
                    column_type = "INTEGER DEFAULT 0"
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"))


def build_session_factory(url: str | None = None):
    engine, normalized = create_db_engine(url)
    init_db(engine)
    ensure_columns(engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine), normalized
