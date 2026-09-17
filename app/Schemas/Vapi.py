"""Vapi server-message payloads.

Vapi's own docs disagree on where tool-call arguments live (`arguments` on one
page, `parameters` on another) and some versions nest them OpenAI-style under
`function`. The models below stay permissive and normalise all three shapes
rather than pinning one and breaking on a platform change.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VapiToolCall(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str | None = None
    arguments: Any = None
    parameters: Any = None
    function: dict[str, Any] | None = None

    def resolved_name(self) -> str:
        if self.name:
            return self.name
        if self.function:
            return str(self.function.get("name", ""))
        return ""

    def resolved_arguments(self) -> dict[str, Any]:
        raw: Any = None
        for candidate in (self.arguments, self.parameters):
            if candidate is not None:
                raw = candidate
                break
        if raw is None and self.function:
            raw = self.function.get("arguments") or self.function.get("parameters")

        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return raw if isinstance(raw, dict) else {}


class VapiMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    call: dict[str, Any] | None = None
    tool_call_list: list[VapiToolCall] = Field(default_factory=list, alias="toolCallList")
    tool_with_tool_call_list: list[dict[str, Any]] = Field(
        default_factory=list, alias="toolWithToolCallList"
    )
    status: str | None = None
    ended_reason: str | None = Field(default=None, alias="endedReason")
    artifact: dict[str, Any] | None = None
    started_at: str | None = Field(default=None, alias="startedAt")
    ended_at: str | None = Field(default=None, alias="endedAt")
    duration_seconds: float | None = Field(default=None, alias="durationSeconds")

    def call_id(self) -> str:
        return str((self.call or {}).get("id") or "")

    def caller_number(self) -> str | None:
        """Vapi nests the caller under call.customer for inbound calls."""
        customer = (self.call or {}).get("customer") or {}
        return customer.get("number")

    def transcript(self) -> str | None:
        return (self.artifact or {}).get("transcript")

    def tool_calls(self) -> list[VapiToolCall]:
        """Prefers the flat list; falls back to the nested `toolWithToolCallList`."""
        if self.tool_call_list:
            return self.tool_call_list

        calls: list[VapiToolCall] = []
        for entry in self.tool_with_tool_call_list:
            tool_call = entry.get("toolCall") or {}
            if not tool_call.get("id"):
                continue
            calls.append(
                VapiToolCall(
                    id=tool_call["id"],
                    name=entry.get("name") or tool_call.get("name"),
                    arguments=tool_call.get("arguments"),
                    parameters=tool_call.get("parameters"),
                    function=tool_call.get("function"),
                )
            )
        return calls


class VapiServerMessage(BaseModel):
    """Top-level body of every Vapi server webhook."""

    model_config = ConfigDict(extra="allow")

    message: VapiMessage


class ToolResult(BaseModel):
    """One entry in the `results` array Vapi expects back from a tool-calls webhook."""

    tool_call_id: str = Field(serialization_alias="toolCallId")
    result: str
    name: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class ToolCallsResponse(BaseModel):
    results: list[ToolResult]


class AssistantResponse(BaseModel):
    """Reply to an `assistant-request`, returning the assistant inline."""

    model_config = ConfigDict(extra="allow")

    assistant: dict[str, Any]


VapiMessageType = Literal[
    "assistant-request",
    "tool-calls",
    "status-update",
    "end-of-call-report",
]
