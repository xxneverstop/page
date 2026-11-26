"""Small independent verifier harness used by M7 experiments."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    task_id: str
    prompt: str
    verifier: Callable[[], bool]
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class EvaluationResult:
    task_id: str
    agent_status: str
    verifier_passed: bool
    duration_s: float
    error: str = ""
    metrics: dict[str, float | int] = field(default_factory=dict)


def evaluate(task: EvaluationTask, run: Callable[[str], Mapping[str, object]]) -> EvaluationResult:
    started = time.perf_counter()
    try:
        report = dict(run(task.prompt))
        status = str(report.get("status", "unknown"))
        passed = bool(task.verifier())
        return EvaluationResult(task.task_id, status, passed, time.perf_counter() - started, metrics={k: v for k, v in report.items() if isinstance(v, (int, float))})
    except Exception as exc:  # verifier failures are evidence, not agent success
        return EvaluationResult(task.task_id, "failed", False, time.perf_counter() - started, error=f"{type(exc).__name__}: {exc}")


def summarize(results: list[EvaluationResult]) -> dict[str, object]:
    return {
        "tasks": len(results),
        "agent_completed": sum(result.agent_status == "completed" for result in results),
        "verifier_passed": sum(result.verifier_passed for result in results),
        "failed": sum(result.agent_status in {"failed", "stopped", "interrupted"} for result in results),
        "results": [result.__dict__ if hasattr(result, "__dict__") else {"task_id": result.task_id, "agent_status": result.agent_status, "verifier_passed": result.verifier_passed, "duration_s": result.duration_s, "error": result.error, "metrics": result.metrics} for result in results],
    }

