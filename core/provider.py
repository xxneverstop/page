"""Provider contracts plus a deterministic test provider."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Protocol

from .models import Message, ModelTurn, ToolCall, ToolSpec


class Provider(Protocol):
    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn: ...


class FakeProvider:
    """Return scripted turns, or compute one from the current message list."""

    def __init__(self, turns: Iterable[ModelTurn] | None = None, handler: Callable | None = None):
        self.turns = list(turns or [])
        self.handler = handler
        self.calls: list[tuple[list[Message], list[ToolSpec]]] = []

    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        self.calls.append((list(messages), list(tools)))
        if self.handler is not None:
            return self.handler(messages, tools)
        if not self.turns:
            return ModelTurn(error="FakeProvider has no scripted turn")
        return self.turns.pop(0)


class OpenAICompatibleProvider:
    """Small JSON adapter for chat-completions compatible endpoints.

    It intentionally uses urllib so the core stays dependency-free. Endpoint
    authentication and retries belong to the application layer.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        payload = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                }}
                for spec in tools
            ]
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return ModelTurn(error=f"provider request failed: {exc}")
        try:
            choice = body["choices"][0]
            message = choice["message"]
            calls = [
                ToolCall(
                    call_id=str(item.get("id") or ""),
                    name=item["function"]["name"],
                    arguments=_parse_arguments(item["function"].get("arguments", {})),
                )
                for item in message.get("tool_calls", [])
            ]
            return ModelTurn(
                text=message.get("content") or "",
                tool_calls=calls,
                usage=body.get("usage") or {},
                finish_reason=choice.get("finish_reason"),
            )
        except (KeyError, TypeError, IndexError, ValueError) as exc:
            return ModelTurn(error=f"invalid provider response: {exc}")


def _parse_arguments(arguments):
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        parsed = json.loads(arguments or "{}")
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("tool arguments must be a JSON object")
