"""The intentionally small agent orchestration loop."""

from __future__ import annotations

import time
from uuid import uuid4

from .context import Context
from .events import EventSink, NullEventSink
from .models import AgentEvent, AgentResult, ModelTurn
from .provider import Provider
from .session import Session
from .tools import ToolExecutor


class Agent:
    def __init__(
        self,
        provider: Provider,
        *,
        context: Context | None = None,
        tools: ToolExecutor | None = None,
        events: EventSink | None = None,
        max_turns: int = 8,
    ):
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.provider = provider
        self.context = context or Context()
        self.tools = tools or ToolExecutor()
        self.events = events or NullEventSink()
        self.max_turns = max_turns

    def run(self, task: str, session: Session | None = None) -> AgentResult:
        if not task.strip():
            raise ValueError("task must not be empty")
        session = session or Session()
        run_id = f"run_{uuid4().hex}"
        started = time.monotonic()
        session.add_user(task)
        # Trace metadata keeps size and correlation, not the raw request, so a
        # pasted credential cannot become part of the default run artifact.
        self._emit("agent_start", run_id, data={"task_chars": len(task)})
        tool_count = 0
        last_text = ""

        for turn_number in range(1, self.max_turns + 1):
            turn_id = f"turn_{turn_number}"
            self._emit("turn_start", run_id, turn_id=turn_id, data={"number": turn_number})
            messages = self.context.build(session)
            self._emit(
                "context_built",
                run_id,
                turn_id=turn_id,
                data={
                    "message_count": len(messages),
                    "prompt_chars": sum(len(str(message.content)) for message in messages),
                },
            )
            self._emit("model_request", run_id, turn_id=turn_id, data={"message_count": len(messages)})
            turn = self.provider.complete(messages, self.tools.specs())
            self._emit(
                "model_response",
                run_id,
                turn_id=turn_id,
                model_request_id=turn.request_id,
                data={"tool_calls": len(turn.tool_calls), "error": turn.error, "text": turn.text, "finish_reason": turn.finish_reason},
            )
            session.add_assistant(turn)
            if turn.is_error:
                return self._finish(session, run_id, "failed", turn.error or "model_error", last_text, turn_number, tool_count, started)
            last_text = turn.text
            if not turn.tool_calls:
                return self._finish(session, run_id, "completed", turn.finish_reason or "final_answer", last_text, turn_number, tool_count, started)

            for call in turn.tool_calls:
                tool_count += 1
                self._emit("tool_start", run_id, turn_id, turn.request_id, call.call_id, {"name": call.name})
                result = self.tools.execute(call)
                session.add_tool_result(result)
                self._emit(
                    "tool_end", run_id, turn_id, turn.request_id, call.call_id,
                    {"name": call.name, "ok": result.ok, "error": result.error, "exit_code": result.exit_code, "output": result.output},
                )
            self._emit("turn_end", run_id, turn_id=turn_id, data={"tool_calls": len(turn.tool_calls)})

        return self._finish(session, run_id, "stopped", "budget_exhausted", last_text, self.max_turns, tool_count, started)

    def _finish(self, session, run_id, status, reason, answer, turns, tool_count, started):
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        result = AgentResult(status, answer or "", reason, turns, tool_count, elapsed, session.session_id)
        self._emit("agent_end", run_id, data={"status": status, "stop_reason": reason, "elapsed_ms": elapsed})
        return result

    def _emit(self, event, run_id, turn_id=None, model_request_id=None, tool_call_id=None, data=None):
        self.events.emit(AgentEvent(event, run_id, turn_id, model_request_id, tool_call_id, data or {}))
