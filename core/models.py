"""Small structured values shared by the agent components."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class Message:
    """A provider-neutral chat message.

    ``content`` may be text or a provider-specific structured value. Keeping it
    as data avoids forcing provider formatting into Session.
    """

    role: str
    content: Any = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=str(data["role"]),
            content=data.get("content", ""),
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=list(data.get("tool_calls", [])),
        )


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "name": self.name, "arguments": self.arguments}


@dataclass(slots=True)
class ToolResult:
    call_id: str
    name: str
    ok: bool
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    error: str | None = None
    request_id: str = field(default_factory=lambda: f"req_{uuid4().hex}")

    @property
    def is_error(self) -> bool:
        return bool(self.error)

    def assistant_message(self) -> Message:
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=[call.to_dict() for call in self.tool_calls],
        )


@dataclass(slots=True)
class AgentResult:
    status: str
    answer: str = ""
    stop_reason: str | None = None
    turns: int = 0
    tool_calls: int = 0
    elapsed_ms: int = 0
    session_id: str | None = None


@dataclass(slots=True)
class AgentEvent:
    event: str
    run_id: str
    turn_id: str | None = None
    model_request_id: str | None = None
    tool_call_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
