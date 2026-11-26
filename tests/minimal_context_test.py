from core.context import Context
from core.models import Message, ModelTurn, ToolCall
from core.session import Session


def test_context_budget_keeps_system_and_recent_tool_pair():
    session = Session()
    session.add_user("inspect")
    session.add_assistant(ModelTurn(tool_calls=[ToolCall("read_file", {"path": "a"}, "c1")]))
    from core.models import ToolResult
    session.add_tool_result(ToolResult("c1", "read_file", True, "source"))
    context = Context("system", max_messages=2, max_chars=100)
    messages = context.build(session)
    assert messages[0].role == "system"
    assert any(message.tool_call_id == "c1" for message in messages)


def test_context_file_freshness_detects_change(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one", encoding="utf-8")
    context = Context()
    context.record_file_version(path)
    assert context.is_file_fresh(path)
    path.write_text("two", encoding="utf-8")
    assert not context.is_file_fresh(path)
