from core.agent import Agent
from core.context import Context
from core.events import MemoryEventSink
from core.models import ModelTurn, ToolCall, ToolSpec
from core.provider import FakeProvider
from core.session import Session
from core.tools import RegisteredTool, ToolExecutor


def test_fake_provider_direct_answer_and_events():
    events = MemoryEventSink()
    agent = Agent(FakeProvider([ModelTurn(text="done")]), events=events)
    result = agent.run("say hello")
    assert result.status == "completed"
    assert result.answer == "done"
    assert [event.event for event in events.events] == [
        "agent_start", "turn_start", "context_built", "model_request", "model_response", "agent_end"
    ]


def test_multiple_tool_calls_are_serial_and_paired():
    order = []
    tools = ToolExecutor([
        RegisteredTool(ToolSpec("one"), lambda args: order.append("one") or "1"),
        RegisteredTool(ToolSpec("two"), lambda args: order.append("two") or "2"),
    ])
    provider = FakeProvider([
        ModelTurn(tool_calls=[ToolCall("one", {"x": 1}, "c1"), ToolCall("two", {}, "c2")]),
        ModelTurn(text="finished"),
    ])
    session = Session()
    result = Agent(provider, tools=tools, context=Context("system")).run("work", session)
    assert result.status == "completed"
    assert order == ["one", "two"]
    assert [message.tool_call_id for message in session.messages if message.role == "tool"] == ["c1", "c2"]
    assert len(provider.calls) == 2
    assert provider.calls[1][0][-2].tool_call_id == "c1"


def test_session_round_trip_is_atomic_and_structured(tmp_path):
    session = Session()
    session.add_user("inspect")
    session.save(tmp_path / "session.json")
    restored = Session.load(tmp_path / "session.json")
    assert restored.to_dict() == session.to_dict()
