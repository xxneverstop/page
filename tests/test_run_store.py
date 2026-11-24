import json

import pytest

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.providers.clients import AnthropicCompatibleModelClient
from page.run_store import RunStore
from page.task_state import STOP_REASON_FINAL_ANSWER_RETURNED, TaskState


def build_workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_agent(tmp_path, outputs, **kwargs):
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".page" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return Page(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def test_run_store_creates_run_directory_and_state_file(tmp_path):
    store = RunStore(tmp_path / ".page" / "runs")
    state = TaskState.create(run_id="run_001", task_id="task_001", user_request="Inspect the repo.")

    run_dir = store.start_run(state)

    assert run_dir == store.run_dir(state.run_id)
    assert run_dir.exists()
    persisted = json.loads((run_dir / "task_state.json").read_text(encoding="utf-8"))
    assert persisted["task_id"] == "task_001"
    assert persisted["run_id"] == "run_001"
    assert persisted["user_request"] == "Inspect the repo."


def test_run_store_appends_trace_jsonl(tmp_path):
    store = RunStore(tmp_path / ".page" / "runs")
    state = TaskState.create(run_id="run_002", task_id="task_002", user_request="Trace the run.")
    store.start_run(state)

    store.append_trace(state, {"event": "run_started", "created_at": "2026-04-07T00:00:00+00:00"})
    store.append_trace(
        state.run_id,
        {
            "event": "prompt_built",
            "created_at": "2026-04-07T00:00:01+00:00",
            "prompt_metadata": {"prompt_chars": 128, "secret_env_count": 1},
        },
    )
    store.append_trace(state.run_id, {"event": "run_finished", "created_at": "2026-04-07T00:00:02+00:00"})

    lines = (store.trace_path(state.run_id)).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["event"] == "run_started"
    assert json.loads(lines[1])["event"] == "prompt_built"
    assert json.loads(lines[2])["event"] == "run_finished"


def test_run_store_writes_report_json(tmp_path):
    store = RunStore(tmp_path / ".page" / "runs")
    state = TaskState.create(run_id="run_003", task_id="task_003", user_request="Report the run.")
    store.start_run(state)
    state.finish_success("Done.")

    store.write_task_state(state)
    store.write_report(state, {"task_state": state.to_dict(), "stop_reason": state.stop_reason})

    report = json.loads(store.report_path(state.run_id).read_text(encoding="utf-8"))
    assert report["stop_reason"] == STOP_REASON_FINAL_ANSWER_RETURNED
    assert report["task_state"]["final_answer"] == "Done."


def test_run_store_tolerates_missing_final_report(tmp_path):
    store = RunStore(tmp_path / ".page" / "runs")
    state = TaskState.create(run_id="run_004", task_id="task_004", user_request="Crash before finalize.")

    store.start_run(state)
    store.append_trace(state, {"event": "run_started"})

    assert store.trace_path(state.run_id).exists()
    assert not store.report_path(state.run_id).exists()


def test_successful_run_persists_run_artifacts_and_stop_reason(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":2}}</tool>',
            "<final>Finished.</final>",
        ],
    )

    assert agent.ask("Do the thing") == "Finished."

    runs_root = tmp_path / ".page" / "runs"
    run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1

    run_dir = run_dirs[0]
    task_state = json.loads((run_dir / "task_state.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    trace_lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()

    assert task_state["task_id"] != task_state["run_id"]
    assert run_dir.name == task_state["run_id"]
    assert (run_dir / "task_state.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.json").exists()
    assert task_state["stop_reason"] == "final_answer_returned"
    assert task_state["final_answer"] == "Finished."
    assert report["stop_reason"] == "final_answer_returned"
    assert report["task_state"]["stop_reason"] == "final_answer_returned"
    assert report["run_id"] == task_state["run_id"]
    trace_events = [json.loads(line)["event"] for line in trace_lines]
    assert trace_events[0] == "run_started"
    assert trace_events[-1] == "run_finished"
    assert trace_events.count("prompt_built") == 2
    assert "tool_executed" in trace_events


def test_write_file_trace_records_minimum_tool_contract_fields(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"notes.txt","content":"hello\\n"}}</tool>',
            "<final>Done.</final>",
        ],
    )

    assert agent.ask("Create notes.txt") == "Done."

    trace_events = [
        json.loads(line)
        for line in agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines()
    ]
    tool_event = [event for event in trace_events if event["event"] == "tool_executed"][-1]

    assert tool_event["name"] == "write_file"
    assert tool_event["risk_level"] == "high"
    assert tool_event["read_only"] is False
    assert tool_event["tool_status"] == "ok"
    assert tool_event["affected_paths"] == ["notes.txt"]
    assert tool_event["workspace_changed"] is True
    assert tool_event["diff_summary"] == ["created:notes.txt"]


