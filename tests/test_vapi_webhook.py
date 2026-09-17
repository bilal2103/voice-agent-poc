"""Covers the Vapi webhook: auth, assistant-request, and every tool-call payload shape."""

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_vapi_service
from app.main import app
from app.Models.Patient import Patient
from app.Services.PatientService import DuplicatePatientError
from app.Services.VapiService import VapiService

WEBHOOK = "/api/v1/vapi/webhook"


class FakePatientService:
    """Stands in for the DB-backed service; records what the agent tried to save."""

    def __init__(self) -> None:
        self.created: list = []
        self.raise_duplicate = False

    async def create(self, payload):
        if self.raise_duplicate:
            raise DuplicatePatientError
        self.created.append(payload)
        return Patient(
            patient_id=uuid.uuid4(),
            first_name=payload.first_name,
            last_name=payload.last_name,
            date_of_birth=payload.date_of_birth,
            sex=payload.sex,
            phone_number=payload.phone_number,
            email=payload.email,
        )


@pytest.fixture
def fake_service():
    return FakePatientService()


@pytest.fixture
def client(fake_service):
    app.dependency_overrides[get_vapi_service] = lambda: VapiService(
        get_settings(), fake_service
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client, message):
    return client.post(WEBHOOK, json={"message": message})


def tool_result(response):
    return response.json()["results"][0]


# --- assistant-request ----------------------------------------------------


def test_assistant_request_returns_assistant_with_create_patient_tool(client):
    response = post(client, {"type": "assistant-request", "call": {"id": "call_1"}})
    assert response.status_code == 200

    assistant = response.json()["assistant"]
    assert assistant["firstMessage"]
    tools = assistant["model"]["tools"]
    assert [t.get("function", {}).get("name") or t["type"] for t in tools] == [
        "lookup_patient",
        "create_patient",
        "update_patient",
        "save_address",
        "endCall",
    ]

    params = next(
        t for t in tools if t["function"]["name"] == "create_patient"
    )["function"]["parameters"]
    assert set(params["required"]) == {
        "first_name",
        "last_name",
        "date_of_birth",
        "sex",
        "phone_number",
    }
    # Email is offered but never demanded.
    assert "email" in params["properties"]
    assert "email" not in params["required"]
    assert params["properties"]["sex"]["enum"] == ["Male", "Female", "Other", "Decline to Answer"]
    assert all(
        t["server"]["url"].endswith("/api/v1/vapi/webhook")
        for t in tools
        if t.get("type") == "function"
    )


# --- tool-calls, across the payload shapes Vapi's docs disagree on ---------

ARGS = {
    "first_name": "Maria",
    "last_name": "O'Brien",
    "date_of_birth": "03/15/1985",
    "sex": "Female",
    "phone_number": "6626701017",
}


@pytest.mark.parametrize(
    "tool_call",
    [
        pytest.param({"id": "t1", "name": "create_patient", "arguments": ARGS}, id="flat-arguments"),
        pytest.param({"id": "t1", "name": "create_patient", "parameters": ARGS}, id="flat-parameters"),
        pytest.param(
            {"id": "t1", "function": {"name": "create_patient", "arguments": ARGS}},
            id="nested-function",
        ),
        pytest.param(
            {"id": "t1", "function": {"name": "create_patient", "arguments": json.dumps(ARGS)}},
            id="nested-function-json-string",
        ),
    ],
)
def test_create_patient_accepts_every_tool_call_shape(client, fake_service, tool_call):
    response = post(client, {"type": "tool-calls", "toolCallList": [tool_call]})
    assert response.status_code == 200

    result = tool_result(response)
    assert result["toolCallId"] == "t1"
    assert "registered successfully" in result["result"]

    assert len(fake_service.created) == 1
    saved = fake_service.created[0]
    assert saved.first_name == "Maria"
    assert saved.date_of_birth == date(1985, 3, 15)


