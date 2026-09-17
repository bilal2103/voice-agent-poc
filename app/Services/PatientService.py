"""Business rules for patients. Owns the transaction; raises domain errors, not HTTP ones."""

import uuid
from collections.abc import Sequence
from datetime import date

from app.Models.Patient import Patient
from app.Repository.PatientRepository import PatientRepository
from app.Schemas.Patient import PatientCreate, PatientUpdate


class PatientNotFoundError(Exception):
    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(f"Patient {patient_id} was not found")
        self.patient_id = patient_id


class DuplicatePatientError(Exception):
    def __init__(self) -> None:
        super().__init__("A patient with the same name and date of birth already exists")


class PatientService:
    def __init__(self, repository: PatientRepository) -> None:
        self.repository = repository

    async def create(self, payload: PatientCreate) -> Patient:
        existing = await self.repository.get_by_name_and_dob(
            payload.first_name, payload.last_name, payload.date_of_birth
        )
        if existing is not None:
            raise DuplicatePatientError

        patient = await self.repository.add(Patient(**payload.model_dump()))
        await self.repository.session.commit()
        return patient

    async def get(self, patient_id: uuid.UUID) -> Patient:
        patient = await self.repository.get_by_id(patient_id)
        if patient is None:
            raise PatientNotFoundError(patient_id)
        return patient

    async def list(
        self,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        phone_number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Patient]:
        return await self.repository.list(
            last_name=last_name,
            date_of_birth=date_of_birth,
            phone_number=phone_number,
            limit=limit,
            offset=offset,
        )

    async def find_by_phone_and_dob(
        self, phone_number: str, date_of_birth: date
    ) -> Sequence[Patient]:
        """Identity check for the voice agent: both must match."""
        return await self.repository.list_by_phone_and_dob(phone_number, date_of_birth)

    async def update(self, patient_id: uuid.UUID, payload: PatientUpdate) -> Patient:
        patient = await self.get(patient_id)
        changes = payload.changes()

        if changes:
            # A rename or DOB change could collide with another live record.
            identity_changed = {"first_name", "last_name", "date_of_birth"} & changes.keys()
            if identity_changed:
                clash = await self.repository.get_by_name_and_dob(
                    changes.get("first_name", patient.first_name),
                    changes.get("last_name", patient.last_name),
                    changes.get("date_of_birth", patient.date_of_birth),
                )
                if clash is not None and clash.patient_id != patient.patient_id:
                    raise DuplicatePatientError

            await self.repository.update(patient, changes)
            await self.repository.session.commit()

        return patient

    async def delete(self, patient_id: uuid.UUID) -> Patient:
        """Soft delete: stamps `deleted_at`, never removes the row."""
        patient = await self.get(patient_id)
        await self.repository.soft_delete(patient)
        await self.repository.session.commit()
        return patient
