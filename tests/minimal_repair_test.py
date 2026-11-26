from core.agent import Agent
from core.models import ModelTurn, ToolCall
from core.provider import FakeProvider
from core.security import SecurityPolicy
from core.tools import ToolExecutor


def test_failed_command_is_returned_and_agent_can_continue(tmp_path):
    policy = SecurityPolicy(tmp_path, allow_shell=True)
    tools = ToolExecutor.for_workspace(tmp_path, policy=policy)

    def decide(messages, specs):
        tool_messages = [message for message in messages if message.role == "tool"]
        if not tool_messages:
            return ModelTurn(tool_calls=[ToolCall("run_shell", {"command": "python -c \"raise SystemExit(2)\""}, "bad")])
        assert "exit_code=2" in str(tool_messages[-1].content)
        return ModelTurn(text="observed failure and continued")

    result = Agent(FakeProvider(handler=decide), tools=tools).run("run and inspect")
    assert result.status == "completed"
    assert result.tool_calls == 1