def test_create_patient_reads_the_nested_tool_with_tool_call_list(client, fake_service):
    response = post(
        client,
        {
            "type": "tool-calls",
            "toolWithToolCallList": [
                {"name": "create_patient", "toolCall": {"id": "t9", "arguments": ARGS}}
            ],
        },
    )
    assert tool_result(response)["toolCallId"] == "t9"
    assert len(fake_service.created) == 1


# --- failure paths the agent has to recover from --------------------------


def test_invalid_arguments_return_a_spoken_reason_not_an_error(client, fake_service):
    response = post(
        client,
        {
            "type": "tool-calls",
            "toolCallList": [
                {"id": "t2", "name": "create_patient", "arguments": {**ARGS, "first_name": "M4ria"}}
            ],
        },
    )
    assert response.status_code == 200

    result = tool_result(response)["result"]
    # Names the one bad field so the agent re-prompts for it alone.
    assert "Re-prompt the caller for these fields only: first_name" in result
    assert "do not start over" in result
    assert fake_service.created == []


def test_future_date_of_birth_is_refused(client, fake_service):
    response = post(
        client,
        {
            "type": "tool-calls",
            "toolCallList": [
                {"id": "t3", "name": "create_patient", "arguments": {**ARGS, "date_of_birth": "01/01/2099"}}
            ],
        },
    )
    result = tool_result(response)["result"]
    assert "Re-prompt the caller for these fields only: date_of_birth" in result
    assert "cannot be in the future" in result
    assert fake_service.created == []


def test_duplicate_patient_tells_the_agent_not_to_retry(client, fake_service):
    fake_service.raise_duplicate = True
    response = post(
        client, {"type": "tool-calls", "toolCallList": [{"id": "t4", "name": "create_patient", "arguments": ARGS}]}
    )
    assert "already registered" in tool_result(response)["result"]


def test_unknown_tool_does_not_crash_the_call(client):
    response = post(
        client, {"type": "tool-calls", "toolCallList": [{"id": "t5", "name": "delete_everything"}]}
    )
    assert response.status_code == 200
    assert "Unknown tool" in tool_result(response)["result"]


# --- informational events -------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"type": "status-update", "status": "ended", "call": {"id": "c1"}},
        {"type": "end-of-call-report", "endedReason": "hangup", "call": {"id": "c1"}},
        {"type": "transcript", "call": {"id": "c1"}},
    ],
)
def test_informational_events_are_acknowledged(client, message):
    response = post(client, message)
    assert response.status_code == 200
    assert response.json() == {}


def test_malformed_payload_is_rejected(client):
    assert client.post(WEBHOOK, json={"not_a_message": True}).status_code == 400


# --- webhook authentication ----------------------------------------------


@pytest.fixture
def secured_settings(monkeypatch):
    """Rebuild Settings with a secret set, bypassing the lru_cache."""
    monkeypatch.setenv("VAPI_SECRET", "s3cret-token")
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_webhook_rejects_a_missing_or_wrong_secret(client, secured_settings):
    assert post(client, {"type": "status-update"}).status_code == 401

    response = client.post(
        WEBHOOK, json={"message": {"type": "status-update"}}, headers={"x-vapi-secret": "wrong"}
    )
    assert response.status_code == 401


def test_webhook_accepts_the_configured_secret(client, secured_settings):
    response = client.post(
        WEBHOOK,
        json={"message": {"type": "status-update", "status": "ended"}},
        headers={"x-vapi-secret": "s3cret-token"},
    )
    assert response.status_code == 200


def test_webhook_refuses_to_run_open_outside_development(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    # Empty, not deleted: deleting would fall back to whatever `.env` holds.
    monkeypatch.setenv("VAPI_SECRET", "")
    get_settings.cache_clear()
    try:
        assert post(client, {"type": "status-update"}).status_code == 503
    finally:
        get_settings.cache_clear()
