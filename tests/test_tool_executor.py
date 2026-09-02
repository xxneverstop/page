from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.tool_executor import ToolExecutor, ToolExecutionResult


def build_agent(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".page" / "sessions")
    return Page(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
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
