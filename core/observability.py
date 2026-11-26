"""Small event and run-artifact layer used by the minimal agent.

The agent core emits structured dictionaries; this module owns persistence so
the control loop does not know the Viewer wire format.  JSONL is deliberately
append-only and each JSON document is replaced atomically when finalized.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


class EventSink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None: ...


class NullEventSink:
    """Drop events for callers that do not need a trace."""

    def emit(self, event: Mapping[str, Any]) -> None:
        return None


@dataclass(slots=True)
class RunArtifacts:
    run_id: str
    root: Path
    trace_path: Path
    state_path: Path
    report_path: Path

    @classmethod
    def create(cls, root: str | Path, run_id: str) -> "RunArtifacts":
        run_root = Path(root).expanduser().resolve() / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        return cls(run_id, run_root, run_root / "trace.jsonl", run_root / "task_state.json", run_root / "report.json")


class TraceWriter:
    """Write bounded, correlated event records for CLI and Viewer consumers."""

    schema_version = "page-trace-v3"

    def __init__(self, artifacts: RunArtifacts, *, run_id: str | None = None):
        self.artifacts = artifacts
        self.run_id = run_id or artifacts.run_id
        self.started_at = time.time()
        self._turn = 0

    def emit(self, event: Mapping[str, Any] | str | Any, **fields: Any) -> dict[str, Any]:
        if isinstance(event, str):
            record: dict[str, Any] = {"event": event, **fields}
        elif hasattr(event, "to_dict"):
            record = dict(event.to_dict())
            data = record.get("data")
            if isinstance(data, Mapping):
                for key, value in data.items():
                    record.setdefault(key, value)
            record.update(fields)
        else:
            record = dict(event)
            record.update(fields)
            record.setdefault("event", "unknown")
        # AgentEvent keeps optional fields under ``data``; flatten them for the
        # legacy Viewer while retaining the nested payload for replay clients.
        data = record.get("data")
        if isinstance(data, Mapping):
            for key, value in data.items():
                record.setdefault(str(key), value)
        record.setdefault("schema_version", self.schema_version)
        record.setdefault("run_id", self.run_id)
        record.setdefault("timestamp", time.time())
        if "turn_id" not in record and record["event"] == "turn_start":
            self._turn += 1
            record["turn_id"] = f"turn_{self._turn}"
        self.artifacts.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.artifacts.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(_json_safe(record), ensure_ascii=False, allow_nan=False) + "\n")
        return record

    def write_state(self, state: Mapping[str, Any]) -> None:
        _atomic_json(self.artifacts.state_path, dict(state))

    def write_report(self, report: Mapping[str, Any]) -> None:
        _atomic_json(self.artifacts.report_path, dict(report))

    def finish(self, *, status: str, stop_reason: str = "", **fields: Any) -> None:
        elapsed = max(0.0, time.time() - self.started_at)
        state = {"run_id": self.run_id, "status": status, "stop_reason": stop_reason, "duration_s": elapsed, **fields}
        self.emit("agent_end", status=status, stop_reason=stop_reason)
        self.write_state(state)
        self.write_report({**state, "schema_version": "page-report-v1"})


class ViewerTraceAdapter:
    """Map v3 events to the legacy viewer's permissive page-trace-v2 shape."""

    def __init__(self, *, output_schema: str = "page-trace-v2"):
        self.output_schema = output_schema

    def adapt(self, event: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(event)
        value["schema_version"] = self.output_schema
        value.setdefault("category", _category(value.get("event", "")))
        return value

    def adapt_lines(self, events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self.adapt(event) for event in events]


def _category(name: str) -> str:
    if name.startswith("tool_"):
        return "tool"
    if name.startswith("model_"):
        return "model"
    if name.startswith("context"):
        return "context"
    if name.startswith("recovery") or name.startswith("checkpoint"):
        return "recovery"
    return "agent"


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(_json_safe(value), stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass

