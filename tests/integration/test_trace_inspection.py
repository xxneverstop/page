"""Inspection model against kernel-generated FakeModel traces (deterministic)."""

import json

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from viewer.trace_model import build_inspection


def _build_agent(tmp_path, outputs, *, trace_detail):
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    return Page(
        model_client=FakeModelClient(outputs),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".page" / "sessions"),
        approval_policy="auto",
        trace_detail=trace_detail,
    )


def _inspect(agent):
    run_id = agent.current_task_state.run_id
    events = [
        json.loads(line)
        for line in agent.run_store.trace_path(run_id).read_text(encoding="utf-8").splitlines()
    ]
    report = json.loads(agent.run_store.report_path(run_id).read_text(encoding="utf-8"))
    state = agent.run_store.load_task_state(run_id)
    return build_inspection(run_id, events, report, state)


def test_detailed_fake_model_trace_keeps_turn_context_and_tool_associations(tmp_path):
    agent = _build_agent(tmp_path, [
        '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
        "<final>Done.</final>",
    ], trace_detail=True)

    assert agent.ask("Inspect hello.txt") == "Done."
    inspection = _inspect(agent)

    assert len(inspection["iterations"]) == 2
    assert [item["outcome"] for item in inspection["iterations"]] == ["tool", "final"]
    assert [item["status"] for item in inspection["iterations"]] == ["completed", "completed"]
    # 每轮 prompt_built + prompt_rendered 只产生一个完整快照。
    assert len(inspection["contexts"]) == 2
    assert inspection["contexts"][0]["prompt_event_id"]
    assert inspection["contexts"][0]["detail_available"] is True
    assert inspection["contexts"][0]["diff"]["available"] is False
    assert inspection["contexts"][1]["diff"]["available"] is True
    assert inspection["contexts"][1]["diff"]["text"] or inspection["contexts"][1]["diff"]["sections"]
    assert inspection["iterations"][0]["context_event_id"] == inspection["contexts"][0]["event_id"]

    tool = inspection["tools"][0]
    assert tool["status"] == "ok" and tool["execution"] == "executed"
    assert tool["request_event_id"] and tool["result_event_id"]
    assert tool["id"] in inspection["iterations"][0]["tool_call_ids"]
    assert tool["model_request_id"] == inspection["iterations"][0]["model_request_ids"][0]

    # 工具反馈进入下一轮 History 的证据来自真实 Runtime 元数据。
    assert tool["id"] in inspection["contexts"][1]["history_tool_call_ids"]
    assert inspection["contexts"][1]["history_tool_results"] == 1

    assert inspection["stats"]["model_calls"] == 2
    assert inspection["stats"]["tool_requested"] == 1
    assert inspection["stats"]["tool_executed"] == 1
    assert inspection["stats"]["http_attempts_known"] is False
    assert inspection["stats"]["usage"]["status"] == "unknown"
    assert inspection["evaluation"]["status"] == "unknown"
    assert inspection["iterations"][-1]["finished_outcome"] == "final"


def test_basic_fake_model_trace_still_exposes_tools_without_detail_bodies(tmp_path):
    agent = _build_agent(tmp_path, [
        '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
        "<final>Done.</final>",
    ], trace_detail=False)

    assert agent.ask("Inspect hello.txt") == "Done."
    inspection = _inspect(agent)

    assert len(inspection["iterations"]) == 2
    assert inspection["contexts"][0]["detail_available"] is False
    assert inspection["contexts"][0]["prompt_event_id"] == ""
    assert inspection["stats"]["tool_requested"] == 1
    assert inspection["stats"]["tool_executed"] == 1
    assert inspection["tools"][0]["result_event_id"]
    # 基础采集仍保留工具结果预览，但详细正文没有进入 Trace。
    assert inspection["run"]["detail_available"] is False


def test_model_failure_in_real_trace_is_failed_not_http_observed(tmp_path):
    agent = _build_agent(tmp_path, [], trace_detail=True)

    agent.ask("This will fail")

    inspection = _inspect(agent)

    assert inspection["run"]["status"] == "failed"
    assert inspection["iterations"][0]["outcome"] == "model_failed"
    assert inspection["iterations"][0]["status"] == "failed"
    assert inspection["models"][0]["status"] == "failed"
    assert inspection["models"][0]["failed_event_id"]
