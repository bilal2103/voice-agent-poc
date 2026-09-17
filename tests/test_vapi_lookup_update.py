"""Covers the returning-caller flow: phone lookup, then update instead of create."""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_vapi_service
from app.main import app
from app.Models.Patient import Patient, Sex
from app.Services.PatientService import DuplicatePatientError, PatientNotFoundError
from app.Services.VapiService import VapiService

WEBHOOK = "/api/v1/vapi/webhook"


def make_patient(first="Maria", last="O'Brien", phone="6626701017", **kw) -> Patient:
    return Patient(
        patient_id=kw.get("patient_id", uuid.uuid4()),
        first_name=first,
        last_name=last,
        date_of_birth=kw.get("dob", date(1985, 3, 15)),
        sex=Sex.FEMALE,
        phone_number=phone,
        email=None,
    )


class FakePatientService:
    def __init__(self) -> None:
        self.by_phone: list[Patient] = []
        self.updated: list[tuple] = []
        self.raise_not_found = False
        self.raise_duplicate = False

    async def find_by_phone_and_dob(self, phone_number, date_of_birth):
        return [
            p
            for p in self.by_phone
            if p.phone_number == phone_number and p.date_of_birth == date_of_birth
        ]

    async def update(self, patient_id, payload):
        if self.raise_not_found:
            raise PatientNotFoundError(patient_id)
        if self.raise_duplicate:
            raise DuplicatePatientError
        self.updated.append((patient_id, payload.changes()))
        patient = next(p for p in self.by_phone if p.patient_id == patient_id)
        for field, value in payload.changes().items():
            setattr(patient, field, value)
        return patient


@pytest.fixture
def fake_service():
    return FakePatientService()


@pytest.fixture
def client(fake_service):
    app.dependency_overrides[get_vapi_service] = lambda: VapiService(get_settings(), fake_service)
    yield TestClient(app)
    app.dependency_overrides.clear()


def call_tool(client, tool, args, call_id="t1"):
    response = client.post(
        WEBHOOK,
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [{"id": call_id, "name": tool, "arguments": args}],
            }
        },
    )
    assert response.status_code == 200
    return response.json()["results"][0]["result"]


# --- lookup: phone alone is never enough ---------------------------------

DOB = "03/15/1985"


def lookup(client, phone="6626701017", dob=DOB):
    return call_tool(
        client, "lookup_patient", {"phone_number": phone, "date_of_birth": dob}
    )


def test_unknown_caller_is_treated_as_new(client):
    result = lookup(client)
    assert "No match" in result
    assert "new registration" in result


def test_matching_phone_and_dob_returns_the_exact_offer_line(client, fake_service):
    fake_service.by_phone = [make_patient()]
    result = lookup(client)

    assert (
        "It looks like we already have a record for Maria O'Brien. "
        "Would you like to update your information instead?"
    ) in result
    assert str(fake_service.by_phone[0].patient_id) in result


def test_right_phone_wrong_dob_reveals_nothing(client, fake_service):
    """The whole point of verification: a guessed date must not confirm a record."""
    fake_service.by_phone = [make_patient()]
    result = lookup(client, dob="01/01/1990")

    assert "No match" in result
    assert "Maria" not in result
    assert "O'Brien" not in result
    assert str(fake_service.by_phone[0].patient_id) not in result
    # And must not coach the agent into letting them guess again.
    assert "do not ask them to try another date of birth" in result.lower()


def test_right_dob_wrong_phone_reveals_nothing(client, fake_service):
    fake_service.by_phone = [make_patient()]
    result = lookup(client, phone="4155550123")
    assert "No match" in result
    assert "Maria" not in result


def test_lookup_normalises_the_number_before_matching(client, fake_service):
    fake_service.by_phone = [make_patient()]
    assert "already have a record" in lookup(client, phone="+1 (662) 670-1017")


def test_lookup_requires_a_usable_dob(client, fake_service):
    fake_service.by_phone = [make_patient()]
    for bad in ["1985-03-15", "not-a-date", "", "13/45/1985"]:
        result = lookup(client, dob=bad)
        assert "MM/DD/YYYY" in result
        assert "Maria" not in result


