"""Tests for the Pydantic request/response models (no server needed)."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.generation import GenerationCreate, GenerationSummary


def test_topic_is_stripped_and_spaces_collapsed():
    assert GenerationCreate(topic="  Python    decorators ").topic == "Python decorators"


@pytest.mark.parametrize(
    "data",
    [
        {"topic": ""},
        {"topic": "    "},
        {"topic": "x"},
        {"topic": "x" * 121},
        {"topic": 42},
        {"topic": ["FastAPI"]},
        {"topic": "line one\nline two"},
        {"topic": "tab\there"},
        {},
        {"topic": "FastAPI", "unexpected": True},
    ],
)
def test_invalid_topics(data):
    with pytest.raises(ValidationError):
        GenerationCreate(**data)


def test_maximum_length_topic_is_accepted():
    assert len(GenerationCreate(topic="x" * 120).topic) == 120


def test_naive_datetimes_are_returned_as_utc():
    summary = GenerationSummary(id="a" * 32, topic="Git", status="completed", created_at=datetime(2026, 1, 1, 12))
    assert summary.created_at.tzinfo is not None
    assert summary.model_dump_json().count("Z") + summary.model_dump_json().count("+00:00") >= 1
