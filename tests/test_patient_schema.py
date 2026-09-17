"""Covers the field rules: 1-50 chars, alphabetic + hyphens/apostrophes, MM/DD/YYYY, not future."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.Schemas.Patient import PatientCreate

VALID = {
    "first_name": "Maria",
    "last_name": "O'Brien",
    "date_of_birth": "03/15/1985",
    "sex": "Female",
    "phone_number": "6626701017",
}


def make(**overrides) -> PatientCreate:
    return PatientCreate(**{**VALID, **overrides})


def test_accepts_a_valid_payload():
    patient = make()
    assert patient.first_name == "Maria"
    assert patient.date_of_birth == date(1985, 3, 15)


@pytest.mark.parametrize("name", ["Anne-Marie", "O'Brien", "Jo", "X", "a" * 50])
def test_accepts_letters_hyphens_and_apostrophes(name):
    assert make(first_name=name).first_name == name


@pytest.mark.parametrize(
    "name",
    [
        "",             # below the 1 char minimum
        "a" * 51,       # above the 50 char maximum
        "John3",        # digits
        "John Smith",   # space
        "John_Smith",   # underscore
        "-John",        # leading separator
        "John-",        # trailing separator
        "Mary--Jane",   # consecutive separators
    ],
)
def test_rejects_names_outside_the_rules(name):
    with pytest.raises(ValidationError):
        make(first_name=name)


def test_trims_surrounding_whitespace():
    assert make(first_name="  Maria  ").first_name == "Maria"


@pytest.mark.parametrize(
    "value",
    [
        "1985-03-15",   # ISO, not the specified format
        "15/03/1985",   # DD/MM/YYYY
        "13/01/1985",   # month 13
        "02/30/1985",   # day does not exist
        "3/15/85",      # unpadded, two digit year
        "not-a-date",
    ],
)
def test_rejects_dates_that_are_not_valid_mm_dd_yyyy(value):
    with pytest.raises(ValidationError):
        make(date_of_birth=value)


def test_rejects_a_future_date_of_birth():
    tomorrow = (date.today() + timedelta(days=1)).strftime("%m/%d/%Y")
    with pytest.raises(ValidationError):
        make(date_of_birth=tomorrow)


def test_accepts_today_as_date_of_birth():
    today = date.today()
    assert make(date_of_birth=today.strftime("%m/%d/%Y")).date_of_birth == today


@pytest.mark.parametrize(
    "field", ["first_name", "last_name", "date_of_birth", "sex", "phone_number"]
)
def test_every_required_field_is_required(field):
    payload = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(ValidationError):
        PatientCreate(**payload)


# --- sex ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["Male", "Female", "Other", "Decline to Answer"])
def test_accepts_the_four_sex_values(value):
    assert make(sex=value).sex.value == value


@pytest.mark.parametrize("value", ["male", "F", "Unknown", "", "Prefer not to say"])
def test_rejects_any_other_sex_value(value):
    with pytest.raises(ValidationError):
        make(sex=value)


# --- phone_number ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["6626701017", "(662) 670-1017", "662-670-1017", "662.670.1017", "+1 662 670 1017", "1-662-670-1017"],
)
def test_accepts_and_normalises_us_phone_formats(value):
    assert make(phone_number=value).phone_number == "6626701017"


@pytest.mark.parametrize(
    "value",
    [
        "123456789",     # 9 digits
        "66267010177",   # 11 digits, no leading 1
        "0626701017",    # area code starts 0
        "1626701017",    # area code starts 1
        "6620701017",    # exchange starts 0
        "6621701017",    # exchange starts 1
        "+44 20 7946 0958",
        "not-a-number",
        "",
    ],
)
def test_rejects_invalid_us_phone_numbers(value):
    with pytest.raises(ValidationError):
        make(phone_number=value)


# --- email ----------------------------------------------------------------


def test_email_is_optional():
    assert make().email is None
    payload = {k: v for k, v in VALID.items()}
    assert PatientCreate(**payload).email is None


@pytest.mark.parametrize("value", ["maria@example.com", "m.o-brien+tag@sub.example.co.uk"])
def test_accepts_valid_emails(value):
    assert make(email=value).email == value


@pytest.mark.parametrize("value", ["not-an-email", "a@b", "@example.com", "maria@", "a b@example.com"])
def test_rejects_malformed_emails(value):
    with pytest.raises(ValidationError):
        make(email=value)


def test_blank_email_becomes_none():
    """A voice agent with no email sends "" rather than omitting the key."""
    assert make(email="").email is None
    assert make(email="   ").email is None
