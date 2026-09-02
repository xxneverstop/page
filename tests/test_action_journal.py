import json

import pytest

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.action_journal import InjectedCrash
from page.task_state import TaskState


def build_agent(tmp_path, outputs=None, session_id=None, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8") if not (tmp_path / "README.md").exists() else None
    workspace = WorkspaceContext.build(tmp_path, repo_root_override=tmp_path)
    store = SessionStore(tmp_path / ".page" / "sessions")
    if session_id:
        agent = Page.from_session(
            FakeModelClient(outputs or []),
            workspace,
            store,
            session_id,
            approval_policy="auto",
            **kwargs,
        )
    else:
        agent = Page(
            FakeModelClient(outputs or []),
            workspace,
            store,
            approval_policy="auto",
            **kwargs,
        )
    agent.current_task_state = TaskState.create(task_id="task_journal", user_request="journal test", run_id="run_journal")
    return agent


def session_id(agent):
    return agent.session["id"]


def only_action(agent):
    items = list(agent.action_journal.state["items"].values())
    assert len(items) == 1
    return items[0]


def test_successful_file_action_persists_full_lifecycle(tmp_path):
    agent = build_agent(tmp_path)

    result = agent.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})

    record = only_action(agent)
    assert result.metadata["action_id"] == record["action_id"]
    assert record["phase"] == "succeeded"
    assert record["before_hashes"] == {"result.txt": "missing"}
    assert record["after_hashes"]["result.txt"].startswith("sha256:")
    assert record["expected_after_hashes"] == record["after_hashes"]


def test_crash_before_tool_is_retryable_and_executes_once(tmp_path):
    agent = build_agent(tmp_path, fault_injection="before_tool_execution")
    sid = session_id(agent)

    with pytest.raises(InjectedCrash, match="before_tool_execution"):
        agent.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})

    assert not (tmp_path / "result.txt").exists()
    assert only_action(agent)["phase"] == "started"

    resumed = build_agent(tmp_path, session_id=sid)
    action = only_action(resumed)
    assert action["recovery_decision"] == "retry"

    result = resumed.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})
    assert result.metadata["tool_status"] == "ok"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "done\n"


def test_crash_after_file_write_reconciles_and_skips_duplicate(tmp_path):
    agent = build_agent(tmp_path, fault_injection="after_tool_execution_before_commit")
    sid = session_id(agent)

    with pytest.raises(InjectedCrash, match="after_tool_execution_before_commit"):
        agent.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})

    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "done\n"
    assert only_action(agent)["phase"] == "started"

    resumed = build_agent(tmp_path, session_id=sid)
    action = only_action(resumed)
    assert action["phase"] == "reconciled"
    assert action["action_id"] in resumed.recovery_decision["reconciled_actions"]

    result = resumed.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})
    assert result.metadata["recovery_action"] == "skipped_duplicate"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "done\n"


def test_external_drift_after_completed_action_requires_manual_review(tmp_path):
    agent = build_agent(tmp_path)
    sid = session_id(agent)
    agent.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})
    (tmp_path / "result.txt").write_text("external\n", encoding="utf-8")

    resumed = build_agent(tmp_path, session_id=sid)

    assert only_action(resumed)["phase"] == "manual-review-required"
    result = resumed.execute_tool("write_file", {"path": "result.txt", "content": "done\n"})
    assert result.metadata["tool_error_code"] == "manual_review_required"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "external\n"


def test_interrupted_shell_is_never_automatically_replayed(tmp_path):
    agent = build_agent(tmp_path, fault_injection="before_tool_execution")
    sid = session_id(agent)

    with pytest.raises(InjectedCrash):
        agent.execute_tool("run_shell", {"command": "echo hello", "timeout": 5})

    resumed = build_agent(tmp_path, session_id=sid)
    action = only_action(resumed)
    assert action["phase"] == "manual-review-required"
    assert action["decision_reason"] == "shell side effects cannot be proven safe to replay"


def test_schema_mismatch_refuses_new_mutation(tmp_path):
    agent = build_agent(tmp_path)
    sid = session_id(agent)
    agent.session["checkpoints"] = {
        "current_id": "ckpt_old",
        "items": {
            "ckpt_old": {
                "checkpoint_id": "ckpt_old",
                "schema_version": "legacy-v0",
                "key_files": [],
                "runtime_identity": agent.current_runtime_identity(),
            }
        },
    }
    agent.session_store.save(agent.session)

    resumed = build_agent(tmp_path, session_id=sid)

    assert resumed.resume_state["status"] == "schema-mismatch"
    assert resumed.recovery_decision["decision"] == "refuse"
    result = resumed.execute_tool("write_file", {"path": "blocked.txt", "content": "no\n"})
    assert result.metadata["tool_error_code"] == "manual_review_required"
    assert not (tmp_path / "blocked.txt").exists()


def test_action_journal_schema_mismatch_refuses_mutation(tmp_path):
    agent = build_agent(tmp_path)
    sid = session_id(agent)
    agent.session["action_journal"] = {"schema_version": "legacy-journal", "items": {}}
    agent.session_store.save(agent.session)

    resumed = build_agent(tmp_path, session_id=sid)

    assert resumed.recovery_decision["decision"] == "refuse"
    assert resumed.recovery_decision["reason"] == "action journal schema mismatch"
    result = resumed.execute_tool("write_file", {"path": "blocked.txt", "content": "no\n"})
    assert result.metadata["tool_error_code"] == "manual_review_required"
    assert not (tmp_path / "blocked.txt").exists()


def test_crash_after_checkpoint_keeps_resumable_checkpoint(tmp_path):
    agent = build_agent(
        tmp_path,
        outputs=["<final>first result</final>"],
        fault_injection="after_checkpoint_before_final",
    )
    sid = session_id(agent)

    with pytest.raises(InjectedCrash, match="after_checkpoint_before_final"):
        agent.ask("finish the task")

    checkpoint_id = agent.session["checkpoints"]["current_id"]
    assert checkpoint_id

    resumed = build_agent(tmp_path, outputs=["<final>resumed result</final>"], session_id=sid)
    assert resumed.current_checkpoint()["checkpoint_id"] == checkpoint_id
    assert resumed.ask("continue") == "resumed result"


def test_model_failure_writes_trace_and_report(tmp_path):
    class FailingModel(FakeModelClient):
        def complete(self, prompt, max_new_tokens, **kwargs):
            raise TimeoutError("provider timeout with secret-like value")

    workspace = WorkspaceContext.build(tmp_path, repo_root_override=tmp_path)
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    agent = Page(
        FailingModel([]),
        workspace,
        SessionStore(tmp_path / ".page" / "sessions"),
        approval_policy="auto",
    )

    answer = agent.ask("inspect the workspace")

    assert "TimeoutError" in answer
    report = agent.run_store.load_report(agent.current_task_state.run_id)
    assert report["status"] == "failed"
    assert report["stop_reason"] == "model_error"
    events = [
        json.loads(line)
        for line in agent.run_store.trace_path(agent.current_task_state.run_id).read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["event"] == "model_failed" for event in events)
