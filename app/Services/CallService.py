"""Business rules for call records: persist the transcript, then summarise it.

The transcript is committed before the LLM is ever called, so a provider outage
costs a summary, never the record of the call.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from app.LLM.base import LLMError
from app.LLM.CallSummarizer import CallSummarizer
from app.Models.Call import Call, SummaryStatus
from app.Repository.CallRepository import CallRepository

logger = logging.getLogger(__name__)

SUMMARY_ERROR_MAX_LENGTH = 500


class CallNotFoundError(Exception):
    def __init__(self, call_id: uuid.UUID) -> None:
        super().__init__(f"Call {call_id} was not found")
        self.call_id = call_id


class CallService:
    def __init__(self, repository: CallRepository, summarizer: CallSummarizer) -> None:
        self.repository = repository
        self.summarizer = summarizer

    async def link_patient(self, vapi_call_id: str, patient_id: uuid.UUID) -> None:
        """Records which patient a call created or updated, mid-call."""
        if not vapi_call_id:
            return
        await self.repository.upsert(vapi_call_id, patient_id=patient_id)
        await self.repository.session.commit()

    async def record_end_of_call(
        self,
        vapi_call_id: str,
        transcript: str | None = None,
        caller_number: str | None = None,
        ended_reason: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
    ) -> Call:
        """Stores everything the report carried and marks the summary pending."""
        has_transcript = bool(transcript and transcript.strip())
        status = SummaryStatus.PENDING if has_transcript else SummaryStatus.SKIPPED

        call = await self.repository.upsert(
            vapi_call_id,
            transcript=transcript,
            caller_number=caller_number,
            ended_reason=ended_reason,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            summary_status=status,
            summary_error=None if has_transcript else "No transcript on the call report",
        )
        await self.repository.session.commit()
        logger.info(
            "call recorded vapi_call_id=%s transcript_chars=%d status=%s",
            vapi_call_id,
            len(transcript or ""),
            status.value,
        )
        return call

    async def summarize(self, vapi_call_id: str) -> Call | None:
        """Summarises a stored transcript. Never raises for LLM problems."""
        call = await self.repository.get_by_vapi_id(vapi_call_id)
        if call is None:
            logger.warning("cannot summarise unknown call %s", vapi_call_id)
            return None

        if not call.transcript or not call.transcript.strip():
            call.summary_status = SummaryStatus.SKIPPED
            call.summary_error = "No transcript to summarise"
            await self.repository.session.commit()
            return call

        if not self.summarizer.is_available:
            call.summary_status = SummaryStatus.SKIPPED
            call.summary_error = "No LLM provider configured"
            await self.repository.session.commit()
            logger.info("summary skipped for %s: no provider configured", vapi_call_id)
            return call

        try:
            call.summary = await self.summarizer.summarize(call.transcript)
            call.summary_status = SummaryStatus.READY
            call.summary_error = None
            logger.info("call summarised vapi_call_id=%s", vapi_call_id)
        except LLMError as exc:
            # The transcript is already safely stored; a failed summary is
            # recorded as such and can be retried later.
            call.summary_status = SummaryStatus.FAILED
            call.summary_error = str(exc)[:SUMMARY_ERROR_MAX_LENGTH]
            logger.warning("summary failed for %s: %s", vapi_call_id, exc)
        except Exception as exc:  # noqa: BLE001 - a bug here must not lose the call
            call.summary_status = SummaryStatus.FAILED
            call.summary_error = f"Unexpected error: {exc}"[:SUMMARY_ERROR_MAX_LENGTH]
            logger.exception("unexpected error summarising %s", vapi_call_id)

        await self.repository.session.commit()
        return call

    async def get(self, call_id: uuid.UUID) -> Call:
        call = await self.repository.get_by_id(call_id)
        if call is None:
            raise CallNotFoundError(call_id)
        return call

    async def list(
        self, patient_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0
    ) -> Sequence[Call]:
        return await self.repository.list(patient_id=patient_id, limit=limit, offset=offset)


async def summarize_call_in_background(vapi_call_id: str) -> None:
    """Runs after the webhook has already responded.

    Opens its own session: the request-scoped one is closed by the time
    FastAPI drains background tasks.
    """
    # Imported here to keep this module free of a dependency cycle.
    from app.LLM.factory import get_call_summarizer
    from app.Repository.CallRepository import CallRepository as _CallRepository
    from app.Repository.database import SessionFactory

    async with SessionFactory() as session:
        try:
            service = CallService(_CallRepository(session), get_call_summarizer())
            await service.summarize(vapi_call_id)
        except Exception:  # noqa: BLE001 - nothing upstream can catch this
            await session.rollback()
            logger.exception("background summarisation crashed for %s", vapi_call_id)
