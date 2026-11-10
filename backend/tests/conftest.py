"""
Shared test setup (pytest loads this file automatically).

Safety rules enforced here:
* A fake, obviously-invalid GROQ_API_KEY is set, so no test ever needs or
  sees your real key.
* `run_learning_crew` (the only function that calls Groq) is replaced in
  EVERY test by a guard that fails loudly. Tests that need agent output
  replace it again with a fake from fakes.py.
* Every API test gets a brand-new, empty SQLite database in a temp folder.
"""

import os
import tempfile
from pathlib import Path

import pytest

# These must be set BEFORE the app is imported, because settings are read at import time.
_TEST_DIR = Path(tempfile.mkdtemp(prefix="learning-assistant-tests-"))
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DIR / 'import-time.db').as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["MAX_ACTIVE_GENERATIONS"] = "2"


def _live_crew_guard(*_args, **_kwargs):
    raise AssertionError("A test tried to run the real CrewAI/Groq pipeline. Use a fake instead.")


@pytest.fixture(autouse=True)
def block_live_llm_calls(monkeypatch):
    """Make accidental live Groq calls impossible in every test."""
    try:
        from app.services import generation_service
    except ImportError:
        # SQLAlchemy is not installed, so only the pure-logic tests can run;
        # none of them can reach the CrewAI pipeline anyway.
        yield
        return
    monkeypatch.setattr(generation_service, "run_learning_crew", _live_crew_guard)
    yield


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def db_session(db_url):
    """A database session on a fresh, empty test database."""
    from app.database import database

    database.configure_database(db_url)
    database.init_db()
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_url):
    """A FastAPI TestClient wired to a fresh, empty test database."""
    from fastapi.testclient import TestClient

    from app.database import database
    from app.main import app

    database.configure_database(db_url)
    with TestClient(app) as test_client:  # "with" runs the startup code (creates tables)
        yield test_client
    app.dependency_overrides.clear()
