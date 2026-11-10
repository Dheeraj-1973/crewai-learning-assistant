"""
Application entry point.

Start the server from the backend folder with:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from app.core.config import FRONTEND_DIR, MAX_REQUEST_BODY_BYTES, get_settings

import litellm  # noqa: F401

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import generations, system
from app.database import database
from app.services.generation_service import fail_interrupted_generations


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("app")


FRONTEND_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()

    with database.SessionLocal() as db:
        interrupted = fail_interrupted_generations(db)

    if interrupted:
        logger.warning(
            "Marked %d interrupted generation(s) as failed after restart",
            interrupted
        )

    if not get_settings().llm_configured:
        logger.warning(
            "GROQ_API_KEY is not set: the API will run, but generations are disabled."
        )

    yield


def _friendly_validation_errors(exc: RequestValidationError) -> list[dict]:
    errors = []

    for error in exc.errors():
        location = [
            str(part)
            for part in error.get("loc", [])
            if part != "body"
        ]

        message = str(
            error.get("msg", "Invalid value")
        ).removeprefix("Value error, ")

        if error.get("type") == "json_invalid":
            message = "The request body is not valid JSON."
            location = []

        errors.append({
            "field": ".".join(location) or "body",
            "message": message
        })

    return errors


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Four CrewAI agents turn any technical topic "
            "into beginner-friendly learning notes."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url="/redoc" if settings.enable_api_docs else None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def limit_body_size_and_add_headers(request: Request, call_next):
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                too_large = int(content_length) > MAX_REQUEST_BODY_BYTES
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."}
                )

            if too_large:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large "
                            f"(limit {MAX_REQUEST_BODY_BYTES} bytes)."
                        )
                    },
                )

        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")

        if request.url.path.startswith("/app"):
            response.headers.setdefault(
                "Content-Security-Policy",
                FRONTEND_CSP
            )

        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError
    ):
        errors = _friendly_validation_errors(exc)

        first = errors[0] if errors else {
            "field": "body",
            "message": "Invalid request."
        }

        return JSONResponse(
            status_code=422,
            content={
                "detail": f"{first['field']}: {first['message']}",
                "errors": errors
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception
    ):
        logger.exception(
            "Unhandled error on %s %s",
            request.method,
            request.url.path,
            exc_info=exc
        )

        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."}
        )

    app.include_router(system.router)
    app.include_router(generations.router)

    if settings.serve_frontend and FRONTEND_DIR.is_dir():
        app.mount(
            "/app",
            StaticFiles(directory=FRONTEND_DIR, html=True),
            name="frontend"
        )

    return app


app = create_app()