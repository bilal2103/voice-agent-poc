"""Covers storing a call's transcript and summarising it, without a database."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_vapi_service
from app.LLM.base import LLMError
from app.LLM.CallSummarizer import CallSummarizer
from app.main import app
from app.Models.Call import Call, SummaryStatus
from app.Services.CallService import CallService
from app.Services.VapiService import VapiService
from tests.test_llm_layer import RecordingClient

WEBHOOK = "/api/v1/vapi/webhook"
TRANSCRIPT = "AI: Welcome to the clinic.\nUser: I would like to register."


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class FakeCallRepository:
    def __init__(self):
        self.rows: dict[str, Call] = {}
        self.session = FakeSession()

    async def get_by_vapi_id(self, vapi_call_id):
        return self.rows.get(vapi_call_id)

    async def get_by_id(self, call_id):
        return next((c for c in self.rows.values() if c.call_id == call_id), None)

    async def upsert(self, vapi_call_id, **fields):
        call = self.rows.get(vapi_call_id)
        if call is None:
            call = Call(call_id=uuid.uuid4(), vapi_call_id=vapi_call_id)
            call.summary_status = SummaryStatus.PENDING
            self.rows[vapi_call_id] = call
        for field, value in fields.items():
            if value is not None:
                setattr(call, field, value)
        return call

    async def list(self, patient_id=None, limit=50, offset=0):
        return list(self.rows.values())


def build_service(reply="Maria registered.", available=True, error=None):
    repo = FakeCallRepository()
    client = RecordingClient(reply=reply, available=available, error=error)
    return CallService(repo, CallSummarizer(client)), repo, client


# --- storing --------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_is_stored_and_marked_pending():
    service, repo, _ = build_service()
    call = await service.record_end_of_call(
        "vapi-1", transcript=TRANSCRIPT, caller_number="+16626701017", ended_reason="hangup"
    )

    assert call.transcript == TRANSCRIPT
    assert call.summary_status == SummaryStatus.PENDING
    assert call.caller_number == "+16626701017"
    assert repo.session.commits == 1


@pytest.mark.asyncio
async def test_a_call_with_no_transcript_is_skipped_not_failed():
    service, _, client = build_service()
    call = await service.record_end_of_call("vapi-2", transcript=None)

    assert call.summary_status == SummaryStatus.SKIPPED
    assert call.summary is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_repeat_reports_update_one_row_rather_than_duplicating():
    service, repo, _ = build_service()
    await service.record_end_of_call("vapi-3", transcript=TRANSCRIPT, ended_reason="hangup")
    await service.record_end_of_call("vapi-3", transcript=TRANSCRIPT, ended_reason="hangup")

    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_linking_a_patient_does_not_clear_existing_fields():
    service, repo, _ = build_service()
    await service.record_end_of_call("vapi-4", transcript=TRANSCRIPT)
    patient_id = uuid.uuid4()
    await service.link_patient("vapi-4", patient_id)

    call = repo.rows["vapi-4"]
    assert call.patient_id == patient_id
    assert call.transcript == TRANSCRIPT


# --- summarising ----------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_is_stored_and_marked_ready():
    service, repo, _ = build_service(reply="Maria registered as a new patient.")
    await service.record_end_of_call("vapi-5", transcript=TRANSCRIPT)
    call = await service.summarize("vapi-5")

    assert call.summary == "Maria registered as a new patient."
    assert call.summary_status == SummaryStatus.READY
    assert call.summary_error is None


@pytest.mark.asyncio
async def test_an_llm_failure_keeps_the_transcript_and_records_why():
    """Losing a summary is acceptable; losing the transcript is not."""
    service, repo, _ = build_service(error=LLMError("OpenAI rate limit reached"))
    await service.record_end_of_call("vapi-6", transcript=TRANSCRIPT)
    call = await service.summarize("vapi-6")

    assert call.transcript == TRANSCRIPT
    assert call.summary is None
    assert call.summary_status == SummaryStatus.FAILED
    assert "rate limit" in call.summary_error


@pytest.mark.asyncio
async def test_an_unexpected_error_is_caught_too():
    service, _, _ = build_service(error=RuntimeError("boom"))
    await service.record_end_of_call("vapi-7", transcript=TRANSCRIPT)
    call = await service.summarize("vapi-7")

    assert call.summary_status == SummaryStatus.FAILED
    assert "Unexpected error" in call.summary_error


@pytest.mark.asyncio
async def test_without_a_provider_the_summary_is_skipped_not_failed():
    service, _, _ = build_service(available=False)
    await service.record_end_of_call("vapi-8", transcript=TRANSCRIPT)
    call = await service.summarize("vapi-8")

    assert call.summary_status == SummaryStatus.SKIPPED
    assert "No LLM provider configured" in call.summary_error


@pytest.mark.asyncio
async def test_summarising_an_unknown_call_is_a_no_op():
    service, _, _ = build_service()
    assert await service.summarize("never-seen") is None


# --- through the webhook --------------------------------------------------


@pytest.fixture
def client():
    service, repo, llm = build_service()

    class FakePatientService:
        pass

    async def summarize_task(vapi_call_id):
        await service.summarize(vapi_call_id)

    app.dependency_overrides[get_vapi_service] = lambda: VapiService(
        get_settings(), FakePatientService(), service, summarize_task=summarize_task
    )
    test_client = TestClient(app)
    test_client.repo = repo
    test_client.llm = llm
    yield test_client
    app.dependency_overrides.clear()


def test_end_of_call_report_stores_and_summarises(client):
    response = client.post(
        WEBHOOK,
        json={
            "message": {
                "type": "end-of-call-report",
                "endedReason": "customer-ended-call",
                "durationSeconds": 42.7,
                "startedAt": "2026-09-17T16:00:00.000Z",
                "endedAt": "2026-09-17T16:00:42.000Z",
                "call": {"id": "vapi-web-1", "customer": {"number": "+16626701017"}},
                "artifact": {"transcript": TRANSCRIPT},
            }
        },
    )
    assert response.status_code == 200

    call = client.repo.rows["vapi-web-1"]
    assert call.transcript == TRANSCRIPT
    assert call.caller_number == "+16626701017"
    assert call.ended_reason == "customer-ended-call"
    assert call.duration_seconds == 42
    assert call.started_at is not None and call.started_at.year == 2026
    # TestClient drains background tasks before the response returns.
    assert call.summary_status == SummaryStatus.READY


def test_report_without_a_call_id_is_ignored_not_an_error(client):
    response = client.post(
        WEBHOOK, json={"message": {"type": "end-of-call-report", "endedReason": "hangup"}}
    )
    assert response.status_code == 200
    assert client.repo.rows == {}


def test_report_with_no_transcript_never_calls_the_model(client):
    client.post(
        WEBHOOK,
        json={
            "message": {
                "type": "end-of-call-report",
                "call": {"id": "vapi-web-2"},
                "artifact": {},
            }
        },
    )
    assert client.repo.rows["vapi-web-2"].summary_status == SummaryStatus.SKIPPED
    assert client.llm.calls == []
