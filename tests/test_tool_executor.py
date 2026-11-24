from unittest.mock import patch

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.task_state import TaskState
from page.tool_executor import ToolExecutor, ToolExecutionResult


def build_agent(tmp_path, outputs=None, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".page" / "sessions")
    return Page(
        model_client=FakeModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def test_tool_executor_returns_content_and_metadata_without_side_channel(tmp_path):
    agent = build_agent(tmp_path)

    result = ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert isinstance(result, ToolExecutionResult)
    assert "# README.md" in result.content
    assert result.metadata["tool_status"] == "ok"
    assert result.metadata["read_only"] is True
    assert result.metadata["workspace_changed"] is False


def test_pico_run_tool_keeps_compatibility_metadata(tmp_path):
    agent = build_agent(tmp_path)

    content = agent.run_tool("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert "# README.md" in content


def test_repeated_read_reuses_latest_result_without_touching_workspace(tmp_path):
    agent = build_agent(tmp_path)
    args = {"path": "README.md", "start": 1, "end": 1}
    for _ in range(2):
        result = agent.execute_tool("read_file", args)
        agent.record({"role": "tool", "name": "read_file", "args": args, "content": result.content})

    cached = agent.execute_tool("read_file", args)

    assert "# README.md" in cached.content
    assert cached.metadata["deduplicated_read"] is True
    assert cached.metadata["recovery_action"] == "cached_read"
    assert agent._last_tool_result_metadata["tool_status"] == "ok"


def test_invalid_risky_tool_does_not_prompt_for_approval(tmp_path):
    agent = build_agent(tmp_path, [], approval_policy="ask")
    agent.trace_detail = True
    agent.current_task_state = TaskState.create("run_invalid", "task_invalid", "Write a file")

    with patch("builtins.input") as mock_input, patch.object(agent, "emit_trace") as trace:
        result = agent.run_tool("write_file", {})

    assert result.startswith("error: invalid arguments for write_file: 'path'")
    assert 'example: <tool name="write_file"' in result
    mock_input.assert_not_called()
    trace.assert_not_called()


def test_detailed_stages_precede_approval_and_execution(tmp_path):
    agent = build_agent(tmp_path, [], approval_policy="ask")
    agent.trace_detail = True
    agent.current_task_state = TaskState.create("run_stages", "task_stages", "Write a file")
    stages = []

    def approve(name, args):
        assert stages == ["validated", "approval_requested"]
        return True

    def write(args):
        assert stages == ["validated", "approval_requested", "approval_granted", "executing"]
        return "written"

    with patch.object(agent, "emit_trace", side_effect=lambda state, event, payload: stages.append(payload["stage"])) as trace:
        with patch.object(agent, "approve", side_effect=approve), patch.dict(agent.tools["write_file"], {"run": write}):
            result = agent.execute_tool("write_file", {"path": "example.txt", "content": "demo"})

    assert result.metadata["tool_status"] == "ok"
    assert all(call.args[0] is agent.current_task_state and call.args[1] == "tool_stage" for call in trace.call_args_list)
    assert trace.call_args_list[1].args[2] == {"name": "write_file", "stage": "approval_requested", "approval": "ask"}


def test_detailed_denied_approval_does_not_execute(tmp_path):
    agent = build_agent(tmp_path, [], approval_policy="never")
    agent.trace_detail = True
    agent.current_task_state = TaskState.create("run_denied", "task_denied", "Write a file")

    with patch.object(agent, "emit_trace") as trace:
        result = agent.execute_tool("write_file", {"path": "example.txt", "content": "demo"})

    assert [call.args[2]["stage"] for call in trace.call_args_list] == ["validated", "approval_requested", "approval_denied"]
    assert result.metadata["tool_error_code"] == "approval_denied"
    assert not (tmp_path / "example.txt").exists()


def test_detailed_safe_tool_has_no_approval_and_requires_active_run(tmp_path):
    agent = build_agent(tmp_path)
    agent.trace_detail = True

    with patch.object(agent, "emit_trace") as trace, patch.object(agent, "approve") as approve:
        agent.execute_tool("list_files", {"path": "."})
        trace.assert_not_called()

        agent.current_task_state = TaskState.create("run_safe", "task_safe", "List files")
        agent.execute_tool("list_files", {"path": "."})
        assert [call.args[2]["stage"] for call in trace.call_args_list] == ["validated", "executing"]
        approve.assert_not_called()

        trace.reset_mock()
        agent.trace_detail = False
        agent.execute_tool("list_files", {"path": "."})
        trace.assert_not_called()


def test_repeated_identical_tool_call_is_rejected(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "1"})
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "2"})

    result = agent.run_tool("list_files", {})

    assert result == "error: repeated identical tool call for list_files; choose a different tool or return a final answer"


def test_run_shell_nonzero_with_workspace_change_is_recorded_as_partial_success(tmp_path):
    agent = build_agent(tmp_path, [])

    result = agent.run_tool(
        "run_shell",
        {
            "command": "printf 'changed\\n' > README.md && exit 1",
            "timeout": 20,
        },
    )

    assert "exit_code: 1" in result
    assert agent._last_tool_result_metadata["tool_status"] == "partial_success"
    assert agent._last_tool_result_metadata["affected_paths"] == ["README.md"]
    assert agent._last_tool_result_metadata["workspace_changed"] is True
