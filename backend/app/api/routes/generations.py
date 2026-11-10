"""
REST endpoints for learning-material generations.

    POST /api/generations                       start a new generation (202 Accepted)
    GET  /api/generations                       history, newest first
    GET  /api/generations/{generation_id}       status + results of one generation
    GET  /api/generations/{generation_id}/download   the Markdown notes as a file
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.database import get_db
from app.database.models import Generation, GenerationStatus
from app.schemas.generation import (
    ErrorResponse,
    GenerationCreate,
    GenerationDetail,
    GenerationList,
    GenerationSummary,
    Progress,
)
from app.services import generation_service
from app.services.markdown_builder import make_download_filename

router = APIRouter(prefix="/api/generations", tags=["generations"])


def to_detail(generation: Generation) -> GenerationDetail:
    """Convert a database row into the API response model."""
    return GenerationDetail(
        id=generation.id,
        topic=generation.topic,
        status=generation.status,
        progress=Progress(completed_steps=generation.completed_steps or 0),
        created_at=generation.created_at,
        started_at=generation.started_at,
        completed_at=generation.completed_at,
        teaching_plan=generation.teaching_plan,
        explanation=generation.explanation,
        qa_pairs=generation.qa_pairs,
        summary_points=generation.summary_points,
        markdown=generation.markdown,
        warnings=generation.warnings or [],
        error_message=generation.error_message,
    )


def get_generation_or_404(db: Session, generation_id: str) -> Generation:
    generation = generation_service.get_generation(db, generation_id)
    if generation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    return generation


@router.post(
    "",
    response_model=GenerationDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a topic for generation",
    responses={
        422: {"model": ErrorResponse, "description": "Invalid topic or request body"},
        429: {"model": ErrorResponse, "description": "Too many generations running"},
        503: {"model": ErrorResponse, "description": "Groq API key not configured"},
    },
)
def submit_generation(
    payload: GenerationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GenerationDetail:
    if not settings.llm_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The server has no GROQ_API_KEY configured, so it cannot generate content.",
        )

    if generation_service.count_active_generations(db) >= settings.max_active_generations:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Other generations are still running. Please wait for them to finish and try again.",
        )

    generation = generation_service.create_generation(db, payload.topic)
    # Runs after the response is sent, so the browser gets the ID immediately.
    background_tasks.add_task(generation_service.run_generation, generation.id)
    return to_detail(generation)


@router.get("", response_model=GenerationList, summary="Retrieve generation history")
def list_history(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of items to return."),
    db: Session = Depends(get_db),
) -> GenerationList:
    rows = generation_service.list_generations(db, limit=limit)
    items = [GenerationSummary.model_validate(row) for row in rows]
    return GenerationList(items=items, count=len(items))


@router.get(
    "/{generation_id}",
    response_model=GenerationDetail,
    summary="Retrieve generation status and result",
    responses={404: {"model": ErrorResponse}},
)
def read_generation(generation_id: str, db: Session = Depends(get_db)) -> GenerationDetail:
    return to_detail(get_generation_or_404(db, generation_id))


@router.get(
    "/{generation_id}/download",
    summary="Download the learning notes as Markdown",
    response_class=Response,
    responses={
        200: {"content": {"text/markdown": {}}, "description": "The Markdown file"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Generation not completed yet"},
    },
)
def download_markdown(generation_id: str, db: Session = Depends(get_db)) -> Response:
    generation = get_generation_or_404(db, generation_id)
    if generation.status != GenerationStatus.COMPLETED.value or not generation.markdown:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This generation has not completed, so there is nothing to download yet.",
        )
    filename = make_download_filename(generation.topic)
    return Response(
        content=generation.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
