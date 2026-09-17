"""Covers the opt-in intake extras and UTC timestamp handling."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.Schemas.Patient import PatientCreate, PatientRead, PatientUpdate

REQUIRED = {
    "first_name": "Maria",
    "last_name": "O'Brien",
    "date_of_birth": "03/15/1985",
    "sex": "Female",
    "phone_number": "6626701017",
}

OPTIONAL_FIELDS = [
    "insurance_provider",
    "insurance_member_id",
    "emergency_contact_name",
    "emergency_contact_phone",
    "preferred_language",
]


def make(**overrides) -> PatientCreate:
    return PatientCreate(**{**REQUIRED, **overrides})


def test_all_extras_default_to_none_when_caller_opts_out():
    patient = make()
    assert all(getattr(patient, field) is None for field in OPTIONAL_FIELDS)


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_each_extra_is_independently_optional(field):
    """A caller may opt into one item without the others."""
    values = {
        "insurance_provider": "Aetna",
        "insurance_member_id": "XYZ123456789",
        "emergency_contact_name": "John O'Brien",
        "emergency_contact_phone": "6175551234",
        "preferred_language": "Spanish",
    }
    patient = make(**{field: values[field]})
    assert getattr(patient, field) is not None
    assert all(getattr(patient, other) is None for other in OPTIONAL_FIELDS if other != field)


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_blank_extras_become_none(field):
    """The agent sends "" for anything it did not collect."""
    assert getattr(make(**{field: ""}), field) is None
    assert getattr(make(**{field: "   "}), field) is None


# --- insurance ------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["Aetna", "Blue Cross Blue Shield", "UnitedHealthcare", "Kaiser Permanente", "AARP/UHC"]
)
def test_accepts_real_insurance_provider_names(value):
    assert make(insurance_provider=value).insurance_provider == value


@pytest.mark.parametrize("value", ["ABC123456", "XYZ123456789", "W1234567890"])
def test_accepts_alphanumeric_member_ids(value):
    assert make(insurance_member_id=value).insurance_member_id == value


@pytest.mark.parametrize("value", ["ABC-123-456", "ABC 123", "ABC_123", "ABC#123"])
def test_rejects_non_alphanumeric_member_ids(value):
    with pytest.raises(ValidationError):
        make(insurance_member_id=value)


# --- emergency contact ----------------------------------------------------


@pytest.mark.parametrize("value", ["John Smith", "Mary-Jane O'Brien", "Jean Claude Van Damme"])
def test_emergency_contact_name_allows_spaces(value):
    """Unlike first_name/last_name, this is one whole name."""
    assert make(emergency_contact_name=value).emergency_contact_name == value


@pytest.mark.parametrize("value", ["John Smith3", "John  Smith", "John.", "-John", "John Smith-"])
def test_rejects_malformed_emergency_contact_names(value):
    with pytest.raises(ValidationError):
        make(emergency_contact_name=value)


def test_emergency_contact_name_is_trimmed():
    assert make(emergency_contact_name="  John Smith  ").emergency_contact_name == "John Smith"


@pytest.mark.parametrize(
    "value", ["6175551234", "(617) 555-1234", "+1 617-555-1234"]
)
def test_emergency_phone_is_normalised(value):
    assert make(emergency_contact_phone=value).emergency_contact_phone == "6175551234"


@pytest.mark.parametrize("value", ["123", "0175551234", "1175551234", "not-a-phone"])
def test_rejects_invalid_emergency_phone(value):
    with pytest.raises(ValidationError):
        make(emergency_contact_phone=value)


# --- preferred language ---------------------------------------------------


@pytest.mark.parametrize("value", ["Spanish", "Haitian Creole", "Serbo-Croatian"])
def test_accepts_language_names(value):
    assert make(preferred_language=value).preferred_language == value


@pytest.mark.parametrize("value", ["Spanish1", "Espa\u00f1ol!", "123"])
def test_rejects_malformed_languages(value):
    with pytest.raises(ValidationError):
        make(preferred_language=value)


# --- extras on PUT --------------------------------------------------------


def test_extras_can_be_added_later_via_update():
    update = PatientUpdate(insurance_provider="Cigna", insurance_member_id="AB123456")
    assert update.changes() == {
        "insurance_provider": "Cigna",
        "insurance_member_id": "AB123456",
    }


def test_update_validates_extras():
    with pytest.raises(ValidationError):
        PatientUpdate(insurance_member_id="ABC-123")
    with pytest.raises(ValidationError):
        PatientUpdate(emergency_contact_phone="123")


# --- UTC timestamps -------------------------------------------------------


def _read(created, updated, deleted=None) -> dict:
    return PatientRead(
        patient_id=uuid.uuid4(),
        first_name="A",
        last_name="B",
        date_of_birth=date(1990, 1, 1),
        sex="Male",
        phone_number="6626701017",
        email=None,
        created_at=created,
        updated_at=updated,
        deleted_at=deleted,
    ).model_dump()


def test_timestamps_are_emitted_as_utc_with_z():
    aware = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
    dumped = _read(aware, aware)
    assert dumped["created_at"] == "2026-09-17T16:00:00Z"
    assert dumped["updated_at"] == "2026-09-17T16:00:00Z"


def test_non_utc_timestamps_are_converted_not_relabelled():
    """A +05:00 instant must shift to the equivalent UTC time, not keep its clock face."""
    plus_five = datetime(2026, 9, 17, 21, 0, tzinfo=timezone(timedelta(hours=5)))
    assert _read(plus_five, plus_five)["created_at"] == "2026-09-17T16:00:00Z"


def test_naive_timestamps_are_assumed_utc():
    naive = datetime(2026, 9, 17, 16, 0)
    assert _read(naive, naive)["created_at"] == "2026-09-17T16:00:00Z"


def test_null_deleted_at_stays_null():
    aware = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
    assert _read(aware, aware)["deleted_at"] is None
    assert _read(aware, aware, aware)["deleted_at"] == "2026-09-17T16:00:00Z"
