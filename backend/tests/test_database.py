"""Tests for the database layer and generation_service helpers (no API)."""

from datetime import timedelta

import pytest

pytest.importorskip("sqlalchemy")

from app.database.models import Generation, GenerationStatus, utc_now  # noqa: E402
from app.services import generation_service  # noqa: E402
from tests import fakes  # noqa: E402


def test_create_and_read_generation(db_session):
    created = generation_service.create_generation(db_session, "SQL joins")
    assert created.status == GenerationStatus.PENDING.value
    assert created.completed_steps == 0
    assert created.created_at is not None

    fetched = generation_service.get_generation(db_session, created.id)
    assert fetched is not None and fetched.topic == "SQL joins"
    assert generation_service.get_generation(db_session, "missing") is None


def test_list_generations_newest_first_with_limit(db_session):
    now = utc_now()
    for minutes, topic in [(3, "old"), (2, "middle"), (1, "new")]:
        db_session.add(Generation(topic=topic, created_at=now - timedelta(minutes=minutes)))
    db_session.commit()

    assert [g.topic for g in generation_service.list_generations(db_session)] == ["new", "middle", "old"]
    assert len(generation_service.list_generations(db_session, limit=2)) == 2


def test_count_active_generations(db_session):
    db_session.add_all(
        [
            Generation(topic="a", status=GenerationStatus.PENDING.value),
            Generation(topic="b", status=GenerationStatus.PROCESSING.value),
            Generation(topic="c", status=GenerationStatus.COMPLETED.value),
            Generation(topic="d", status=GenerationStatus.FAILED.value),
        ]
    )
    db_session.commit()
    assert generation_service.count_active_generations(db_session) == 2


def test_interrupted_generations_are_failed_on_restart(db_session):
    stuck = Generation(topic="stuck", status=GenerationStatus.PROCESSING.value)
    done = Generation(topic="done", status=GenerationStatus.COMPLETED.value)
    db_session.add_all([stuck, done])
    db_session.commit()

    assert generation_service.fail_interrupted_generations(db_session) == 1
    db_session.expire_all()
    assert db_session.get(Generation, stuck.id).status == "failed"
    assert "restarted" in db_session.get(Generation, stuck.id).error_message
    assert db_session.get(Generation, done.id).status == "completed"


def test_run_generation_saves_all_results(db_session, monkeypatch):
    monkeypatch.setattr(generation_service, "run_learning_crew", fakes.fake_successful_crew)
    generation = generation_service.create_generation(db_session, "FastAPI")

    generation_service.run_generation(generation.id)

    db_session.expire_all()
    saved = db_session.get(Generation, generation.id)
    assert saved.status == "completed"
    assert saved.started_at is not None and saved.completed_at is not None
    assert len(saved.qa_pairs) == 3 and len(saved.summary_points) == 5
    assert saved.markdown.count("## ") >= 4
    assert saved.error_message is None
