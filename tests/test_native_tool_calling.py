import json
from unittest.mock import patch

import pytest

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.providers.clients import AnthropicCompatibleModelClient, OpenAICompatibleModelClient
from page.providers.tool_calling import ModelResponse, ToolCall, openai_tool_calls
from page.evaluation.evaluator import BenchmarkEvaluator


TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    }
]


def test_native_agent_executes_tool_and_returns_plain_text(tmp_path):
    (tmp_path / "README.md").write_text("native\n", encoding="utf-8")
    client = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[ToolCall("call_1", "read_file", {"path": "README.md"})],
                continuation={"response_id": "resp_1"},
            ),
            ModelResponse(text="The file contains native."),
        ]
    )
    agent = Page(
        model_client=client,
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".page" / "sessions"),
        approval_policy="auto",
        tool_protocol="native",
    )

    answer = agent.ask("Read README.md")

    assert answer == "The file contains native."
    tool_event = next(item for item in agent.session["history"] if item["role"] == "tool")
    assert tool_event["call_id"] == "call_1"
    assert agent.session["native_tool_state"] == {}
    assert "structurally supplied tools" in client.prompts[0]


def test_native_multiple_calls_are_retried_without_partial_execution(tmp_path):
    (tmp_path / "README.md").write_text("native\n", encoding="utf-8")
    client = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("call_1", "read_file", {"path": "README.md"}),
                    ToolCall("call_2", "list_files", {}),
                ]
            ),
            ModelResponse(text="Stopped parallel execution safely."),
        ]
    )
    agent = Page(
        client,
        WorkspaceContext.build(tmp_path),
        SessionStore(tmp_path / ".page" / "sessions"),
        tool_protocol="native",
    )

    assert agent.ask("Try two calls") == "Stopped parallel execution safely."
    assert not any(item["role"] == "tool" for item in agent.session["history"])
    assert "parallel tool calls are not supported" in agent.session["history"][1]["content"]


def test_native_unknown_tool_still_uses_tool_executor_guard(tmp_path):
    client = FakeModelClient(
        [
            ModelResponse(tool_calls=[ToolCall("call_1", "delete_everything", {})]),
            ModelResponse(text="The unknown tool was rejected."),
        ]
    )
    agent = Page(
        client,
        WorkspaceContext.build(tmp_path),
        SessionStore(tmp_path / ".page" / "sessions"),
        tool_protocol="native",
    )

    assert agent.ask("Use an unknown tool") == "The unknown tool was rejected."
    tool_event = next(item for item in agent.session["history"] if item["role"] == "tool")
    assert tool_event["metadata"]["tool_error_code"] == "unknown_tool"


def test_native_openai_arguments_reject_malformed_json():
    with pytest.raises(ValueError, match="malformed JSON"):
        openai_tool_calls(
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": "{bad",
                    }
                ]
            }
        )


def test_openai_native_tool_call_and_observation_payloads():
    captured = []
    responses = [
        {
            "id": "resp_1",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": json.dumps({"path": "README.md"}),
                }
            ],
        },
        {"id": "resp_2", "output_text": "done"},
    ]

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses.pop(0))

    client = OpenAICompatibleModelClient("gpt-test", "https://api.openai.com/v1", "key", 0, 30)
    with patch("urllib.request.urlopen", fake_urlopen):
        first = client.complete("prompt", 50, tools=TOOL_DEFINITIONS)
        second = client.complete(
            "ignored continuation prompt",
            50,
            tools=TOOL_DEFINITIONS,
            observations=[{"call_id": "call_1", "name": "read_file", "content": "native", "is_error": False}],
            continuation=first.continuation,
        )

    assert first.tool_calls[0].arguments == {"path": "README.md"}
    assert captured[0]["tools"][0]["type"] == "function"
    assert captured[1]["previous_response_id"] == "resp_1"
    assert captured[1]["input"] == [
        {"type": "function_call_output", "call_id": "call_1", "output": "native"}
    ]
    assert second.text == "done"


def test_anthropic_native_tool_call_and_observation_payloads():
    captured = []
    responses = [
        {
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "README.md"}}
            ]
        },
        {"content": [{"type": "text", "text": "done"}]},
    ]

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses.pop(0))

    client = AnthropicCompatibleModelClient("claude-test", "https://api.anthropic.com/v1", "key", 0, 30)
    with patch("urllib.request.urlopen", fake_urlopen):
        first = client.complete("prompt", 50, tools=TOOL_DEFINITIONS)
        second = client.complete(
            "ignored continuation prompt",
            50,
            tools=TOOL_DEFINITIONS,
            observations=[{"call_id": "toolu_1", "name": "read_file", "content": "native", "is_error": False}],
            continuation=first.continuation,
        )

    assert first.tool_calls[0].name == "read_file"
    assert captured[0]["tools"][0]["input_schema"]["type"] == "object"
    assert captured[1]["messages"][-1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "native",
        "is_error": False,
    }
    assert second.text == "done"


def test_checkpoint_identity_detects_tool_protocol_change(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".page" / "sessions")
    first = Page(FakeModelClient(["<final>done</final>"]), workspace, store, tool_protocol="text")
    first.ask("finish")

    resumed = Page.from_session(
        FakeModelClient([]),
        workspace,
        store,
        first.session["id"],
        tool_protocol="native",
    )

    assert resumed.resume_state["status"] == "workspace-mismatch"
    assert "tool_protocol" in resumed.resume_state["runtime_identity_mismatch_fields"]


def test_evaluator_filters_tasks_repeats_and_records_protocol(tmp_path):
    artifact = tmp_path / "benchmark.json"
    evaluator = BenchmarkEvaluator(
        benchmark_path="benchmarks/coding_tasks.json",
        artifact_path=artifact,
        workspace_root=tmp_path / "workspaces",
        task_ids=["readme_intro_locked"],
        repetitions=2,
        tool_protocol="text",
        max_total_runs=2,
    )

    payload = evaluator.run()

    assert payload["benchmark"]["task_count"] == 1
    assert payload["benchmark"]["run_count"] == 2
    assert payload["reproducibility"]["tool_protocol"] == "text"
    assert [row["repetition"] for row in payload["rows"]] == [1, 2]
    assert all(row["tool_signature"] for row in payload["rows"])


def test_evaluator_enforces_total_run_cap(tmp_path):
    evaluator = BenchmarkEvaluator(
        benchmark_path="benchmarks/coding_tasks.json",
        artifact_path=tmp_path / "benchmark.json",
        workspace_root=tmp_path / "workspaces",
        task_ids=["readme_intro_locked"],
        repetitions=2,
        max_total_runs=1,
    )

    try:
        evaluator.run()
    except ValueError as exc:
        assert "exceeds max_total_runs=1" in str(exc)
    else:
        raise AssertionError("expected max_total_runs guard to fail")
