"""
Application settings.

Every configurable value lives here so the rest of the code never reads
environment variables directly. Values come from (in priority order):

1. Real environment variables (for example, set by a hosting platform).
2. A `.env` file in the project root (for local development).
3. The defaults written below.

The Groq API key is only ever read here and passed to the CrewAI service.
It is never logged, never returned by the API and never sent to the browser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Folder layout:  <project root>/backend/app/core/config.py
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Load <project root>/.env if it exists. Existing environment variables win.
load_dotenv(PROJECT_ROOT / ".env", override=False)

# The project intentionally uses this exact Groq model. It is a constant,
# not an environment variable, so it cannot be changed by accident.
LLM_MODEL = "groq/openai/gpt-oss-20b"

# Input limits (also used by the Pydantic schemas and mirrored in app.js).
TOPIC_MIN_LENGTH = 2
TOPIC_MAX_LENGTH = 120
MAX_REQUEST_BODY_BYTES = 4 * 1024  # a topic request is tiny; 4 KB is plenty


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _get_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_database_url(raw_url: str) -> str:
    """Turn a relative SQLite path into an absolute one inside backend/.

    `sqlite:///./data/app.db` would otherwise depend on the folder you start
    the server from. Making it absolute means the same database file is used
    no matter where you run `uvicorn` from.
    """
    prefix = "sqlite:///"
    if raw_url.startswith(prefix) and not raw_url.startswith("sqlite:////"):
        relative_path = raw_url[len(prefix):]
        if relative_path and relative_path != ":memory:" and not Path(relative_path).is_absolute():
            absolute = (BACKEND_DIR / relative_path).resolve()
            absolute.parent.mkdir(parents=True, exist_ok=True)
            return f"{prefix}{absolute.as_posix()}"
    return raw_url


@dataclass(frozen=True)
class Settings:
    """All runtime settings in one immutable object."""

    app_name: str = "CrewAI Multi-Agent Learning Assistant"
    app_version: str = "1.0.0"
    environment: str = "development"

    # --- LLM / CrewAI ---
    groq_api_key: str = field(default="", repr=False)  # repr=False keeps it out of logs
    llm_model: str = LLM_MODEL
    llm_temperature: float = 0.4
    llm_max_tokens: int = 8192
    llm_timeout_seconds: int = 120
    llm_reasoning_effort: str = "low"
    crew_verbose: bool = False

    # --- Database ---
    database_url: str = "sqlite:///./data/learning_assistant.db"

    # --- Web server ---
    cors_origins: tuple[str, ...] = ()
    serve_frontend: bool = True
    enable_api_docs: bool = True

    # --- Protection of your Groq quota ---
    max_active_generations: int = 2

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key.strip())


def load_settings() -> Settings:
    """Build a Settings object from environment variables."""
    environment = os.getenv("APP_ENV", "development").strip().lower() or "development"
    default_origins = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ]
    return Settings(
        environment=environment,
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        llm_temperature=_get_float("LLM_TEMPERATURE", 0.4),
        llm_max_tokens=_get_int("LLM_MAX_TOKENS", 8192),
        llm_timeout_seconds=_get_int("LLM_TIMEOUT_SECONDS", 120),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low").strip().lower(),
        crew_verbose=_get_bool("CREW_VERBOSE", False),
        database_url=_resolve_database_url(
            os.getenv("DATABASE_URL", "sqlite:///./data/learning_assistant.db").strip()
        ),
        cors_origins=tuple(_get_list("CORS_ORIGINS", default_origins)),
        serve_frontend=_get_bool("SERVE_FRONTEND", True),
        enable_api_docs=_get_bool("ENABLE_API_DOCS", environment != "production"),
        max_active_generations=max(1, _get_int("MAX_ACTIVE_GENERATIONS", 2)),
    )


@lru_cache
def get_settings() -> Settings:
    """Return the settings, created once and then reused (cached)."""
    return load_settings()
