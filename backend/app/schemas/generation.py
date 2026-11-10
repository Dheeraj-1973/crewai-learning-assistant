"""
Pydantic schemas: the exact shape of data going IN to and OUT of the API.

* `GenerationCreate`  - what the browser must send to start a generation.
* `GenerationSummary` - one row in the history list (no big text fields).
* `GenerationDetail`  - everything about one generation, including results.

FastAPI uses these classes to validate requests automatically and to turn
database rows into JSON responses.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import TOPIC_MAX_LENGTH, TOPIC_MIN_LENGTH

TOTAL_AGENT_STEPS = 4

# Control characters (newlines, tabs, NUL, ...) have no place in a topic name.
# Rejecting them also blocks multi-line text meant to smuggle instructions
# into the agent prompts.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class GenerationCreate(BaseModel):
    """Request body for POST /api/generations."""

    model_config = ConfigDict(
        str_strip_whitespace=True,  # "  FastAPI  " becomes "FastAPI" before checks run
        extra="forbid",             # unknown fields are an error, not silently ignored
        json_schema_extra={"examples": [{"topic": "FastAPI"}]},
    )

    topic: str = Field(
        ...,
        min_length=TOPIC_MIN_LENGTH,
        max_length=TOPIC_MAX_LENGTH,
        description="The technical topic to learn, e.g. 'FastAPI' or 'Python decorators'.",
    )

    @field_validator("topic", mode="before")
    @classmethod
    def reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and _CONTROL_CHARS.search(value.strip()):
            raise ValueError("Topic must be a single line without control characters.")
        return value

    @field_validator("topic")
    @classmethod
    def collapse_spaces(cls, value: str) -> str:
        # "Python    decorators" -> "Python decorators"
        return re.sub(r"\s+", " ", value)


class QAPair(BaseModel):
    question: str
    answer: str


class Progress(BaseModel):
    completed_steps: int = Field(ge=0, le=TOTAL_AGENT_STEPS)
    total_steps: int = TOTAL_AGENT_STEPS


class _TimestampMixin(BaseModel):
    """SQLite forgets time zones, so we re-attach UTC when reading."""

    @field_validator("created_at", "started_at", "completed_at", mode="after", check_fields=False)
    @classmethod
    def ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class GenerationSummary(_TimestampMixin):
    """A short view of a generation, used in the history list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    topic: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class GenerationDetail(_TimestampMixin):
    """The full view of a generation, including results when completed."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    topic: str
    status: str
    progress: Progress
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    teaching_plan: str | None = None
    explanation: str | None = None
    qa_pairs: list[QAPair] | None = None
    summary_points: list[str] | None = None
    markdown: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None


class GenerationList(BaseModel):
    items: list[GenerationSummary]
    count: int


class HealthResponse(BaseModel):
    status: str
    database: str
    llm_configured: bool
    model: str
    version: str


class ErrorResponse(BaseModel):
    """Shape of every error the API returns (documented in /docs)."""

    detail: str
    errors: list[dict] | None = None
