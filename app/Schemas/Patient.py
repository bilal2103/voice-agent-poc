"""Request/response contracts for patients, including the field validation rules."""

import re
import uuid
from datetime import date, datetime, timezone

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_serializer,
    field_validator,
)

from app.Models.Patient import Sex

#: Letters, with hyphens/apostrophes allowed only *between* letters.
#: Accepts "O'Brien", "Anne-Marie"; rejects "-Ann", "Mary--Jane", "J0hn".
NAME_PATTERN = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")

#: NANP rules: area code and exchange code both start 2-9.
US_PHONE_PATTERN = re.compile(r"^[2-9]\d{2}[2-9]\d{6}$")

#: A person's full name: letters, with single spaces/hyphens/apostrophes between.
#: Unlike first_name/last_name this allows spaces - it is one whole name.
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z]+(?:[-' ][A-Za-z]+)*$")

#: Member/subscriber IDs are alphanumeric, no punctuation.
MEMBER_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+$")

#: Insurance company names: letters, digits and the punctuation brands use.
INSURANCE_PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,&'/-]*$")

#: Language names, e.g. "Spanish", "Haitian Creole", "Serbo-Croatian".
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]+(?:[- ][A-Za-z]+)*$")

#: The only date format accepted on input and emitted on output.
DATE_FORMAT = "%m/%d/%Y"


def _normalise_phone(value: str) -> str:
    """Strips formatting and a leading US country code.

    Callers dictate numbers every way imaginable — "(662) 670-1017",
    "+1 662 670 1017", "662.670.1017" — and all of them mean the same row.
    """
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


class PatientFieldRules(BaseModel):
    """Field rules shared by create and update.

    These live on a mixin both models inherit: Pydantic v2 inherits validators
    down the MRO, but does *not* pick them up if you assign the decorated
    objects onto another class, which silently leaves that model unvalidated.
    `check_fields=False` lets the mixin cover fields a subclass may not declare.
    """

    @field_validator("first_name", "last_name", mode="before", check_fields=False)
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("first_name", "last_name", check_fields=False)
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "must contain only letters, hyphens and apostrophes, "
                "and must begin and end with a letter"
            )
        return value

    @field_validator("date_of_birth", mode="before", check_fields=False)
    @classmethod
    def _parse_date(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return datetime.strptime(value.strip(), DATE_FORMAT).date()
            except ValueError:
                raise ValueError("must be a valid date in MM/DD/YYYY format") from None
        return value

    @field_validator("date_of_birth", check_fields=False)
    @classmethod
    def _reject_future_dates(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("cannot be in the future")
        return value

    @field_validator("phone_number", mode="before", check_fields=False)
    @classmethod
    def _validate_phone(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        digits = _normalise_phone(value)
        if not US_PHONE_PATTERN.fullmatch(digits):
            raise ValueError(
                "must be a valid 10-digit US phone number; "
                "area code and exchange code cannot start with 0 or 1"
            )
        return digits

    @field_validator(
        "email",
        "insurance_provider",
        "insurance_member_id",
        "emergency_contact_name",
        "emergency_contact_phone",
        "preferred_language",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _blank_optional_is_none(cls, value: object) -> object:
        # A voice agent that collected nothing sends "" rather than omitting the key.
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("emergency_contact_phone", mode="before", check_fields=False)
    @classmethod
    def _validate_emergency_phone(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        # Pydantic runs before-validators in reverse definition order, so this
        # sees the raw input ahead of the blank-to-None pass.
        if not value.strip():
            return None
        digits = _normalise_phone(value)
        if not US_PHONE_PATTERN.fullmatch(digits):
            raise ValueError(
                "must be a valid 10-digit US phone number; "
                "area code and exchange code cannot start with 0 or 1"
            )
        return digits

    @field_validator("emergency_contact_name", check_fields=False)
    @classmethod
    def _validate_contact_name(cls, value: str | None) -> str | None:
        if value is not None and not FULL_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "must be a full name using only letters, spaces, hyphens and apostrophes"
            )
        return value

    @field_validator("insurance_member_id", check_fields=False)
    @classmethod
    def _validate_member_id(cls, value: str | None) -> str | None:
        if value is not None and not MEMBER_ID_PATTERN.fullmatch(value):
            raise ValueError("must be alphanumeric, with no spaces or punctuation")
        return value

    @field_validator("insurance_provider", check_fields=False)
    @classmethod
    def _validate_insurance_provider(cls, value: str | None) -> str | None:
        if value is not None and not INSURANCE_PROVIDER_PATTERN.fullmatch(value):
            raise ValueError("must be a company name using letters, digits and basic punctuation")
        return value

    @field_validator("preferred_language", check_fields=False)
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        if value is not None and not LANGUAGE_PATTERN.fullmatch(value):
            raise ValueError("must be a language name using only letters, spaces and hyphens")
        return value


class PatientBase(PatientFieldRules):
    first_name: str = Field(..., min_length=1, max_length=50, examples=["Maria"])
    last_name: str = Field(..., min_length=1, max_length=50, examples=["O'Brien"])
    date_of_birth: date = Field(..., examples=["03/15/1985"])
    sex: Sex = Field(..., examples=["Female"])
    phone_number: str = Field(..., examples=["6626701017"])
    email: EmailStr | None = Field(default=None, examples=["maria@example.com"])

    insurance_provider: str | None = Field(
        default=None, max_length=100, examples=["Blue Cross Blue Shield"]
    )
    insurance_member_id: str | None = Field(default=None, max_length=50, examples=["XYZ123456789"])
    emergency_contact_name: str | None = Field(
        default=None, max_length=100, examples=["John O'Brien"]
    )
    emergency_contact_phone: str | None = Field(default=None, examples=["6175551234"])
    preferred_language: str | None = Field(default=None, max_length=50, examples=["Spanish"])


class PatientCreate(PatientBase):
    """Body of POST /patients."""


class PatientUpdate(PatientFieldRules):
    """Body of PUT /patients/{patient_id}. Every field is optional."""

    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    last_name: str | None = Field(default=None, min_length=1, max_length=50)
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone_number: str | None = None
    email: EmailStr | None = None
    insurance_provider: str | None = Field(
        default=None, max_length=100, examples=["Blue Cross Blue Shield"]
    )
    insurance_member_id: str | None = Field(default=None, max_length=50, examples=["XYZ123456789"])
    emergency_contact_name: str | None = Field(
        default=None, max_length=100, examples=["John O'Brien"]
    )
    emergency_contact_phone: str | None = Field(default=None, examples=["6175551234"])
    preferred_language: str | None = Field(default=None, max_length=50, examples=["Spanish"])

    def changes(self) -> dict:
        """Only the fields the client actually sent, so PUT can be partial."""
        return self.model_dump(exclude_unset=True)


class PatientRead(BaseModel):
    """A stored patient as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: str | None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    preferred_language: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @field_serializer("date_of_birth")
    def _serialize_date(self, value: date) -> str:
        return value.strftime(DATE_FORMAT)

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _serialize_utc(self, value: datetime | None) -> str | None:
        """Always emit UTC with a trailing Z.

        The columns are timestamptz so the stored instant is absolute, but a
        driver or session in another zone would otherwise render a local offset.
        """
        if value is None:
            return None
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
