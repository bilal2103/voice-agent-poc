"""Pins the functional requirements to the assistant config and tool behaviour.

These read as prose assertions on purpose: the requirements are about what the
agent is told to do, and a silent prompt edit would otherwise go unnoticed.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_vapi_service
from app.main import app
from app.Models.Patient import Patient, Sex
from app.Services.VapiAssistant import SYSTEM_PROMPT, build_assistant
from app.Services.VapiService import VapiService

WEBHOOK = "/api/v1/vapi/webhook"


@pytest.fixture
def assistant():
    return build_assistant(get_settings())


# --- Voice interaction: conversational, not an IVR menu -------------------


def test_prompt_forbids_ivr_style_interaction():
    assert "not a phone menu" in SYSTEM_PROMPT
    assert "press or say" in SYSTEM_PROMPT
    assert "human intake coordinator" in SYSTEM_PROMPT


def test_prompt_handles_varied_phrasing_and_corrections():
    assert "Understand varied phrasing" in SYSTEM_PROMPT
    assert "corrects themselves" in SYSTEM_PROMPT
    assert "clarifying question" in SYSTEM_PROMPT


def test_prompt_accepts_several_values_volunteered_at_once():
    assert "volunteer several things at once" in SYSTEM_PROMPT


# --- Confirmation: read everything back before saving --------------------


def test_prompt_requires_full_readback_before_saving():
    assert "CONFIRMATION, BEFORE YOU SAVE" in SYSTEM_PROMPT
    assert "Include every field you collected, including the optional ones." in SYSTEM_PROMPT
    assert "confirm or correct anything" in SYSTEM_PROMPT
    assert "Only once they agree, call create_patient." in SYSTEM_PROMPT


def test_prompt_reads_values_not_field_names():
    assert 'Say the values, not the field names' in SYSTEM_PROMPT


# --- Error handling: re-prompt for the offending field only --------------


class FakePatientService:
    def __init__(self):
        self.created = []

    async def create(self, payload):
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
def client():
    service = FakePatientService()
    app.dependency_overrides[get_vapi_service] = lambda: VapiService(get_settings(), service)
    client = TestClient(app)
    client.fake = service
    yield client
    app.dependency_overrides.clear()


def create_with(client, **overrides):
    args = {
        "first_name": "Maria",
        "last_name": "OBrien",
        "date_of_birth": "03/15/1985",
        "sex": "Female",
        "phone_number": "6626701017",
        **overrides,
    }
    response = client.post(
        WEBHOOK,
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [{"id": "t1", "name": "create_patient", "arguments": args}],
            }
        },
    )
    return response.json()["results"][0]["result"]


def test_three_digit_phone_reprompts_for_that_field_only(client):
    """The requirement's own example: a 3-digit phone number."""
    result = create_with(client, phone_number="123")

    assert "Re-prompt the caller for these fields only: phone_number" in result
    assert "first_name" not in result.split("Problem:")[0]
    assert "do not start over" in result
    assert client.fake.created == []


def test_future_date_of_birth_reprompts_for_that_field_only(client):
    """The requirement's other example: a future date of birth."""
    result = create_with(client, date_of_birth="01/01/2099")

    assert "Re-prompt the caller for these fields only: date_of_birth" in result
    assert "cannot be in the future" in result
    assert client.fake.created == []


def test_two_bad_fields_are_both_named(client):
    result = create_with(client, phone_number="123", date_of_birth="01/01/2099")
    named = result.split("Problem:")[0]
    assert "phone_number" in named and "date_of_birth" in named
    assert "last_name" not in named


def test_prompt_tells_the_agent_to_keep_the_other_values():
    assert "keep every other value you already collected" in SYSTEM_PROMPT
    assert "Never restart the call" in SYSTEM_PROMPT


def test_prompt_catches_bad_values_before_calling_the_tool():
    assert "a phone number that is not ten digits, a date of birth in the future" in SYSTEM_PROMPT


def test_prompt_gives_up_gracefully_after_repeated_failures():
    assert "fails a third time" in SYSTEM_PROMPT


def test_prompt_forbids_reading_raw_errors_aloud():
    assert "Never read the raw error text aloud" in SYSTEM_PROMPT


# --- Call completion: brief personalised sign-off, then hang up ----------


def test_assistant_can_end_the_call_itself(assistant):
    assert {"type": "endCall"} in assistant["model"]["tools"]


def test_no_fixed_end_message_would_talk_over_the_signoff(assistant):
    """A static endCallMessage cannot contain the caller's name, and would double up."""
    assert "endCallMessage" not in assistant


def test_prompt_requires_a_personalised_signoff_then_hangup():
    assert "ENDING THE CALL" in SYSTEM_PROMPT
    assert "You're all set, Maria. Thanks for calling." in SYSTEM_PROMPT
    assert "end the call with the endCall tool" in SYSTEM_PROMPT
    assert "Do not list their details again." in SYSTEM_PROMPT


def test_prompt_ends_when_the_caller_says_goodbye():
    assert "If the caller says goodbye" in SYSTEM_PROMPT
    assert "Do not keep the line open" in SYSTEM_PROMPT


