"""HTTP layer for /patients. Translates requests into service calls and errors into responses."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import PatientServiceDep
from app.Schemas.Envelope import Envelope, ok
from app.Schemas.Patient import DATE_FORMAT, PatientCreate, PatientRead, PatientUpdate
from app.Services.PatientService import DuplicatePatientError, PatientNotFoundError


def _parse_dob_filter(value: str | None) -> date | None:
    """`?date_of_birth=` uses the same MM/DD/YYYY format as the body."""
    if value is None:
        return None
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "date_of_birth filter must be in MM/DD/YYYY format",
        ) from None


class PatientController:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/patients", tags=["patients"])
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route(
            "",
            self.create,
            methods=["POST"],
            response_model=Envelope[PatientRead],
            status_code=status.HTTP_201_CREATED,
            summary="Create a new patient",
        )
        self.router.add_api_route(
            "",
            self.list,
            methods=["GET"],
            response_model=Envelope[list[PatientRead]],
            summary="List patients",
        )
        self.router.add_api_route(
            "/{patient_id}",
            self.get,
            methods=["GET"],
            response_model=Envelope[PatientRead],
            summary="Retrieve a single patient by patient_id",
        )
        self.router.add_api_route(
            "/{patient_id}",
            self.update,
            methods=["PUT"],
            response_model=Envelope[PatientRead],
            summary="Update a patient (partial updates allowed)",
        )
        self.router.add_api_route(
            "/{patient_id}",
            self.delete,
            methods=["DELETE"],
            response_model=Envelope[PatientRead],
            summary="Soft-delete a patient",
        )

    async def create(self, payload: PatientCreate, service: PatientServiceDep) -> dict:
        try:
            patient = await service.create(payload)
        except DuplicatePatientError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return ok(PatientRead.model_validate(patient))

    async def list(
        self,
        service: PatientServiceDep,
        last_name: str | None = Query(None, description="Exact match, case-insensitive"),
        date_of_birth: str | None = Query(None, description="MM/DD/YYYY"),
        phone_number: str | None = Query(None, description="10 digits; punctuation ignored"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict:
        digits = "".join(c for c in phone_number if c.isdigit()) if phone_number else None
        if digits and len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]

        patients = await service.list(
            last_name=last_name,
            date_of_birth=_parse_dob_filter(date_of_birth),
            phone_number=digits,
            limit=limit,
            offset=offset,
        )
        return ok([PatientRead.model_validate(patient) for patient in patients])

    async def get(self, patient_id: uuid.UUID, service: PatientServiceDep) -> dict:
        try:
            patient = await service.get(patient_id)
        except PatientNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return ok(PatientRead.model_validate(patient))

    async def update(
        self, patient_id: uuid.UUID, payload: PatientUpdate, service: PatientServiceDep
    ) -> dict:
        try:
            patient = await service.update(patient_id, payload)
        except PatientNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except DuplicatePatientError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return ok(PatientRead.model_validate(patient))

    async def delete(self, patient_id: uuid.UUID, service: PatientServiceDep) -> dict:
        try:
            patient = await service.delete(patient_id)
        except PatientNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return ok(PatientRead.model_validate(patient))
