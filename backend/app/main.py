"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.routers import registration
from backend.app.services.google_sheets import GoogleSheetsError, ensure_headers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ensure .env edits are picked up after process start/reload
    get_settings.cache_clear()
    settings = get_settings()
    logger.info("Starting %s", settings.app_name)
    logger.info(
        "[diag] startup cloudinary_configured=%s email_configured=%s",
        settings.cloudinary_configured,
        settings.email_configured,
    )
    try:
        ensure_headers(settings)
        logger.info("Google Sheet headers verified")
    except GoogleSheetsError as exc:
        # Allow the app to boot; registration will surface a clear error
        logger.warning("Could not verify Google Sheet on startup: %s", exc)
    yield
    logger.info("Shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: dict[str, str] = {}
        for err in exc.errors():
            loc = err.get("loc", ())
            field = str(loc[-1]) if loc else "form"
            if field in {"body", "__root__"}:
                field = "form"
            message = err.get("msg", "Invalid value")
            if message.startswith("Value error, "):
                message = message.replace("Value error, ", "", 1)
            errors[field] = message
        return JSONResponse(
            status_code=422,
            content={"success": False, "message": "Validation failed", "errors": errors},
        )

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(registration.router, prefix="/api")
    # Also expose POST /register at root as specified
    app.include_router(registration.router)

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
