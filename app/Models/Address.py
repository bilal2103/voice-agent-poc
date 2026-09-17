"""Address ORM model — one address per patient, linked by foreign key."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.Repository.database import Base

ADDRESS_LINE_MAX_LENGTH = 200
CITY_MAX_LENGTH = 100
STATE_LENGTH = 2
ZIP_MAX_LENGTH = 10


class Address(Base):
    __tablename__ = "addresses"

    address_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    #: The patient must exist first; deleting one takes its address with it.
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    address_line_1: Mapped[str] = mapped_column(String(ADDRESS_LINE_MAX_LENGTH), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(
        String(ADDRESS_LINE_MAX_LENGTH), nullable=True
    )
    city: Mapped[str] = mapped_column(String(CITY_MAX_LENGTH), nullable=False)
    #: Two-letter USPS abbreviation, stored uppercase.
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    #: 12345 or 12345-6789.
    zip_code: Mapped[str] = mapped_column(String(ZIP_MAX_LENGTH), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(address_line_1)) > 0", name="ck_addresses_line1_not_blank"
        ),
        CheckConstraint("char_length(btrim(city)) > 0", name="ck_addresses_city_not_blank"),
        CheckConstraint("state ~ '^[A-Z]{2}$'", name="ck_addresses_state_format"),
        CheckConstraint("zip_code ~ '^[0-9]{5}(-[0-9]{4})?$'", name="ck_addresses_zip_format"),
        Index("ix_addresses_patient_id", "patient_id"),
        Index("ix_addresses_zip_code", "zip_code"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Address address_id={self.address_id} patient_id={self.patient_id}>"