def test_lookup_without_a_dob_at_all_is_refused(client, fake_service):
    fake_service.by_phone = [make_patient()]
    result = call_tool(client, "lookup_patient", {"phone_number": "6626701017"})
    assert "MM/DD/YYYY" in result
    assert "Maria" not in result


def test_unusable_number_asks_the_caller_to_repeat(client):
    result = lookup(client, phone="12345")
    assert "10-digit US number" in result


def test_twins_on_one_line_are_disambiguated_by_first_name(client, fake_service):
    fake_service.by_phone = [
        make_patient(first="Maria", last="O'Brien"),
        make_patient(first="Declan", last="O'Brien"),
    ]
    result = lookup(client)

    assert "2 verified patients" in result
    assert "Maria" in result and "Declan" in result


# --- update ---------------------------------------------------------------


def test_update_applies_only_the_named_fields(client, fake_service):
    patient = make_patient()
    fake_service.by_phone = [patient]

    result = call_tool(
        client,
        "update_patient",
        {"patient_id": str(patient.patient_id), "email": "maria@example.com"},
    )

    assert "Record updated" in result
    # The agent must offer another change rather than signing off here.
    assert "anything else they would like to change" in result
    assert "Do not end the call" in result
    assert fake_service.updated == [(patient.patient_id, {"email": "maria@example.com"})]


def test_a_second_update_in_the_same_call_works(client, fake_service):
    """Callers often remember a second change once the first lands."""
    patient = make_patient()
    fake_service.by_phone = [patient]

    call_tool(client, "update_patient", {"patient_id": str(patient.patient_id), "email": "a@example.com"})
    call_tool(
        client,
        "update_patient",
        {"patient_id": str(patient.patient_id), "preferred_language": "Spanish"},
        call_id="t2",
    )

    assert [changes for _, changes in fake_service.updated] == [
        {"email": "a@example.com"},
        {"preferred_language": "Spanish"},
    ]


def test_update_normalises_a_new_phone_number(client, fake_service):
    patient = make_patient()
    fake_service.by_phone = [patient]

    call_tool(
        client,
        "update_patient",
        {"patient_id": str(patient.patient_id), "phone_number": "(415) 555-0123"},
    )
    assert fake_service.updated[0][1] == {"phone_number": "4155550123"}


def test_update_without_a_patient_id_tells_the_agent_to_look_up_first(client):
    result = call_tool(client, "update_patient", {"email": "x@example.com"})
    assert "lookup_patient" in result


def test_update_with_a_malformed_patient_id_is_refused(client):
    result = call_tool(client, "update_patient", {"patient_id": "not-a-uuid", "email": "x@example.com"})
    assert "valid patient_id" in result


def test_update_with_no_changes_prompts_the_agent(client, fake_service):
    patient = make_patient()
    fake_service.by_phone = [patient]
    result = call_tool(client, "update_patient", {"patient_id": str(patient.patient_id)})
    assert "No changes were supplied" in result


def test_update_validates_fields(client, fake_service):
    patient = make_patient()
    fake_service.by_phone = [patient]
    result = call_tool(
        client, "update_patient", {"patient_id": str(patient.patient_id), "first_name": "M4ria"}
    )
    assert "Re-prompt the caller for these fields only: first_name" in result
    assert fake_service.updated == []


def test_update_of_a_deleted_record_offers_new_registration(client, fake_service):
    fake_service.raise_not_found = True
    result = call_tool(
        client, "update_patient", {"patient_id": str(uuid.uuid4()), "email": "x@example.com"}
    )
    assert "no longer exists" in result


def test_update_that_would_collide_does_not_retry(client, fake_service):
    patient = make_patient()
    fake_service.by_phone = [patient]
    fake_service.raise_duplicate = True
    result = call_tool(
        client, "update_patient", {"patient_id": str(patient.patient_id), "last_name": "Smith"}
    )
    assert "Do not retry" in result
