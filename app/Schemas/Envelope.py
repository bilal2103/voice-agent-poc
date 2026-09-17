"""The `{"data": ..., "error": ...}` envelope every REST response is wrapped in."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """One field-level validation problem."""

    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: int = Field(..., examples=[404])
    message: str
    details: list[ErrorDetail] | None = None


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    error: ErrorBody | None = None


def ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}


def fail(
    code: int, message: str, details: list[ErrorDetail] | None = None
) -> dict[str, Any]:
    body = ErrorBody(code=code, message=message, details=details)
    return {"data": None, "error": body.model_dump(exclude_none=True)}
