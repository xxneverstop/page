"""Paired blind/guarded recovery experiments for the action journal."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..action_journal import InjectedCrash
from ..providers.clients import FakeModelClient
from ..runtime import Page
from ..session_store import SessionStore
from ..task_state import TaskState
from ..workspace import WorkspaceContext, now


RECOVERY_EXPERIMENT_TASKS = (
    "write_after_commit_crash",
    "patch_after_commit_crash",
    "stale_file_drift",
)


def _workspace(root):
    return WorkspaceContext.build(root, repo_root_override=root)


def _agent(root, model_client, session_id=None, **kwargs):
    store = SessionStore(Path(root) / ".page" / "sessions")
    if session_id:
        return Page.from_session(
            model_client,
            _workspace(root),
            store,
            session_id,
            approval_policy="auto",
            max_steps=5,
            max_new_tokens=1024,
            **kwargs,
        )
    return Page(
        model_client,
        _workspace(root),
        store,
        approval_policy="auto",
        max_steps=5,
        max_new_tokens=1024,
        **kwargs,
    )


def _direct_task(agent, task_id):
    state = TaskState.create(task_id=task_id, user_request=task_id, run_id=f"setup_{task_id}")
    agent.current_task_state = state
    return state


def _prepare_interrupted_workspace(root, task_id):
    root = Path(root)
    (root / "README.md").write_text("recovery fixture\n", encoding="utf-8", newline="")
    if task_id == "write_after_commit_crash":
        agent = _agent(root, FakeModelClient([]), fault_injection="after_tool_execution_before_commit")
        _direct_task(agent, task_id)
        try:
            agent.execute_tool("write_file", {"path": "result.txt", "content": "recovered-value\n"})
        except InjectedCrash:
            pass
        return agent.session["id"]

    if task_id == "patch_after_commit_crash":
        (root / "sample.txt").write_text("alpha\nplaceholder\n", encoding="utf-8", newline="")
        agent = _agent(root, FakeModelClient([]), fault_injection="after_tool_execution_before_commit")
        _direct_task(agent, task_id)
        try:
            agent.execute_tool(
                "patch_file",
                {"path": "sample.txt", "old_text": "placeholder", "new_text": "recovered"},
            )
        except InjectedCrash:
            pass
        return agent.session["id"]

    if task_id == "stale_file_drift":
        (root / "state.txt").write_text("alpha-state\n", encoding="utf-8", newline="")
        agent = _agent(
            root,
            FakeModelClient(
                [
                    '<tool>{"name":"read_file","args":{"path":"state.txt","start":1,"end":20}}</tool>',
                    "<final>alpha-state</final>",
                ]
            ),
        )
        agent.ask("Read state.txt and remember its exact state.")
        (root / "state.txt").write_text("beta-state\n", encoding="utf-8", newline="")
        return agent.session["id"]

    raise ValueError(f"unknown recovery experiment task: {task_id}")


def _fake_client(task_id):
    if task_id == "write_after_commit_crash":
        return FakeModelClient(
            [
                '<tool name="write_file" path="result.txt"><content>recovered-value\n</content></tool>',
                "<final>write recovery complete</final>",
            ]
        )
    if task_id == "patch_after_commit_crash":
        return FakeModelClient(
            [
                '<tool name="patch_file" path="sample.txt"><old_text>placeholder</old_text><new_text>recovered</new_text></tool>',
                "<final>patch recovery complete</final>",
            ]
        )
    return FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"state.txt","start":1,"end":20}}</tool>',
            "<final>beta-state</final>",
        ]
    )


def _prompt(task_id):
    if task_id == "write_after_commit_crash":
        return (
            "Continue the interrupted task. Ensure result.txt contains exactly recovered-value and one newline. "
            "Use tools if needed, then return a short final answer."
        )
    if task_id == "patch_after_commit_crash":
        return (
            "Continue the interrupted task. Ensure sample.txt contains recovered instead of placeholder exactly once. "
            "Use tools if needed, then return a short final answer."
        )
    return (
        "The workspace may have changed while the task was interrupted. Determine the exact current line in state.txt. "
        "Do not trust a stale summary. One successful read_file result in this resumed run is authoritative; "
        "after that read, do not call any more tools and reply with the exact line."
    )


def _trace_events(agent):
    path = agent.run_store.trace_path(agent.current_task_state.run_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _verify(root, task_id, answer):
    root = Path(root)
    if task_id == "write_after_commit_crash":
        return (root / "result.txt").read_text(encoding="utf-8") == "recovered-value\n"
    if task_id == "patch_after_commit_crash":
        text = (root / "sample.txt").read_text(encoding="utf-8")
        return text == "alpha\nrecovered\n" and "placeholder" not in text
    return "beta-state" in str(answer).lower()


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(path)


def run_recovery_experiment(
    artifact_path,
    repetitions=2,
    model_client_factory=None,
    model_label="fake",
    tasks=None,
    modes=None,
):
    rows = []
    repetitions = int(repetitions)
    task_ids = tuple(tasks or RECOVERY_EXPERIMENT_TASKS)
    variants_to_run = tuple(modes or ("blind", "guarded"))
    for repetition in range(repetitions):
        for task_id in task_ids:
            if task_id not in RECOVERY_EXPERIMENT_TASKS:
                raise ValueError(f"unknown recovery experiment task: {task_id}")
            for mode in variants_to_run:
                if mode not in {"blind", "guarded"}:
                    raise ValueError(f"unknown recovery experiment mode: {mode}")
                with tempfile.TemporaryDirectory(prefix="page-recovery-journal-") as temp_dir:
                    root = Path(temp_dir)
                    sid = _prepare_interrupted_workspace(root, task_id)
                    client = model_client_factory(task_id=task_id, mode=mode) if model_client_factory else _fake_client(task_id)
                    agent = _agent(root, client, session_id=sid, resume_mode=mode)
                    answer = agent.ask(_prompt(task_id))
                    events = _trace_events(agent)
                    journal = agent.action_journal.summary()
                    execution_count = sum(int(item.get("execution_count", 0)) for item in journal["items"])
                    skipped = sum(
                        1
                        for event in events
                        if event.get("event") == "tool_executed"
                        and event.get("recovery_action") == "skipped_duplicate"
                    )
                    reads = sum(
                        1
                        for event in events
                        if event.get("event") == "tool_executed" and event.get("name") == "read_file"
                    )
                    model_requests = sum(1 for event in events if event.get("event") == "model_requested")
                    completion_events = [event for event in events if event.get("event") == "model_parsed"]
                    input_tokens = sum(int(event.get("completion_metadata", {}).get("input_tokens") or 0) for event in completion_events)
                    output_tokens = sum(int(event.get("completion_metadata", {}).get("output_tokens") or 0) for event in completion_events)
                    total_tokens = sum(int(event.get("completion_metadata", {}).get("total_tokens") or 0) for event in completion_events)
                    stale_invalidations = max(
                        [
                            int(event.get("prompt_metadata", {}).get("stale_summary_invalidations", 0))
                            for event in events
                            if event.get("event") == "prompt_built"
                        ]
                        or [0]
                    )
                    row = {
                        "task_id": task_id,
                        "variant": f"{mode}_resume",
                        "repetition": repetition + 1,
                        "model": model_label,
                        "verifier_passed": _verify(root, task_id, answer),
                        "final_answer": answer,
                        "tool_steps": agent.current_task_state.tool_steps,
                        "attempts": agent.current_task_state.attempts,
                        "model_requests": model_requests,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "read_file_calls": reads,
                        "journal_execution_count": execution_count,
                        "skipped_duplicate_actions": skipped,
                        "manual_review_actions": len(agent.recovery_decision.get("manual_review_actions", [])),
                        "stale_summary_invalidations": stale_invalidations,
                        "resume_status": agent.last_prompt_metadata.get("resume_status", ""),
                        "recovery_decision": dict(agent.recovery_decision),
                        "stop_reason": agent.current_task_state.stop_reason,
                    }
                    rows.append(row)

    variants = {}
    for variant in ("blind_resume", "guarded_resume"):
        selected = [row for row in rows if row["variant"] == variant]
        variants[variant] = {
            "runs": len(selected),
            "verifier_passes": sum(1 for row in selected if row["verifier_passed"]),
            "verifier_pass_rate": sum(1 for row in selected if row["verifier_passed"]) / len(selected) if selected else 0.0,
            "journal_execution_count": sum(row["journal_execution_count"] for row in selected),
            "skipped_duplicate_actions": sum(row["skipped_duplicate_actions"] for row in selected),
            "model_requests": sum(row["model_requests"] for row in selected),
            "input_tokens": sum(row["input_tokens"] for row in selected),
            "output_tokens": sum(row["output_tokens"] for row in selected),
            "total_tokens": sum(row["total_tokens"] for row in selected),
            "tool_steps": sum(row["tool_steps"] for row in selected),
            "stale_summary_invalidations": sum(row["stale_summary_invalidations"] for row in selected),
        }
    payload = {
        "schema_version": "recovery-journal-experiment-v1",
        "captured_at": now(),
        "model": model_label,
        "task_count": len(task_ids),
        "repetitions": repetitions,
        "task_runs": len(rows),
        "variants": variants,
        "rows": rows,
    }
    _atomic_write_json(artifact_path, payload)
    return payload
