"""
Database table definitions.

The application needs only ONE table, `generations`. Each row is one
"please teach me <topic>" request and everything the four agents produced
for it. Because there is nothing else to relate it to (no users, no tags),
no relationships between tables are needed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base


class GenerationStatus(str, enum.Enum):
    """The four states a generation moves through."""

    PENDING = "pending"        # saved, waiting for the background worker
    PROCESSING = "processing"  # the CrewAI agents are running
    COMPLETED = "completed"    # all four agents finished and output passed validation
    FAILED = "failed"          # something went wrong; see error_message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_generation_id() -> str:
    # 32 hexadecimal characters, e.g. "3f2b9c...". Random, so IDs cannot be guessed.
    return uuid.uuid4().hex


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_generation_id)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GenerationStatus.PENDING.value, index=True
    )

    # How many of the four agent tasks have finished. Updated by a real
    # CrewAI callback, so the progress shown in the browser is genuine.
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Results (empty until the generation completes) ---
    teaching_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    qa_pairs: Mapped[list | None] = mapped_column(JSON, nullable=True)   # [{"question": ..., "answer": ...}] x3
    summary_points: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["...", ...] x5
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Timestamps (stored in UTC) ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # shown when you print() a row while debugging
        return f"<Generation id={self.id} topic={self.topic!r} status={self.status}>"
