"""Request/response contracts for patient addresses, with the field rules."""

import re
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

#: USPS two-letter codes: 50 states, DC, territories and military posts.
US_STATE_CODES = frozenset(
    """
    AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
    MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY
    DC AS GU MP PR VI AA AE AP
    """.split()
)

#: Street lines: letters, digits and the punctuation real addresses carry.
#: A leading "#" is allowed - "#7 Park Lane" is a real address.
ADDRESS_LINE_PATTERN = re.compile(r"^[A-Za-z0-9#][A-Za-z0-9 .,'#/\-]*$")

#: City names: words of letters, each optionally abbreviated with a period,
#: joined by single spaces, hyphens or apostrophes. Covers "St. Louis",
#: "Winston-Salem" and "Coeur d'Alene".
CITY_PATTERN = re.compile(r"^[A-Za-z]+\.?(?:[ '\-][A-Za-z]+\.?)*$")

#: 5-digit, or ZIP+4.
ZIP_PATTERN = re.compile(r"^\d{5}(?:-\d{4})?$")


class AddressFieldRules(BaseModel):
    """Shared by create and update; see PatientFieldRules for why this is a mixin."""

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def _strip_and_blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("address_line_1", "address_line_2", check_fields=False)
    @classmethod
    def _validate_line(cls, value: str | None) -> str | None:
        if value is not None and not ADDRESS_LINE_PATTERN.fullmatch(value):
            raise ValueError(
                "must start with a letter or digit and contain only letters, digits, "
                "spaces and the punctuation . , ' # / -"
            )
        return value

    @field_validator("city", check_fields=False)
    @classmethod
    def _validate_city(cls, value: str | None) -> str | None:
        if value is not None and not CITY_PATTERN.fullmatch(value):
            raise ValueError("must be a place name using only letters, spaces, hyphens and apostrophes")
        return value

    @field_validator("state", mode="before", check_fields=False)
    @classmethod
    def _validate_state(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        code = value.strip().upper()
        if code not in US_STATE_CODES:
            raise ValueError(
                "must be a valid 2-letter US state or territory abbreviation, such as MA"
            )
        return code

    @field_validator("zip_code", mode="before", check_fields=False)
    @classmethod
    def _validate_zip(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        # Callers dictate "one two three four five six seven eight nine";
        # nine bare digits mean ZIP+4.
        code = re.sub(r"[\s–—]", "", value.strip())
        if re.fullmatch(r"\d{9}", code):
            code = f"{code[:5]}-{code[5:]}"
        if not ZIP_PATTERN.fullmatch(code):
            raise ValueError("must be a 5-digit ZIP or ZIP+4, such as 02118 or 02118-1234")
        return code


class AddressCreate(AddressFieldRules):
    """Body of POST /patients/{patient_id}/address."""

    address_line_1: str = Field(..., max_length=200, examples=["120 Beacon Street"])
    address_line_2: str | None = Field(default=None, max_length=200, examples=["Apt 4B"])
    city: str = Field(..., min_length=1, max_length=100, examples=["Boston"])
    state: str = Field(..., examples=["MA"])
    zip_code: str = Field(..., examples=["02116"])


class AddressUpdate(AddressFieldRules):
    """Body of PUT /patients/{patient_id}/address. Every field is optional."""

    address_line_1: str | None = Field(default=None, max_length=200)
    address_line_2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = None
    zip_code: str | None = None

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class AddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    address_id: uuid.UUID
    patient_id: uuid.UUID
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_utc(self, value: datetime) -> str:
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
