"""Business rules for patient addresses.

An address cannot exist without its patient, so every operation resolves the
patient first - that is what enforces "save the patient, then the address".
"""

import logging
import uuid

from app.Models.Address import Address
from app.Repository.AddressRepository import AddressRepository
from app.Schemas.Address import AddressCreate, AddressUpdate
from app.Services.PatientService import PatientService

logger = logging.getLogger(__name__)


class AddressNotFoundError(Exception):
    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(f"Patient {patient_id} has no address on file")
        self.patient_id = patient_id


class AddressAlreadyExistsError(Exception):
    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(f"Patient {patient_id} already has an address; update it instead")
        self.patient_id = patient_id


class AddressService:
    def __init__(self, repository: AddressRepository, patient_service: PatientService) -> None:
        self.repository = repository
        self.patient_service = patient_service

    async def create(self, patient_id: uuid.UUID, payload: AddressCreate) -> Address:
        # Raises PatientNotFoundError if the patient does not exist or is deleted,
        # so a stray foreign key can never be written.
        await self.patient_service.get(patient_id)

        if await self.repository.get_by_patient_id(patient_id) is not None:
            raise AddressAlreadyExistsError(patient_id)

        address = await self.repository.add(
            Address(patient_id=patient_id, **payload.model_dump())
        )
        await self.repository.session.commit()
        logger.info("address saved for patient %s", patient_id)
        return address

    async def get(self, patient_id: uuid.UUID) -> Address:
        await self.patient_service.get(patient_id)
        address = await self.repository.get_by_patient_id(patient_id)
        if address is None:
            raise AddressNotFoundError(patient_id)
        return address

    async def update(self, patient_id: uuid.UUID, payload: AddressUpdate) -> Address:
        address = await self.get(patient_id)
        changes = payload.changes()
        if changes:
            await self.repository.update(address, changes)
            await self.repository.session.commit()
        return address

    async def upsert(self, patient_id: uuid.UUID, payload: AddressCreate) -> Address:
        """Create, or replace what is there.

        The voice agent may retry after a mishearing, and a caller correcting
        their address should not hit a conflict.
        """
        await self.patient_service.get(patient_id)
        existing = await self.repository.get_by_patient_id(patient_id)
        if existing is None:
            return await self.create(patient_id, payload)

        await self.repository.update(existing, payload.model_dump())
        await self.repository.session.commit()
        return existing

    async def delete(self, patient_id: uuid.UUID) -> None:
        address = await self.get(patient_id)
        await self.repository.delete(address)
        await self.repository.session.commit()
