"""Single webhook Vapi posts every server message to."""

import hmac
import json
import logging
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import VapiServiceDep
from app.Schemas.Vapi import VapiServerMessage

logger = logging.getLogger(__name__)


def _summarise_assistant(response: dict) -> str:
    """The assistant payload embeds the whole system prompt; log its shape instead."""
    assistant = response.get("assistant") or {}
    model = assistant.get("model") or {}
    tools = [t.get("function", {}).get("name") for t in model.get("tools", [])]
    return (
        f"assistant={assistant.get('name')!r} model={model.get('provider')}/{model.get('model')} "
        f"voice={(assistant.get('voice') or {}).get('voiceId')} tools={tools}"
    )


def _preview(value: object, limit: int = 4000) -> str:
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}... [truncated]"


class VapiController:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/vapi", tags=["vapi"])
        self.router.add_api_route(
            "/webhook",
            self.webhook,
            methods=["POST"],
            summary="Vapi server messages (assistant-request, tool-calls, reports)",
        )

    def _authorize(self, request: Request) -> None:
        settings = get_settings()
        if not settings.vapi_secret:
            if settings.environment != "development":
                logger.error("VAPI_SECRET is not set outside development; rejecting webhook")
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook not configured")
            logger.debug("no VAPI_SECRET set; skipping auth (development)")
            return

        provided = request.headers.get(settings.vapi_secret_header, "")
        if not provided:
            logger.warning(
                "webhook rejected: header %r missing. Headers received: %s",
                settings.vapi_secret_header,
                sorted(request.headers.keys()),
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook secret")
        if not hmac.compare_digest(provided, settings.vapi_secret):
            logger.warning("webhook rejected: header %r present but value did not match", settings.vapi_secret_header)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook secret")

    async def webhook(
        self, request: Request, background_tasks: BackgroundTasks, service: VapiServiceDep
    ) -> dict:
        settings = get_settings()
        started = time.perf_counter()
        self._authorize(request)

        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raw = (await request.body())[:500]
            logger.error("webhook body was not valid JSON: %s | raw=%r", exc, raw)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed payload") from exc

        message_type = (body.get("message") or {}).get("type", "<none>")
        call_id = ((body.get("message") or {}).get("call") or {}).get("id", "-")

        logger.info("-> vapi message type=%s call=%s", message_type, call_id)

        try:
            payload = VapiServerMessage.model_validate(body)
        except Exception as exc:  # noqa: BLE001 - unknown shapes must not 500 the call
            logger.error("unparseable vapi payload: %s | body=%s", exc, _preview(body))
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed payload") from exc

        try:
            response = await service.handle(payload.message, background_tasks)
        except Exception:
            # Without this the traceback is swallowed and the caller just hears
            # "a technical issue" with nothing on the server to explain it.
            logger.exception(
                "unhandled error while processing type=%s call=%s body=%s",
                message_type,
                call_id,
                _preview(body),
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("<- responded type=%s call=%s in %.0fms", message_type, call_id, elapsed_ms)

        if message_type == "assistant-request" and elapsed_ms > 7500:
            logger.warning(
                "assistant-request took %.0fms; Vapi times out at 7500ms and will drop the call",
                elapsed_ms,
            )

        return response
