"""Liveness and readiness endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.dependencies import DbSession


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


class HealthController:
    def __init__(self) -> None:
        self.router = APIRouter(tags=["health"])
        self.router.add_api_route(
            "/health",
            self.health,
            methods=["GET"],
            response_model=HealthResponse,
            summary="Liveness check",
        )
        self.router.add_api_route(
            "/health/ready",
            self.ready,
            methods=["GET"],
            response_model=ReadinessResponse,
            summary="Readiness check (verifies the database)",
        )

    async def health(self) -> HealthResponse:
        settings = get_settings()
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            version=settings.version,
            environment=settings.environment,
        )

    async def ready(self, session: DbSession) -> ReadinessResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - surfaced as a 503, detail is logged upstream
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "database unreachable"
            ) from exc
        return ReadinessResponse(status="ok", database="ok")
