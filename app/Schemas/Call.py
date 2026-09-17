"""Response contracts for stored calls."""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_serializer

from app.Models.Call import SummaryStatus


def _as_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CallSummaryRead(BaseModel):
    """List view: metadata and summary, without the full transcript."""

    model_config = ConfigDict(from_attributes=True)

    call_id: uuid.UUID
    vapi_call_id: str
    caller_number: str | None
    patient_id: uuid.UUID | None
    ended_reason: str | None
    duration_seconds: int | None
    summary: str | None
    summary_status: SummaryStatus
    summary_error: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

    @field_serializer("started_at", "ended_at", "created_at")
    def _serialize_utc(self, value: datetime | None) -> str | None:
        return _as_utc(value)


class CallRead(CallSummaryRead):
    """Detail view: adds the transcript."""

    transcript: str | None
