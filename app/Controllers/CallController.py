"""Read-only HTTP access to stored call transcripts and summaries."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import CallServiceDep
from app.Schemas.Call import CallRead, CallSummaryRead
from app.Schemas.Envelope import Envelope, ok
from app.Services.CallService import CallNotFoundError


class CallController:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/calls", tags=["calls"])
        self.router.add_api_route(
            "",
            self.list,
            methods=["GET"],
            response_model=Envelope[list[CallSummaryRead]],
            summary="List calls, newest first",
        )
        self.router.add_api_route(
            "/{call_id}",
            self.get,
            methods=["GET"],
            response_model=Envelope[CallRead],
            summary="Retrieve one call with its full transcript",
        )

    async def list(
        self,
        service: CallServiceDep,
        patient_id: uuid.UUID | None = Query(None, description="Only calls for this patient"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict:
        calls = await service.list(patient_id=patient_id, limit=limit, offset=offset)
        return ok([CallSummaryRead.model_validate(call) for call in calls])

    async def get(self, call_id: uuid.UUID, service: CallServiceDep) -> dict:
        try:
            call = await service.get(call_id)
        except CallNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return ok(CallRead.model_validate(call))
