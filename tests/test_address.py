"""Covers address validation and the patient-then-address ordering."""

import pytest
from pydantic import ValidationError

from app.Schemas.Address import AddressCreate, AddressUpdate
from app.Services.VapiAssistant import SYSTEM_PROMPT

VALID = {
    "address_line_1": "120 Beacon Street",
    "city": "Boston",
    "state": "MA",
    "zip_code": "02116",
}


def make(**overrides) -> AddressCreate:
    return AddressCreate(**{**VALID, **overrides})


# --- required vs optional -------------------------------------------------


@pytest.mark.parametrize("field", ["address_line_1", "city", "state", "zip_code"])
def test_every_required_field_is_required(field):
    payload = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(ValidationError):
        AddressCreate(**payload)


def test_address_line_2_is_optional():
    assert make().address_line_2 is None
    assert make(address_line_2="Apt 4B").address_line_2 == "Apt 4B"


def test_blank_address_line_2_becomes_none():
    """The agent sends "" when the caller has no apartment number."""
    assert make(address_line_2="").address_line_2 is None
    assert make(address_line_2="   ").address_line_2 is None


# --- street lines ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["120 Beacon Street", "1 Main St.", "45-B Elm Road", "12 O'Connor Way", "3 Rue St. Denis", "#7 Park Lane"],
)
def test_accepts_real_street_addresses(value):
    assert make(address_line_1=value).address_line_1 == value


@pytest.mark.parametrize("value", ["", "   ", "@@@", "<script>"])
def test_rejects_unusable_street_addresses(value):
    with pytest.raises(ValidationError):
        make(address_line_1=value)


def test_street_address_is_trimmed():
    assert make(address_line_1="  120 Beacon Street  ").address_line_1 == "120 Beacon Street"


# --- city -----------------------------------------------------------------


@pytest.mark.parametrize("value", ["Boston", "New York", "Winston-Salem", "St. Louis", "Coeur d'Alene"])
def test_accepts_real_city_names(value):
    assert make(city=value).city == value


@pytest.mark.parametrize("value", ["Boston3", "", "12345"])
def test_rejects_malformed_city_names(value):
    with pytest.raises(ValidationError):
        make(city=value)


def test_city_respects_the_100_character_limit():
    assert make(city="a" * 100).city == "a" * 100
    with pytest.raises(ValidationError):
        make(city="a" * 101)


# --- state ----------------------------------------------------------------


@pytest.mark.parametrize("value", ["MA", "CA", "NY", "TX", "DC", "PR"])
def test_accepts_valid_state_abbreviations(value):
    assert make(state=value).state == value


@pytest.mark.parametrize("value", ["ma", "Ma", " ma "])
def test_state_is_normalised_to_uppercase(value):
    assert make(state=value).state == "MA"


@pytest.mark.parametrize("value", ["ZZ", "XX", "Massachusetts", "M", "MAS", "", "12"])
def test_rejects_anything_that_is_not_a_real_state_code(value):
    with pytest.raises(ValidationError):
        make(state=value)


# --- zip ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["02116", "90210", "10001"])
def test_accepts_five_digit_zips(value):
    assert make(zip_code=value).zip_code == value


def test_accepts_zip_plus_four():
    assert make(zip_code="02116-1234").zip_code == "02116-1234"


def test_nine_bare_digits_are_formatted_as_zip_plus_four():
    """A caller reading out nine digits means ZIP+4."""
    assert make(zip_code="021161234").zip_code == "02116-1234"


def test_spoken_zip_with_spaces_is_normalised():
    assert make(zip_code="02116 1234").zip_code == "02116-1234"


@pytest.mark.parametrize("value", ["1234", "123456", "abcde", "02116-12", "", "02116-abcd"])
def test_rejects_malformed_zips(value):
    with pytest.raises(ValidationError):
        make(zip_code=value)


# --- update ---------------------------------------------------------------


def test_update_is_partial():
    assert AddressUpdate(city="Somerville").changes() == {"city": "Somerville"}


def test_update_applies_the_same_rules():
    with pytest.raises(ValidationError):
        AddressUpdate(state="ZZ")
    with pytest.raises(ValidationError):
        AddressUpdate(zip_code="1234")


def test_update_normalises_like_create():
    assert AddressUpdate(state="ma").changes() == {"state": "MA"}


# --- ordering is instructed, not just enforced ---------------------------


def test_prompt_requires_the_patient_to_be_saved_first():
    assert "Saving happens in two steps, in this order:" in SYSTEM_PROMPT
    assert "1. Call create_patient. It returns a record id." in SYSTEM_PROMPT
    assert "2. Call save_address with that record id" in SYSTEM_PROMPT
    assert "Never call save_address first" in SYSTEM_PROMPT


def test_prompt_collects_every_required_address_field():
    for asked in ["Street address", "City", "State", "ZIP code"]:
        assert asked in SYSTEM_PROMPT
    assert "skip it if they do not have one" in SYSTEM_PROMPT


def test_prompt_converts_spoken_state_names_itself():
    assert 'if they say "Massachusetts", use MA' in SYSTEM_PROMPT
    assert "never make the caller spell it out" in SYSTEM_PROMPT