@pytest.mark.parametrize("trace_detail", [False, True])
def test_detailed_trace_shows_model_and_tool_round_trip(tmp_path, monkeypatch, trace_detail):
    file_text = "文件内容" * 160
    (tmp_path / "hello.txt").write_text(file_text, encoding="utf-8")
    tool_call = '<tool>{"name":"read_file","args":{"path":"hello.txt","end":1}}</tool>'
    replies = [json.dumps({"content": [{"type": "text", "text": text}]}) for text in (tool_call, "<final>完成</final>")]
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return replies[len(requests) - 1].encode("utf-8")

    def mock_http(request, timeout):
        requests.append(json.loads(request.data))
        return Response()

    # 用真实 Messages 适配器验证顺序和 HTTP 结构，网络请求由测试拦截。
    monkeypatch.setattr("urllib.request.urlopen", mock_http)
    monkeypatch.setenv("PAGE_TEST_API_KEY", "test-credential-in-user-message")
    agent = Page(
        model_client=AnthropicCompatibleModelClient("fake", "https://example.test", "private-header-key", 0.2, 10),
        workspace=build_workspace(tmp_path),
        session_store=SessionStore(tmp_path / ".page" / "sessions"),
        trace_detail=trace_detail,
    )
    question = "请读取 hello.txt\n" + "问题正文" * 90 + "\ntest-credential-in-user-message"
    assert agent.ask(question) == "完成"
    assert len(requests) == 2
    trace = agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8")
    assert "private-header-key" not in trace
    assert "test-credential-in-user-message" not in trace
    events = [json.loads(line) for line in trace.splitlines()]
    first = {event["event"]: event for event in reversed(events)}
    tool = first["tool_executed"]

    if not trace_detail:
        assert "prompt_rendered" not in first
        assert "model_http_request" not in first
        assert "model_extracted" not in first
        assert "tool_stage" not in first
        assert "payload" not in first["model_parsed"]
        assert "[truncated " in tool["result"]
        assert file_text not in tool["result"]
        return

    assert first["run_started"]["user_request"] == agent.redact_text(question)
    rendered = first["prompt_rendered"]
    assert rendered["tool_protocol"] == "text"
    assert rendered["section_order"][-1] == "current_request"
    assert rendered["prompt"] == agent.redact_text(requests[0]["messages"][0]["content"][0]["text"])
    assert first["model_http_response"]["body"] == replies[0]
    assert first["model_extracted"]["text"] == tool_call
    assert first["model_parsed"]["payload"] == {"name": "read_file", "args": {"path": "hello.txt", "end": 1}}
    assert file_text in tool["result"]
    assert file_text in requests[1]["messages"][0]["content"][0]["text"]
    order = [event["event"] for event in events]
    steps = ("prompt_rendered", "model_http_request", "model_http_response", "model_extracted", "model_parsed", "tool_requested", "tool_stage", "tool_executed")
    positions = [order.index(step) for step in steps]
    assert positions == sorted(positions)