def test_caller_goodbye_phrases_are_configured(assistant):
    assert "goodbye" in assistant["endCallPhrases"]


def test_successful_create_gives_the_agent_the_first_name_to_say_back(client):
    """The sign-off needs the name, so the tool result must carry it."""
    result = create_with(client)
    assert "Maria" in result


# --- Update: never hang up after a single change -------------------------


def test_prompt_asks_for_further_changes_after_each_update():
    assert "AFTER EACH SUCCESSFUL UPDATE, ask whether there is anything else" in SYSTEM_PROMPT
    assert "Is there anything else you'd like to change?" in SYSTEM_PROMPT
    assert "Repeat for as many changes as they want." in SYSTEM_PROMPT


def test_prompt_forbids_hanging_up_straight_after_an_update():
    assert "Never hang up straight after an update." in SYSTEM_PROMPT
    assert "One change is not a signal that they are finished" in SYSTEM_PROMPT


def test_ending_section_defers_to_the_update_loop():
    ending = SYSTEM_PROMPT.split("=== ENDING THE CALL ===")[1].split("===")[0]
    assert "do NOT end the call straight away" in ending
    assert "Only once the caller says there is nothing else" in ending


# --- Greeting and scope ---------------------------------------------------


def test_greeting_is_the_agreed_wording(assistant):
    assert assistant["firstMessage"] == "Hi there! Welcome to Bilal's Clinic. How can I help you today?"


def test_clinic_name_is_configurable(monkeypatch):
    from app.config import Settings
    from app.Services.VapiAssistant import build_assistant as build

    settings = Settings(clinic_name="Riverside Health")
    built = build(settings)
    assert built["firstMessage"] == "Hi there! Welcome to Riverside Health. How can I help you today?"
    assert "Riverside Health" in built["model"]["messages"][0]["content"]


def test_prompt_placeholder_is_always_rendered(assistant):
    assert "{clinic_name}" not in assistant["model"]["messages"][0]["content"]


def test_prompt_states_exactly_two_capabilities():
    assert "=== WHAT YOU CAN DO ===" in SYSTEM_PROMPT
    assert "1. Register a new patient" in SYSTEM_PROMPT
    assert "2. Update an existing patient's details" in SYSTEM_PROMPT
    assert "Nothing else." in SYSTEM_PROMPT


def test_open_greeting_routes_both_intents_to_the_same_verification():
    """The lookup decides new vs existing, so the agent must not ask up front."""
    assert 'Do not ask "are you a new or existing patient?"' in SYSTEM_PROMPT
    assert "go to VERIFY THE CALLER" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    "refused",
    ["appointments", "test or lab results", "symptoms, diagnoses, medicines", "billing"],
)
def test_out_of_scope_requests_are_named_explicitly(refused):
    section = SYSTEM_PROMPT.split("=== OUT OF SCOPE ===")[1].split("=== VERIFY")[0]
    assert refused in section


def test_agent_never_gives_medical_advice():
    assert "Never give medical advice of any kind" in SYSTEM_PROMPT
    assert "Never speculate about what a clinician would say" in SYSTEM_PROMPT


def test_emergencies_are_redirected_to_911_and_the_call_ends():
    assert 'If this is an emergency, please hang up and dial 911.' in SYSTEM_PROMPT
    assert "Do not continue with registration or an update." in SYSTEM_PROMPT


def test_out_of_scope_refusal_is_stated_once_not_repeatedly():
    assert "without apologising repeatedly" in SYSTEM_PROMPT
    assert "If they then want to register or update, carry on as normal." in SYSTEM_PROMPT


# --- webhook traffic ------------------------------------------------------


def test_assistant_only_subscribes_to_messages_the_server_handles(assistant):
    """Unsubscribed chatter (conversation-update, speech-update) is pure load.

    Left at the default, a four-minute call sent ~170 webhooks the service
    discards, which is enough to get real tool calls dropped in transit.
    """
    assert set(assistant["serverMessages"]) == {
        "tool-calls",
        "status-update",
        "end-of-call-report",
    }


def test_server_messages_only_uses_values_vapi_accepts(assistant):
    """Vapi rejects the whole assistant on an unknown value.

    "assistant-request" in particular is not valid here: it is how Vapi asks for
    this assistant, so it is configured on the phone number instead.
    """
    allowed = {
        "conversation-update",
        "end-of-call-report",
        "function-call",
        "hang",
        "speech-update",
        "status-update",
        "tool-calls",
        "transfer-destination-request",
        "user-interrupted",
    }
    assert set(assistant["serverMessages"]) <= allowed


def test_sex_options_are_never_read_aloud():
    """Listing the values invites the caller to pick "Decline to Answer"."""
    assert "Never read a list of options aloud" in SYSTEM_PROMPT
    assert 'never say the words "Decline to Answer" to the caller' in SYSTEM_PROMPT
    assert "Storing sex is separate from asking about it" in SYSTEM_PROMPT
    assert "The caller never hears these labels" in SYSTEM_PROMPT
