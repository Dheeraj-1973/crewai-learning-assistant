"""
System endpoints: a welcome message and a health check.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.database import get_db
from app.schemas.generation import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/", summary="API welcome information")
def home(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "message": "Welcome! Submit a technical topic to POST /api/generations.",
        "frontend": "/app/" if settings.serve_frontend else None,
        "docs": "/docs" if settings.enable_api_docs else None,
        "health": "/health",
    }


@router.get("/health", response_model=HealthResponse, summary="Backend health check")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        database_status = "unavailable"

    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        database=database_status,
        llm_configured=settings.llm_configured,  # True/False only - never the key itself
        model=settings.llm_model,
        version=settings.app_version,
    )
