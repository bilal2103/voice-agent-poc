"""Dispatches Vapi server messages and executes the voice agent's tool calls."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import BackgroundTasks
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.Schemas.Address import AddressCreate
from app.Schemas.Patient import (
    DATE_FORMAT,
    PatientCreate,
    PatientUpdate,
    _normalise_phone,
)
from app.Schemas.Vapi import ToolCallsResponse, ToolResult, VapiMessage, VapiToolCall
from app.Services.AddressService import AddressService
from app.Services.CallService import CallService, summarize_call_in_background
from app.Services.PatientService import (
    DuplicatePatientError,
    PatientNotFoundError,
    PatientService,
)
from app.Services.VapiAssistant import (
    CREATE_PATIENT_TOOL,
    LOOKUP_PATIENT_TOOL,
    SAVE_ADDRESS_TOOL,
    UPDATE_PATIENT_TOOL,
    build_assistant,
)

logger = logging.getLogger(__name__)


def _field_errors(exc: ValidationError) -> tuple[list[str], str]:
    """Split a validation failure into the field names and a readable reason.

    The agent is told to re-prompt for exactly these fields and keep everything
    else it already collected, so the names have to come back separately rather
    than buried in prose.
    """
    fields: list[str] = []
    reasons: list[str] = []
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"]) or "request"
        if field not in fields:
            fields.append(field)
        reasons.append(f"{field}: {err['msg']}")
    return fields, "; ".join(reasons)


class VapiService:
    def __init__(
        self,
        settings: Settings,
        patient_service: PatientService,
        call_service: CallService | None = None,
        summarize_task: Callable[[str], Awaitable[None]] | None = None,
        address_service: AddressService | None = None,
    ) -> None:
        self.settings = settings
        self.patient_service = patient_service
        self.call_service = call_service
        # Injectable so the queueing strategy can change - an out-of-process
        # worker, say - without touching this class.
        self.summarize_task = summarize_task or summarize_call_in_background
        self.address_service = address_service

    # --- entry point ------------------------------------------------------

    async def handle(
        self, message: VapiMessage, background_tasks: BackgroundTasks | None = None
    ) -> dict[str, Any]:
        """Returns the body Vapi expects; `{}` for informational events."""
        match message.type:
            case "assistant-request":
                return {"assistant": build_assistant(self.settings)}
            case "tool-calls":
                return await self._handle_tool_calls(message)
            case "end-of-call-report":
                logger.info(
                    "call ended: reason=%s call_id=%s",
                    message.ended_reason,
                    message.call_id(),
                )
                await self._record_call(message, background_tasks)
            case "status-update":
                logger.info(
                    "call status: %s call_id=%s",
                    message.status,
                    (message.call or {}).get("id"),
                )
            case _:
                logger.debug("unhandled vapi message type: %s", message.type)
        return {}

    # --- tool dispatch ----------------------------------------------------

    async def _handle_tool_calls(self, message: VapiMessage) -> dict[str, Any]:
        calls = message.tool_calls()
        if not calls:
            logger.warning(
                "tool-calls message carried no recognisable tool calls; "
                "neither toolCallList nor toolWithToolCallList parsed"
            )
        vapi_call_id = message.call_id()
        results = [await self._run_tool(call, vapi_call_id) for call in calls]
        return ToolCallsResponse(results=results).model_dump(by_alias=True, exclude_none=True)

    async def _run_tool(self, call: VapiToolCall, vapi_call_id: str = "") -> ToolResult:
        name = call.resolved_name()
        arguments = call.resolved_arguments()

        logger.info("   tool call id=%s name=%s args=%s", call.id, name or "<none>", arguments)
        if not arguments:
            logger.warning(
                "   tool call id=%s produced no arguments; raw shape was: %s",
                call.id,
                call.model_dump(exclude_none=True),
            )

        handlers = {
            LOOKUP_PATIENT_TOOL: self._lookup_patient,
            CREATE_PATIENT_TOOL: self._create_patient,
            UPDATE_PATIENT_TOOL: self._update_patient,
            SAVE_ADDRESS_TOOL: self._save_address,
        }
        handler = handlers.get(name)
        if handler is None:
            logger.warning("   unknown tool requested: %r (known: %s)", name, sorted(handlers))
            return ToolResult(
                tool_call_id=call.id, name=name or None, result=f"Unknown tool '{name}'."
            )

        try:
            return await handler(call.id, name, arguments, vapi_call_id)
        except Exception:
            # A DB error here would otherwise 500 the whole webhook and lose the
            # other tool results in the same batch.
            logger.exception("   tool %s failed unexpectedly for call id=%s", name, call.id)
            return ToolResult(
                tool_call_id=call.id,
                name=name,
                result=(
                    "A technical problem stopped the save. Apologise, and offer to "
                    "take the details again in a moment."
                ),
            )

    async def _create_patient(
        self, tool_call_id: str, name: str, arguments: dict[str, Any], vapi_call_id: str = ""
    ) -> ToolResult:
        """Validation failures come back as a `result`, not an HTTP error.

        The agent has to hear what went wrong so it can re-ask the caller; an
        error status would just make it apologise and stall.
        """
        try:
            payload = PatientCreate(**arguments)
        except ValidationError as exc:
            fields, reasons = _field_errors(exc)
            logger.warning(
                "   create_patient REJECTED id=%s fields=%s reasons=%s | arguments received: %s",
                tool_call_id,
                fields,
                reasons,
                arguments,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    f"Not saved. Re-prompt the caller for these fields only: "
                    f"{', '.join(fields)}. Keep every other value you already have "
                    f"and do not start over. Problem: {reasons}."
                ),
            )
        except TypeError as exc:
            logger.warning(
                "   create_patient got unusable arguments id=%s error=%s | received: %s",
                tool_call_id,
                exc,
                arguments,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="Could not save the patient: first_name, last_name and date_of_birth are all required.",
            )

        try:
            patient = await self.patient_service.create(payload)
        except DuplicatePatientError:
            logger.info(
                "   create_patient DUPLICATE id=%s name=%s %s dob=%s",
                tool_call_id,
                payload.first_name,
                payload.last_name,
                payload.date_of_birth,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="This patient is already registered. Let the caller know; do not retry.",
            )

        logger.info("   create_patient OK id=%s -> patient %s", tool_call_id, patient.patient_id)
        await self._link_call_to_patient(vapi_call_id, patient.patient_id)
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            result=(
                f"Patient registered successfully. "
                f"Name: {patient.first_name} {patient.last_name}. "
                f"Date of birth: {patient.date_of_birth.strftime('%m/%d/%Y')}. "
                f"Sex: {patient.sex.value}. Phone: {patient.phone_number}. "
                f"Record id: {patient.patient_id}. "
                f"Now call save_address with patient_id {patient.patient_id} "
                f"and the address you collected."
            ),
        )

    # --- lookup & update --------------------------------------------------

    async def _lookup_patient(
        self, tool_call_id: str, name: str, arguments: dict[str, Any], vapi_call_id: str = ""
    ) -> ToolResult:
        """Phone + date of birth, both required.

        Phone alone is not identity: caller ID is spoofable and numbers get
        reassigned. A failed match is reported as a plain "no match" with no
        hint about whether the number is on file, so a caller cannot probe for
        whose record exists by guessing dates.
        """
        raw_phone = str(arguments.get("phone_number") or "")
        raw_dob = str(arguments.get("date_of_birth") or "")

        digits = _normalise_phone(raw_phone)
        if len(digits) != 10:
            logger.warning("   lookup REJECTED id=%s unusable phone=%r", tool_call_id, raw_phone)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="That does not look like a 10-digit US number. Ask the caller to repeat it.",
            )

        try:
            date_of_birth = datetime.strptime(raw_dob.strip(), DATE_FORMAT).date()
        except ValueError:
            logger.warning("   lookup REJECTED id=%s unusable dob=%r", tool_call_id, raw_dob)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "The date of birth must be a real date in MM/DD/YYYY format. "
                    "Ask the caller to repeat it."
                ),
            )

        matches = await self.patient_service.find_by_phone_and_dob(digits, date_of_birth)
        # Never log the pair together with a hit/miss at INFO in a way that
        # implies identity; the count is enough to debug the flow.
        logger.info(
            "   lookup id=%s phone=%s dob=%s -> %d match(es)",
            tool_call_id,
            digits,
            date_of_birth,
            len(matches),
        )

        if not matches:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "No match. Treat the caller as new and continue with a new "
                    "registration. Do not tell them whether the number is on file, "
                    "and do not ask them to try another date of birth."
                ),
            )

        if len(matches) == 1:
            patient = matches[0]
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    f"Verified. First name: {patient.first_name}. "
                    f"Last name: {patient.last_name}. patient_id: {patient.patient_id}. "
                    f'Say exactly: "It looks like we already have a record for '
                    f'{patient.first_name} {patient.last_name}. Would you like to '
                    f'update your information instead?"'
                ),
            )

        options = "; ".join(f"{p.first_name} (patient_id: {p.patient_id})" for p in matches)
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            result=(
                f"{len(matches)} verified patients share that number and date of birth: "
                f"{options}. Ask which one the caller is, reading only the first names."
            ),
        )

    async def _update_patient(
        self, tool_call_id: str, name: str, arguments: dict[str, Any], vapi_call_id: str = ""
    ) -> ToolResult:
        fields = dict(arguments)
        raw_id = str(fields.pop("patient_id", "") or "")

        try:
            patient_id = uuid.UUID(raw_id)
        except ValueError:
            logger.warning("   update REJECTED id=%s bad patient_id=%r", tool_call_id, raw_id)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "Cannot update without a valid patient_id. "
                    "Call lookup_patient first and use the id it returns."
                ),
            )

        if not fields:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="No changes were supplied. Ask the caller what they would like to update.",
            )

        try:
            payload = PatientUpdate(**fields)
        except ValidationError as exc:
            bad_fields, reasons = _field_errors(exc)
            logger.warning(
                "   update REJECTED id=%s fields=%s reasons=%s | arguments received: %s",
                tool_call_id,
                bad_fields,
                reasons,
                fields,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    f"Not updated. Re-prompt the caller for these fields only: "
                    f"{', '.join(bad_fields)}. Keep every other value you already have. "
                    f"Problem: {reasons}."
                ),
            )

        try:
            patient = await self.patient_service.update(patient_id, payload)
        except PatientNotFoundError:
            logger.warning("   update id=%s patient %s not found", tool_call_id, patient_id)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="That record no longer exists. Offer to register the caller as new.",
            )
        except DuplicatePatientError:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "Those details now match a different patient already on file. "
                    "Do not retry; tell the caller we will sort it out manually."
                ),
            )

        changed = ", ".join(sorted(payload.changes()))
        logger.info("   update OK id=%s patient=%s fields=%s", tool_call_id, patient.patient_id, changed)
        await self._link_call_to_patient(vapi_call_id, patient.patient_id)
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            result=(
                f"Record updated for {patient.first_name} {patient.last_name}. "
                f"Fields changed: {changed}. "
                f"Now ask whether there is anything else they would like to change. "
                f"Do not end the call until they say there is nothing else."
            ),
        )

    # --- call records -----------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("unparseable timestamp from Vapi: %r", value)
            return None

    async def _link_call_to_patient(self, vapi_call_id: str, patient_id: uuid.UUID) -> None:
        """Best effort: losing the link must never fail the tool call."""
        if not vapi_call_id or self.call_service is None:
            return
        try:
            await self.call_service.link_patient(vapi_call_id, patient_id)
        except Exception:  # noqa: BLE001
            logger.exception("could not link call %s to patient %s", vapi_call_id, patient_id)

    async def _record_call(
        self, message: VapiMessage, background_tasks: BackgroundTasks | None
    ) -> None:
        """Stores the transcript, then queues summarisation to run after the response.

        Summarising inline would put an OpenAI round trip inside Vapi's webhook
        timeout, so the transcript is committed first and the summary follows.
        """
        if self.call_service is None:
            return

        vapi_call_id = message.call_id()
        if not vapi_call_id:
            logger.warning("end-of-call-report had no call id; nothing stored")
            return

        transcript = message.transcript()
        duration = message.duration_seconds

        try:
            await self.call_service.record_end_of_call(
                vapi_call_id=vapi_call_id,
                transcript=transcript,
                caller_number=message.caller_number(),
                ended_reason=message.ended_reason,
                started_at=self._parse_timestamp(message.started_at),
                ended_at=self._parse_timestamp(message.ended_at),
                duration_seconds=int(duration) if duration is not None else None,
            )
        except Exception:  # noqa: BLE001 - a storage failure must not 500 the webhook
            logger.exception("could not store call %s", vapi_call_id)
            return

        if not transcript or not transcript.strip():
            return

        if background_tasks is not None:
            background_tasks.add_task(self.summarize_task, vapi_call_id)
        else:
            # No request context (tests, direct calls): summarise inline.
            await self.call_service.summarize(vapi_call_id)

    async def _save_address(
        self, tool_call_id: str, name: str, arguments: dict[str, Any], vapi_call_id: str = ""
    ) -> ToolResult:
        """Requires an existing patient; the FK is what enforces the ordering."""
        if self.address_service is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result="Addresses cannot be saved right now. Continue without one.",
            )

        fields = dict(arguments)
        raw_id = str(fields.pop("patient_id", "") or "")

        try:
            patient_id = uuid.UUID(raw_id)
        except ValueError:
            logger.warning("   save_address REJECTED id=%s bad patient_id=%r", tool_call_id, raw_id)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "Cannot save an address without a valid patient_id. Save the "
                    "patient first with create_patient, then use the record id it returns."
                ),
            )

        try:
            payload = AddressCreate(**fields)
        except ValidationError as exc:
            bad_fields, reasons = _field_errors(exc)
            logger.warning(
                "   save_address REJECTED id=%s fields=%s reasons=%s | received: %s",
                tool_call_id,
                bad_fields,
                reasons,
                fields,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    f"Address not saved. Re-prompt the caller for these fields only: "
                    f"{', '.join(bad_fields)}. Keep every other value you already have. "
                    f"Problem: {reasons}."
                ),
            )
        except TypeError:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "Address not saved: street address, city, state and ZIP code are all required."
                ),
            )

        try:
            # Upsert, not create: a caller correcting a misheard street should
            # not hit a conflict on their second attempt.
            address = await self.address_service.upsert(patient_id, payload)
        except PatientNotFoundError:
            logger.warning("   save_address id=%s patient %s not found", tool_call_id, patient_id)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                result=(
                    "That patient does not exist, so the address cannot be attached. "
                    "Register the patient first with create_patient."
                ),
            )

        logger.info("   save_address OK id=%s patient=%s", tool_call_id, patient_id)
        line2 = f", {address.address_line_2}" if address.address_line_2 else ""
        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            result=(
                f"Address saved: {address.address_line_1}{line2}, "
                f"{address.city}, {address.state} {address.zip_code}."
            ),
        )
