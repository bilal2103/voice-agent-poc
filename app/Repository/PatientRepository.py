"""Data access for patients. Knows about the ORM and nothing about HTTP.

Every read filters out soft-deleted rows; `deleted_at` is the only thing DELETE
touches, so a deleted patient stays on disk but is invisible to the API.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Models.Patient import Patient


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _alive(stmt: Select) -> Select:
        return stmt.where(Patient.deleted_at.is_(None))

    async def add(self, patient: Patient) -> Patient:
        """Stage a new patient and flush so server defaults (id, timestamps) are populated."""
        self.session.add(patient)
        await self.session.flush()
        await self.session.refresh(patient)
        return patient

    async def get_by_id(self, patient_id: uuid.UUID) -> Patient | None:
        stmt = self._alive(select(Patient).where(Patient.patient_id == patient_id))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name_and_dob(
        self, first_name: str, last_name: str, date_of_birth: date
    ) -> Patient | None:
        stmt = self._alive(
            select(Patient).where(
                Patient.first_name == first_name,
                Patient.last_name == last_name,
                Patient.date_of_birth == date_of_birth,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_phone_and_dob(
        self, phone_number: str, date_of_birth: date
    ) -> Sequence[Patient]:
        """Live patients matching BOTH a number and a date of birth.

        Phone alone is not an identity check - caller ID is spoofable and
        numbers get reassigned - so the date of birth is required to match
        before any record is disclosed. Still returns a list: twins on a shared
        family line would match both.
        """
        stmt = self._alive(
            select(Patient).where(
                Patient.phone_number == phone_number,
                Patient.date_of_birth == date_of_birth,
            )
        )
        stmt = stmt.order_by(Patient.created_at)
        return (await self.session.execute(stmt)).scalars().all()

    async def list(
        self,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        phone_number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Patient]:
        stmt = self._alive(select(Patient))

        if last_name is not None:
            # Case-insensitive: a caller's spelling rarely matches stored casing.
            stmt = stmt.where(Patient.last_name.ilike(last_name))
        if date_of_birth is not None:
            stmt = stmt.where(Patient.date_of_birth == date_of_birth)
        if phone_number is not None:
            stmt = stmt.where(Patient.phone_number == phone_number)

        stmt = stmt.order_by(Patient.last_name, Patient.first_name).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

    async def update(self, patient: Patient, changes: dict) -> Patient:
        for field, value in changes.items():
            setattr(patient, field, value)
        await self.session.flush()
        await self.session.refresh(patient)
        return patient

    async def soft_delete(self, patient: Patient) -> Patient:
        patient.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(patient)
        return patient
