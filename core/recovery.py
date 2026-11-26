"""Minimal checkpoint and action journal primitives for explicit resume."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class Checkpoint:
    session_id: str
    status: str
    turn_count: int
    tool_count: int
    budget_remaining: int | None = None
    last_call_id: str | None = None
    created_at: float = field(default_factory=time.time)
    schema_version: str = "checkpoint-v1"


class CheckpointStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, checkpoint: Checkpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(checkpoint), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass

    def load(self) -> Checkpoint | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return None
        try:
            return Checkpoint(**data)
        except (TypeError, ValueError):
            return None


class ActionJournal:
    """Append one identity per logical call; never infer identity from arguments."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, *, call_id: str | None = None, tool: str, args: Mapping[str, Any], status: str, **fields: Any) -> str:
        call_id = call_id or f"call_{uuid.uuid4().hex}"
        record = {"call_id": call_id, "tool": tool, "args": dict(args), "status": status, "timestamp": time.time(), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        return call_id

    def entries(self) -> list[dict[str, Any]]:
        result = []
        try:
            with self.path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict) and isinstance(value.get("call_id"), str):
                        result.append(value)
        except FileNotFoundError:
            pass
        return result

    def reconcile(self) -> dict[str, list[dict[str, Any]]]:
        entries = self.entries()
        return {
            "applied": [entry for entry in entries if entry.get("status") == "applied"],
            "retryable": [entry for entry in entries if entry.get("status") in {"failed", "rejected", "pending"}],
            "unknown": [entry for entry in entries if entry.get("status") == "unknown"],
        }


def make_resume_decision(journal: ActionJournal) -> dict[str, Any]:
    """Resume only known-safe entries; unknown side effects require review."""
    groups = journal.reconcile()
    return {"can_resume": not groups["unknown"], "groups": groups, "reason": "unknown_side_effect" if groups["unknown"] else "safe"}

