"""FastAPI application entrypoint."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.router import api_router
from app.config import get_settings
from app.error_handlers import register_error_handlers
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

#: <project root>/frontend — resolved from this file so the working directory
#: does not matter, in a container or out of it.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    # Mounted last, so /api/v1/*, /docs and /openapi.json are matched first.
    # html=True serves index.html for "/". Serving the page from the same origin
    # as the API means the browser makes no cross-origin requests at all.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    else:
        logger.warning("frontend directory not found at %s; serving API only", FRONTEND_DIR)

    return app


app = create_app()
