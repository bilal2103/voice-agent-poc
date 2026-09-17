"""Patient ORM model — mirrors the `patients` table."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.Repository.database import Base

NAME_MAX_LENGTH = 50
EMAIL_MAX_LENGTH = 254
PHONE_LENGTH = 10
INSURANCE_PROVIDER_MAX_LENGTH = 100
INSURANCE_MEMBER_ID_MAX_LENGTH = 50
CONTACT_NAME_MAX_LENGTH = 100
LANGUAGE_MAX_LENGTH = 50


class Sex(str, enum.Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE_TO_ANSWER = "Decline to Answer"


#: Stores the labels ("Decline to Answer") rather than the member names.
SEX_ENUM = Enum(
    Sex,
    name="sex_enum",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    first_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    last_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[Sex] = mapped_column(SEX_ENUM, nullable=False)
    #: Ten digits, no punctuation; formatting is a presentation concern.
    phone_number: Mapped[str] = mapped_column(String(PHONE_LENGTH), nullable=False)
    email: Mapped[str | None] = mapped_column(String(EMAIL_MAX_LENGTH), nullable=True)

    # Optional intake extras; the voice agent offers these rather than demanding them.
    insurance_provider: Mapped[str | None] = mapped_column(
        String(INSURANCE_PROVIDER_MAX_LENGTH), nullable=True
    )
    insurance_member_id: Mapped[str | None] = mapped_column(
        String(INSURANCE_MEMBER_ID_MAX_LENGTH), nullable=True
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(CONTACT_NAME_MAX_LENGTH), nullable=True
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(PHONE_LENGTH), nullable=True
    )
    preferred_language: Mapped[str | None] = mapped_column(
        String(LANGUAGE_MAX_LENGTH), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    #: Set by DELETE; every read filters on this being NULL.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("char_length(btrim(first_name)) > 0", name="ck_patients_first_name_not_blank"),
        CheckConstraint("char_length(btrim(last_name)) > 0", name="ck_patients_last_name_not_blank"),
        CheckConstraint("phone_number ~ '^[0-9]{10}$'", name="ck_patients_phone_number_digits"),
        CheckConstraint(
            "emergency_contact_phone IS NULL OR emergency_contact_phone ~ '^[0-9]{10}$'",
            name="ck_patients_emergency_phone_digits",
        ),
        Index("ix_patients_name_dob", "last_name", "first_name", "date_of_birth"),
        Index("ix_patients_phone_number", "phone_number"),
        # List queries always exclude soft-deleted rows.
        Index("ix_patients_deleted_at", "deleted_at"),
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Patient patient_id={self.patient_id} last_name={self.last_name!r}>"
