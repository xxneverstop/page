"""Session state and its JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from .models import Message, ModelTurn, ToolResult


@dataclass
class Session:
    """Replayable conversation facts; provider prompts are projections of it."""

    session_id: str = field(default_factory=lambda: f"session_{uuid4().hex}")
    messages: list[Message] = field(default_factory=list)

    def add_user(self, text: str) -> Message:
        message = Message("user", text)
        self.messages.append(message)
        return message

    def add_assistant(self, turn: ModelTurn) -> Message:
        message = turn.assistant_message()
        self.messages.append(message)
        return message

    def add_tool_result(self, result: ToolResult) -> Message:
        content = result.output if result.ok else result.error or result.output
        if result.exit_code is not None:
            content = f"exit_code={result.exit_code}\n{content}"
        if result.error and result.ok:
            content = f"error={result.error}\n{content}"
        message = Message(
            role="tool",
            content=content,
            name=result.name,
            tool_call_id=result.call_id,
        )
        self.messages.append(message)
        return message

    def to_dict(self) -> dict:
        return {"session_id": self.session_id, "messages": [m.to_dict() for m in self.messages]}

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            session_id=str(data["session_id"]),
            messages=[Message.from_dict(item) for item in data.get("messages", [])],
        )

    def save(self, path: str | Path) -> None:
        """Atomically replace a session file so a crash cannot leave partial JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @classmethod
    def load(cls, path: str | Path) -> "Session":
        with Path(path).open(encoding="utf-8") as stream:
            return cls.from_dict(json.load(stream))
