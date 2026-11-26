"""Context projection used for each model request."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .models import Message
from .session import Session


@dataclass
class Context:
    system_prompt: str = "You are a careful coding agent. Use tools when they help."
    max_messages: int | None = None
    max_chars: int | None = None
    skill_context: str = ""
    _file_versions: dict[str, tuple[int, int, str]] = field(default_factory=dict, repr=False)

    def build(self, session: Session) -> list[Message]:
        """Return a fresh projection; building context never mutates Session."""
        system_text = self.system_prompt
        if self.skill_context.strip():
            system_text = f"{system_text}\n\n{self.skill_context.strip()}"
        messages = [Message("system", system_text), *session.messages]
        if self.max_messages is not None and self.max_messages > 0:
            messages = [messages[0], *self._recent_complete_messages(messages[1:], self.max_messages)]
        if self.max_chars is not None and self.max_chars > 0:
            messages = self._fit_chars(messages, self.max_chars)
        return list(messages)

    def record_file_version(self, path: str | Path, *, stat_result: tuple[int, int] | None = None) -> None:
        """Remember the observed file version so stale reads can be rejected."""
        value = _file_version(path) if stat_result is None else (*stat_result, _file_digest(path))
        self._file_versions[str(Path(path).resolve())] = value

    def is_file_fresh(self, path: str | Path) -> bool:
        key = str(Path(path).resolve())
        expected = self._file_versions.get(key)
        if expected is None:
            return False
        try:
            current = _file_version(path)
        except OSError:
            return False
        return current == expected

    @staticmethod
    def _recent_complete_messages(messages: list[Message], limit: int) -> list[Message]:
        """Trim whole conversation facts, retaining assistant/tool pairs."""
        selected = messages[-limit:]
        if selected and selected[0].role == "tool":
            # A tool result without its assistant call is unusable to providers.
            for index, message in enumerate(messages):
                if message is selected[0] and index > 0:
                    selected = messages[index - 1 :]
                    break
        return selected

    @staticmethod
    def _fit_chars(messages: list[Message], max_chars: int) -> list[Message]:
        if sum(len(str(item.content)) for item in messages) <= max_chars:
            return messages
        system = messages[0]
        budget = max(0, max_chars - len(str(system.content)))
        groups: list[list[Message]] = []
        index = 1
        while index < len(messages):
            message = messages[index]
            group = [message]
            index += 1
            if message.role == "assistant" and message.tool_calls:
                call_ids = {str(call.get("call_id")) for call in message.tool_calls}
                while index < len(messages) and messages[index].role == "tool" and messages[index].tool_call_id in call_ids:
                    group.append(messages[index])
                    index += 1
            groups.append(group)
        kept: list[Message] = []
        for group in reversed(groups):
            size = sum(len(str(item.content)) for item in group)
            if size > budget:
                continue
            kept[0:0] = group
            budget -= size
        return [system, *kept]


def _file_version(path: str | Path) -> tuple[int, int, str]:
    stat = Path(path).stat()
    return stat.st_mtime_ns, stat.st_size, _file_digest(path)


def _file_digest(path: str | Path) -> str:
    # Windows 文件时间粒度可能让同大小快速写入看起来未变化，因此保留内容摘要。
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
