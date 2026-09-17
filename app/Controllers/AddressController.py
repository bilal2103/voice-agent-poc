"""HTTP layer for a patient's address, nested under the patient that owns it."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.dependencies import AddressServiceDep
from app.Schemas.Address import AddressCreate, AddressRead, AddressUpdate
from app.Schemas.Envelope import Envelope, ok
from app.Services.AddressService import AddressAlreadyExistsError, AddressNotFoundError
from app.Services.PatientService import PatientNotFoundError


class AddressController:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/patients/{patient_id}/address", tags=["addresses"])
        self.router.add_api_route(
            "",
            self.create,
            methods=["POST"],
            response_model=Envelope[AddressRead],
            status_code=status.HTTP_201_CREATED,
            summary="Save a patient's address",
        )
        self.router.add_api_route(
            "",
            self.get,
            methods=["GET"],
            response_model=Envelope[AddressRead],
            summary="Retrieve a patient's address",
        )
        self.router.add_api_route(
            "",
            self.update,
            methods=["PUT"],
            response_model=Envelope[AddressRead],
            summary="Update a patient's address (partial updates allowed)",
        )
        self.router.add_api_route(
            "",
            self.delete,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Remove a patient's address",
        )

    async def create(
        self, patient_id: uuid.UUID, payload: AddressCreate, service: AddressServiceDep
    ) -> dict:
        try:
            address = await service.create(patient_id, payload)
        except PatientNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except AddressAlreadyExistsError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return ok(AddressRead.model_validate(address))

    async def get(self, patient_id: uuid.UUID, service: AddressServiceDep) -> dict:
        try:
            address = await service.get(patient_id)
        except (PatientNotFoundError, AddressNotFoundError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return ok(AddressRead.model_validate(address))

    async def update(
        self, patient_id: uuid.UUID, payload: AddressUpdate, service: AddressServiceDep
    ) -> dict:
        try:
            address = await service.update(patient_id, payload)
        except (PatientNotFoundError, AddressNotFoundError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return ok(AddressRead.model_validate(address))

    async def delete(self, patient_id: uuid.UUID, service: AddressServiceDep) -> None:
        try:
            await service.delete(patient_id)
        except (PatientNotFoundError, AddressNotFoundError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
