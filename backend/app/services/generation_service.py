"""
Generation workflow: database operations + the background job.

The API routes call the small functions here instead of touching the
database or CrewAI directly. That keeps routes short and makes this logic
easy to test on its own.

Lifecycle of one generation
---------------------------
    create_generation()        -> status "pending"   (saved, ID returned to browser)
    run_generation()  starts   -> status "processing"
        each agent finishes    -> completed_steps = 1, 2, 3, 4
        outputs validated OK   -> status "completed" (results + Markdown saved)
        anything goes wrong    -> status "failed"    (error_message saved)
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import database
from app.database.models import Generation, GenerationStatus, utc_now
from app.services.crewai_service import CrewExecutionError, LLMNotConfiguredError, run_learning_crew
from app.services.markdown_builder import build_learning_notes
from app.services.output_parser import (
    OutputValidationError,
    parse_coordinator_output,
    parse_explanation,
    parse_qa_output,
    parse_summary_output,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (GenerationStatus.PENDING.value, GenerationStatus.PROCESSING.value)
RESTART_ERROR = (
    "The server restarted before this generation finished, so it was stopped. "
    "Please submit the topic again."
)


# ---------------------------------------------------------------------------
# Database helpers (used by the API routes)
# ---------------------------------------------------------------------------

def create_generation(db: Session, topic: str) -> Generation:
    generation = Generation(topic=topic, status=GenerationStatus.PENDING.value)
    db.add(generation)
    db.commit()
    db.refresh(generation)
    return generation


def get_generation(db: Session, generation_id: str) -> Generation | None:
    return db.get(Generation, generation_id)


def list_generations(db: Session, limit: int = 20) -> list[Generation]:
    statement = select(Generation).order_by(Generation.created_at.desc()).limit(limit)
    return list(db.scalars(statement))


def count_active_generations(db: Session) -> int:
    statement = select(func.count()).select_from(Generation).where(Generation.status.in_(ACTIVE_STATUSES))
    return db.scalar(statement) or 0


def fail_interrupted_generations(db: Session) -> int:
    """Mark jobs left 'pending'/'processing' by a previous server run as failed.

    Background tasks live in the server's memory. If the server stops, those
    jobs are gone, so their rows would otherwise say "processing" forever.
    """
    statement = (
        update(Generation)
        .where(Generation.status.in_(ACTIVE_STATUSES))
        .values(status=GenerationStatus.FAILED.value, error_message=RESTART_ERROR, completed_at=utc_now())
    )
    result = db.execute(statement)
    db.commit()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# The background job
# ---------------------------------------------------------------------------

def _set_completed_steps(generation_id: str, steps: int) -> None:
    """Called by the CrewAI task callback after each agent finishes."""
    with database.SessionLocal() as db:
        db.execute(
            update(Generation)
            .where(Generation.id == generation_id)
            .values(completed_steps=max(0, min(steps, 4)))
        )
        db.commit()


def _mark_failed(generation_id: str, message: str) -> None:
    with database.SessionLocal() as db:
        generation = db.get(Generation, generation_id)
        if generation is None:
            return
        generation.status = GenerationStatus.FAILED.value
        generation.error_message = message
        generation.completed_at = utc_now()
        db.commit()


def run_generation(generation_id: str) -> None:
    """Run the four agents for one generation and save the outcome.

    FastAPI runs this AFTER the HTTP response has been sent (BackgroundTasks),
    in a worker thread. It opens its own database session because the
    request's session is already closed by then.
    """
    with database.SessionLocal() as db:
        generation = db.get(Generation, generation_id)
        if generation is None:
            logger.warning("Generation %s disappeared before it could start", generation_id)
            return
        generation.status = GenerationStatus.PROCESSING.value
        generation.started_at = utc_now()
        db.commit()
        topic = generation.topic

    try:
        raw = run_learning_crew(topic, on_task_complete=lambda n: _set_completed_steps(generation_id, n))

        coordinator = parse_coordinator_output(raw.coordinator)
        explanation = parse_explanation(raw.explanation)
        qa_pairs = parse_qa_output(raw.qa, coordinator.questions)
        summary_points = parse_summary_output(raw.summary)

        finished_at = utc_now()
        markdown = build_learning_notes(
            topic=topic,
            teaching_plan=coordinator.teaching_plan,
            explanation=explanation.text,
            qa_pairs=qa_pairs,
            summary_points=summary_points,
            generated_at=finished_at,
        )
    except LLMNotConfiguredError:
        _mark_failed(generation_id, "GROQ_API_KEY is not configured on the server.")
        return
    except CrewExecutionError as error:
        _mark_failed(generation_id, f"The AI agents could not finish: {error}")
        return
    except OutputValidationError as error:
        _mark_failed(generation_id, f"The agents' output did not pass validation: {error} Please try again.")
        return
    except Exception:  # last line of defence: log details, show a generic message
        logger.exception("Unexpected error while running generation %s", generation_id)
        _mark_failed(generation_id, "An unexpected server error occurred. Please try again.")
        return

    with database.SessionLocal() as db:
        generation = db.get(Generation, generation_id)
        if generation is None:
            return
        generation.status = GenerationStatus.COMPLETED.value
        generation.completed_steps = 4
        generation.teaching_plan = coordinator.teaching_plan
        generation.explanation = explanation.text
        generation.qa_pairs = qa_pairs
        generation.summary_points = summary_points
        generation.markdown = markdown
        generation.warnings = explanation.warnings
        generation.error_message = None
        generation.completed_at = finished_at
        db.commit()
    logger.info("Generation %s completed", generation_id)
