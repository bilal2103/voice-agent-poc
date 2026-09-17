"""Maps every error path onto the `{"data": null, "error": {...}}` envelope.

Without these, FastAPI returns its own `{"detail": ...}` shape and the contract
would hold only for successful responses.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.Schemas.Envelope import ErrorDetail, fail

logger = logging.getLogger(__name__)

#: The Vapi webhook speaks Vapi's protocol, not the REST envelope.
EXEMPT_PREFIXES = ("/api/v1/vapi",)


def _is_exempt(request: Request) -> bool:
    return request.url.path.startswith(EXEMPT_PREFIXES)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if _is_exempt(request):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(exc.status_code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details = [
            ErrorDetail(
                # Drop the "body"/"query" prefix; the field name is what matters.
                field=".".join(str(part) for part in err["loc"][1:]) or None,
                message=err["msg"],
            )
            for err in exc.errors()
        ]
        logger.info("422 validation failure on %s: %s", request.url.path, exc.errors())

        if _is_exempt(request):
            return JSONResponse(status_code=422, content={"detail": exc.errors()})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=fail(422, "Request validation failed", details),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=fail(500, "Internal server error"),
        )
