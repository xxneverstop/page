"""Event sinks for CLI, tests, and trace adapters."""

from __future__ import annotations

from collections.abc import Callable

from .models import AgentEvent


class EventSink:
    def emit(self, event: AgentEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NullEventSink(EventSink):
    def emit(self, event: AgentEvent) -> None:
        return None


class MemoryEventSink(EventSink):
    def __init__(self, callback: Callable[[AgentEvent], None] | None = None):
        self.events: list[AgentEvent] = []
        self.callback = callback

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)
        if self.callback is not None:
            self.callback(event)
