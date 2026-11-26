"""Run six deterministic coding contracts with independent verifiers."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.evaluation import EvaluationTask, evaluate, summarize
from core.models import ToolCall
from core.recovery import ActionJournal, make_resume_decision
from core.security import SecurityPolicy
from core.tools import ToolExecutor


def run_case(item: dict[str, object]):
    task_id = str(item["task_id"])
    root = Path(tempfile.mkdtemp(prefix=f"page-eval-{task_id}-"))
    policy = SecurityPolicy(root, allow_write=True, allow_shell=True)
    executor = ToolExecutor.for_workspace(root, policy=policy)
    state: dict[str, object] = {}
    if task_id == "read-symbol":
        (root / "sample.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
        state["read"] = executor.execute(ToolCall("read_file", {"path": "sample.py"}, "read-1"))
        verifier = lambda: state["read"].ok and "def entry" in state["read"].output
    elif task_id == "search-usage":
        (root / "a.py").write_text("entry()\n", encoding="utf-8")
        state["search"] = executor.execute(ToolCall("search", {"query": "entry"}, "search-1"))
        verifier = lambda: state["search"].ok and "a.py:1" in state["search"].output
    elif task_id == "write-small":
        state["write"] = executor.execute(ToolCall("write_file", {"path": "config.ini", "content": "enabled=true\n"}, "write-1"))
        verifier = lambda: state["write"].ok and (root / "config.ini").read_text(encoding="utf-8") == "enabled=true\n"
    elif task_id == "edit-small":
        (root / "value.txt").write_text("before\n", encoding="utf-8")
        state["edit"] = executor.execute(ToolCall("edit_file", {"path": "value.txt", "old": "before", "new": "after"}, "edit-1"))
        verifier = lambda: state["edit"].ok and (root / "value.txt").read_text(encoding="utf-8") == "after\n"
    elif task_id == "test-repair":
        failed = executor.execute(ToolCall("run_shell", {"command": "python -c \"raise SystemExit(1)\""}, "test-1"))
        passed = executor.execute(ToolCall("run_shell", {"command": "python -c \"raise SystemExit(0)\""}, "test-2"))
        state.update(failed=failed, passed=passed)
        verifier = lambda: state["failed"].exit_code == 1 and state["passed"].exit_code == 0
    else:
        journal = ActionJournal(root / "journal.jsonl")
        journal.append(tool="write_file", args={"path": "safe.txt"}, status="applied")
        state["decision"] = make_resume_decision(journal)
        verifier = lambda: bool(state["decision"]["can_resume"])
    return {"status": "completed", "tool_calls": len(state)}, verifier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("benchmarks/minimal_tasks.json"))
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    results = []
    for item in tasks:
        holder: dict[str, object] = {}
        def run(prompt: str, item=item):
            report, verifier = run_case(item)
            holder["verifier"] = verifier
            return report
        task = EvaluationTask(str(item["task_id"]), str(item["prompt"]), lambda: bool(holder["verifier"]()), tags=tuple(item.get("tags", [])))
        results.append(evaluate(task, run))
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))
    return 0 if all(item.verifier_passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
