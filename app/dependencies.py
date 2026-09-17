"""Wiring for the Controller -> Service -> Repository chain."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.LLM.CallSummarizer import CallSummarizer
from app.LLM.factory import get_call_summarizer
from app.Repository.AddressRepository import AddressRepository
from app.Repository.CallRepository import CallRepository
from app.Repository.database import get_db
from app.Repository.PatientRepository import PatientRepository
from app.Services.AddressService import AddressService
from app.Services.CallService import CallService
from app.Services.PatientService import PatientService
from app.Services.VapiService import VapiService

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SummarizerDep = Annotated[CallSummarizer, Depends(get_call_summarizer)]


def get_patient_service(session: DbSession) -> PatientService:
    return PatientService(PatientRepository(session))


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]


def get_address_service(session: DbSession) -> AddressService:
    return AddressService(AddressRepository(session), PatientService(PatientRepository(session)))


AddressServiceDep = Annotated[AddressService, Depends(get_address_service)]


def get_call_service(session: DbSession, summarizer: SummarizerDep) -> CallService:
    return CallService(CallRepository(session), summarizer)


CallServiceDep = Annotated[CallService, Depends(get_call_service)]


def get_vapi_service(
    settings: SettingsDep,
    patient_service: PatientServiceDep,
    call_service: CallServiceDep,
    address_service: AddressServiceDep,
) -> VapiService:
    return VapiService(settings, patient_service, call_service, address_service=address_service)


VapiServiceDep = Annotated[VapiService, Depends(get_vapi_service)]
