"""
Database connection setup (SQLite + SQLAlchemy 2.x).

Three things live here:

* `engine`        - the object that knows how to talk to the SQLite file.
* `SessionLocal`  - a factory that creates a new database session.
* `Base`          - the parent class for every table model (see models.py).

Other modules should use `database.SessionLocal()` (looking it up on the
module at call time) rather than `from ... import SessionLocal`. That way the
tests can point the whole app at a temporary database with
`configure_database(...)`.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Parent class for all SQLAlchemy table models."""


def _create_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI may use the database from different threads (the request
        # thread and the background-task thread). SQLite needs this flag to
        # allow that. Each thread still gets its own session.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


engine: Engine = _create_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_database(database_url: str) -> None:
    """Point the application at a different database (used by the tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables that do not exist yet. Safe to call many times."""
    # Importing models registers the table classes on Base.metadata.
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: give each request its own session, then close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
