"""Aggregates every controller into a single versioned API router."""

from fastapi import APIRouter

from app.Controllers.AddressController import AddressController
from app.Controllers.CallController import CallController
from app.Controllers.HealthController import HealthController
from app.Controllers.PatientController import PatientController
from app.Controllers.VapiController import VapiController

api_router = APIRouter()
api_router.include_router(HealthController().router)
api_router.include_router(PatientController().router)
api_router.include_router(AddressController().router)
api_router.include_router(CallController().router)
api_router.include_router(VapiController().router)
