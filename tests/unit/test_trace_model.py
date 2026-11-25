import pytest

from viewer.trace_model import build_inspection, diff_contexts, normalize_events


def _context(chars, history_chars, *, budget=1000, reductions=None, recovery=None):
    return {
        "prompt_chars": chars,
        "prompt_budget_chars": budget,
        "token_estimate": chars // 4,
        "token_estimate_method": "chars_div_4",
        "section_order": ["prefix", "history", "current_request"],
        "sections": {
            "prefix": {"raw_chars": 100, "rendered_chars": 100, "budget_chars": 200},
            "history": {"raw_chars": history_chars, "rendered_chars": history_chars, "budget_chars": 500},
            "current_request": {"raw_chars": 20, "rendered_chars": 20, "budget_chars": None},
        },
        "budget_reductions": list(reductions or []),
        "recovery_decision": dict(recovery or {}),
    }


def _detailed_events(prompts, histories):
    """Build a runtime-shaped detailed trace: one prompt_built + prompt_rendered per turn."""
    events = [
        {"event": "run_started", "created_at": "2026-11-25T00:00:00+00:00", "task_id": "task_1", "user_request": "inspect"},
    ]
    stamp = 1
    for number, (prompt, history) in enumerate(zip(prompts, histories), start=1):
        events.append({"event": "iteration_started", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number})
        stamp += 1
        events.append({
            "event": "prompt_built",
            "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00",
            "iteration": number,
            "prompt_metadata": _context(len(prompt), history),
        })
        stamp += 1
        events.append({
            "event": "prompt_rendered",
            "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00",
            "iteration": number,
            "prompt": prompt,
            "sections": _context(len(prompt), history)["sections"],
            "section_order": ["prefix", "history", "current_request"],
        })
        stamp += 1
        events.append({"event": "model_requested", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number, "attempts": number})
        stamp += 1
        kind = "final" if number == len(prompts) else "tool"
        events.append({"event": "model_parsed", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number, "kind": kind, "tool_name": "read_file" if kind == "tool" else ""})
        stamp += 1
        if kind == "tool":
            events.append({"event": "tool_requested", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number, "name": "read_file", "args": {"path": "README.md"}})
            stamp += 1
            events.append({"event": "tool_stage", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number, "name": "read_file", "stage": "validated"})
            stamp += 1
            events.append({"event": "tool_executed", "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00", "iteration": number, "name": "read_file", "tool_status": "ok", "result": "text"})
            stamp += 1
        events.append({
            "event": "iteration_finished",
            "created_at": f"2026-11-25T00:00:{stamp:02d}+00:00",
            "iteration": number,
            "outcome": kind,
            "next_step": "context" if kind == "tool" else "run_finished",
        })
        stamp += 1
    events.append({"event": "run_finished", "created_at": "2026-11-25T00:01:00+00:00", "status": "completed", "stop_reason": "final_answer_returned", "final_answer": "done"})
    return events


def test_three_turn_contexts_keep_one_snapshot_per_turn_and_real_diffs():
    prompts = ["alpha\nbeta\n", "alpha\nbeta\ngamma\n", "alpha\ndelta\n"]
    events = _detailed_events(prompts, [100, 250, 400])

    result = build_inspection("run_ctx", events, {"status": "completed", "task_id": "task_1"})

    contexts = result["contexts"]
    assert len(contexts) == 3
    # prompt_rendered 是正文证据，prompt_built 是元数据证据：同一轮只应产生一个合并快照。
    assert [context["iteration"] for context in contexts] == [1, 2, 3]
    assert contexts[0]["diff"]["available"] is False
    assert contexts[1]["diff"]["available"] is True
    assert contexts[2]["diff"]["available"] is True
    changed = {item["name"]: item for item in contexts[1]["diff"]["sections"]}
    assert changed["history"]["delta_rendered_chars"] == 150
    assert "-beta" in contexts[2]["diff"]["text"] or "+delta" in contexts[2]["diff"]["text"]
    # 迭代引用必须指向 contexts 里的同一份快照。
    assert result["iterations"][0]["context_event_id"] == contexts[0]["event_id"]
    assert contexts[0]["prompt_event_id"]
    assert contexts[0]["detail_available"] is True


def test_prompt_rendered_does_not_overwrite_cross_turn_diff():
    events = _detailed_events(["a\n", "a\nb\n"], [100, 200])

    contexts = build_inspection("run_ctx", events)["contexts"]

    assert contexts[1]["diff"]["available"] is True
    assert contexts[1]["diff"]["sections"]


def test_diff_contexts_compares_any_two_snapshots():
    first = {"event_id": "e1", "iteration": 1, "iteration_id": "run:iteration:0001", **_context(100, 100)}
    third = {"event_id": "e3", "iteration": 3, "iteration_id": "run:iteration:0003", **_context(900, 900)}

    diff = diff_contexts(first, third, "same\nold\n", "same\nnew\n")

    assert diff["available"] is True
    assert {item["name"]: item["delta_rendered_chars"] for item in diff["sections"]}["history"] == 800
    assert "-old" in diff["text"] and "+new" in diff["text"]


def test_diff_truncation_flag_reflects_generated_lines(monkeypatch):
    import viewer.trace_model as model

    monkeypatch.setattr(model, "MAX_DIFF_LINES", 2)
    first = {"iteration": 1, **_context(10, 10)}
    second = {"iteration": 2, **_context(20, 20)}

    diff = diff_contexts(first, second, "a\nb\nc\n", "x\ny\nz\n")

    assert diff["text_truncated"] is True
    assert len(diff["text"].splitlines()) <= 2


def test_http_attempts_count_sends_not_request_response_error_events():
    events = [
        {"event": "run_started", "iteration": None},
        {"event": "iteration_started", "iteration": 1},
        {"event": "prompt_built", "iteration": 1, "prompt_metadata": _context(100, 10)},
        {"event": "model_requested", "iteration": 1, "attempts": 1},
        {"event": "model_http_request", "iteration": 1, "attempt": 1, "url": "https://example.test", "body": {"a": 1}},
        {"event": "model_http_error", "iteration": 1, "attempt": 1, "error": "timeout"},
        {"event": "model_http_request", "iteration": 1, "attempt": 2, "url": "https://example.test", "body": {"a": 1}},
        {"event": "model_http_response", "iteration": 1, "attempt": 2, "status": 200, "body": "{}"},
        {"event": "model_parsed", "iteration": 1, "kind": "final", "answer_preview": "done"},
        {"event": "iteration_finished", "iteration": 1, "outcome": "final"},
        {"event": "run_finished", "status": "completed"},
    ]

    result = build_inspection("run_http", events, {"status": "completed"})

    assert result["stats"]["http_attempts"] == 2
    assert result["stats"]["http_attempts_known"] is True
    request = result["models"][0]
    assert request["status"] == "final"
    assert [attempt["attempt"] for attempt in request["http"]] == [1, 2]
    assert request["http"][0]["request_event_id"]
    assert request["http"][0]["error_event_id"]
    assert request["http"][1]["response_event_id"]
    # 原文正文只保留在 raw 事件里一次，避免多处重复序列化。
    assert "body" not in request["http"][0]


def test_http_events_without_attempt_keep_separate_lifecycles():
    events = [
        {"event": "iteration_started", "iteration": 1},
        {"event": "model_requested", "iteration": 1, "attempts": 1},
        {"event": "model_http_request", "iteration": 1},
        {"event": "model_http_error", "iteration": 1, "error": "timeout"},
        {"event": "model_http_request", "iteration": 1},
        {"event": "model_http_response", "iteration": 1, "status": 200},
        {"event": "model_parsed", "iteration": 1, "kind": "final"},
    ]

    result = build_inspection("run_http_legacy", events)

    assert result["stats"]["http_attempts"] == 2
    assert result["models"][0]["http_sends"] == 2
    assert len(result["models"][0]["http"]) == 2
    assert result["models"][0]["http"][0]["error_event_id"]
    assert result["models"][0]["http"][1]["response_event_id"]


def test_model_failure_survives_http_observed_and_marks_turn_failed():
    events = [
        {"event": "iteration_started", "iteration": 1},
        {"event": "prompt_built", "iteration": 1, "prompt_metadata": _context(100, 10)},
        {"event": "model_requested", "iteration": 1, "attempts": 1},
        {"event": "model_http_request", "iteration": 1, "attempt": 1},
        {"event": "model_http_error", "iteration": 1, "attempt": 1, "error": "boom"},
        {"event": "model_failed", "iteration": 1, "error_type": "RuntimeError", "error": "boom"},
        {"event": "iteration_finished", "iteration": 1, "outcome": "model_failed"},
        {"event": "run_finished", "status": "failed"},
    ]

    result = build_inspection("run_fail", events, {"status": "failed"})

    assert result["models"][0]["status"] == "failed"
    assert result["iterations"][0]["outcome"] == "model_failed"
    assert result["iterations"][0]["status"] == "failed"
    assert result["run"]["status"] == "failed"


def test_tool_failure_is_not_overwritten_by_generic_tool_outcome():
    events = [
        {"event": "iteration_started", "iteration": 1},
        {"event": "prompt_built", "iteration": 1, "prompt_metadata": _context(100, 10)},
        {"event": "model_requested", "iteration": 1, "attempts": 1},
        {"event": "model_parsed", "iteration": 1, "kind": "tool", "tool_name": "write_file"},
        {"event": "tool_requested", "iteration": 1, "name": "write_file", "args": {"path": "a.txt"}},
        {"event": "tool_executed", "iteration": 1, "name": "write_file", "tool_status": "error", "tool_error_code": "tool_failed", "result": "error"},
        {"event": "iteration_finished", "iteration": 1, "outcome": "tool"},
    ]

    result = build_inspection("run_tool_fail", events, {"status": "failed"})

    assert result["iterations"][0]["status"] == "failed"
    assert result["iterations"][0]["outcome"] == "tool_error"
    assert result["stats"]["tool_failed"] == 1
    assert result["stats"]["tool_succeeded"] == 0


def test_tool_requested_executed_rejected_skipped_and_completed_are_distinct():
    events = [
        {"event": "iteration_started", "iteration": 1},
        {"event": "tool_requested", "iteration": 1, "name": "read_file", "args": {"path": "a"}},
        {"event": "tool_executed", "iteration": 1, "name": "read_file", "tool_status": "ok", "result": "text"},
        {"event": "tool_requested", "iteration": 1, "name": "write_file", "args": {"path": "b"}},
        {"event": "tool_executed", "iteration": 1, "name": "write_file", "tool_status": "rejected", "tool_error_code": "approval_denied"},
        {"event": "tool_requested", "iteration": 1, "name": "write_file", "args": {"path": "c"}},
        {"event": "tool_executed", "iteration": 1, "name": "write_file", "tool_status": "ok", "recovery_action": "skipped_duplicate", "action_id": "act_1"},
        {"event": "tool_requested", "iteration": 1, "name": "read_file", "args": {"path": "d"}},
        {"event": "tool_executed", "iteration": 1, "name": "read_file", "tool_status": "ok", "recovery_action": "cached_read", "result": "cached"},
    ]

    result = build_inspection("run_tools", events, {"status": "completed"})

    assert [tool["status"] for tool in result["tools"]] == ["ok", "rejected", "skipped", "skipped"]
    assert [tool["execution"] for tool in result["tools"]] == ["executed", "rejected", "skipped", "skipped"]
    stats = result["stats"]
    assert stats["tool_requested"] == 4
    assert stats["tool_executed"] == 4
    assert stats["tool_succeeded"] == 1
    assert stats["tool_rejected"] == 1
    assert stats["tool_skipped"] == 2
    assert stats["tool_failed"] == 0


def test_usage_reports_complete_partial_unknown_and_last_request_only():
    def request(number, metadata):
        return {"event": "model_parsed", "iteration": number, "kind": "final", "completion_metadata": metadata}

    def requested(number):
        return {"event": "model_requested", "iteration": number, "attempts": number}

    complete = build_inspection("run_usage", [
        {"event": "iteration_started", "iteration": 1},
        requested(1),
        request(1, {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
        {"event": "iteration_started", "iteration": 2},
        requested(2),
        request(2, {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}),
    ], {"status": "completed"})
    assert complete["stats"]["usage"]["status"] == "complete"
    assert complete["stats"]["usage"]["total_tokens"] == 40
    assert complete["stats"]["usage"]["calls_with_usage"] == 2

    partial = build_inspection("run_usage", [
        {"event": "iteration_started", "iteration": 1},
        requested(1),
        request(1, {"input_tokens": 10, "output_tokens": 5}),
        {"event": "iteration_started", "iteration": 2},
        requested(2),
        request(2, {}),
    ], {"status": "completed"})
    assert partial["stats"]["usage"]["status"] == "partial"
    assert partial["stats"]["usage"]["total_tokens"] == 15
    assert partial["stats"]["usage"]["calls_with_usage"] == 1

    unknown = build_inspection("run_usage", [
        {"event": "iteration_started", "iteration": 1},
        requested(1),
        request(1, {"prompt_cache_key": "k"}),
    ], {"status": "completed"})
    assert unknown["stats"]["usage"]["status"] == "unknown"
    assert unknown["stats"]["usage"]["total_tokens"] is None
    assert unknown["stats"]["usage"]["calls_with_usage"] == 0

    last_request = build_inspection("run_usage", [
        {"event": "iteration_started", "iteration": 1},
        requested(1),
        request(1, {}),
    ], {"status": "completed", "prompt_metadata": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}})
    assert last_request["stats"]["usage"]["status"] == "partial"
    assert last_request["stats"]["usage"]["scope"] == "last_request"
    assert last_request["stats"]["usage"]["total_tokens"] == 10


def test_final_answer_is_not_reported_as_verifier_pass():
    events = _detailed_events(["a\n", "a\nb\n"], [100, 200])

    result = build_inspection("run_final", events, {"status": "completed", "final_answer": "done"})

    assert result["evaluation"] == {"status": "unknown", "source": "not_recorded", "evidence": None}
    assert result["iterations"][-1]["outcome"] == "final"
    assert result["iterations"][-1]["status"] == "completed"


def test_legacy_snapshots_are_consolidated_per_turn_without_prompt_text():
    events = [
        {"event": "run_started"},
        {"event": "model_requested", "attempts": 1},
        {"event": "prompt_built", "prompt_metadata": _context(100, 10)},
        {"event": "model_parsed", "kind": "final"},
        {"event": "run_finished", "status": "completed"},
    ]

    result = build_inspection("run_legacy", events, None)

    assert len(result["contexts"]) == 1
    assert result["contexts"][0]["detail_available"] is False
    assert result["contexts"][0]["prompt_event_id"] == ""
    assert result["contexts"][0]["source"] == "viewer_inferred"


def test_normalize_legacy_trace_marks_inferred_identity_and_preserves_unknowns():
    events = normalize_events([
        {"event": "run_started"},
        {"event": "model_requested", "attempts": 1},
        {"event": "model_parsed", "kind": "retry"},
        {"event": "prompt_built", "prompt_metadata": {"prompt_chars": 10}},
        {"event": "model_requested", "attempts": 2},
    ], "run_legacy")

    assert events[1]["iteration_id"] == "run_legacy:iteration:0001"
    assert events[1]["iteration_source"] == "viewer_inferred"
    assert events[3]["iteration_id"] == "run_legacy:iteration:0002"
    assert events[4]["model_request_id"] == "run_legacy:model:0002"


def test_normalize_explicit_iteration_resets_legacy_model_association():
    events = normalize_events([
        {"event": "run_started"},
        {"event": "iteration_started", "iteration": 1},
        {"event": "prompt_built", "prompt_metadata": {"prompt_chars": 10}},
        {"event": "model_requested"},
        {"event": "model_parsed", "kind": "tool", "tool_name": "read_file"},
        {"event": "iteration_finished", "iteration": 1},
        {"event": "iteration_started", "iteration": 2},
        {"event": "prompt_built", "prompt_metadata": {"prompt_chars": 20}},
        {"event": "model_requested"},
        {"event": "model_parsed", "kind": "final", "answer_preview": "done"},
    ], "run_legacy")

    requests = build_inspection("run_legacy", events)["models"]
    assert [request["iteration"] for request in requests] == [1, 2]
    assert [request["iteration_id"] for request in requests] == [
        "run_legacy:iteration:0001",
        "run_legacy:iteration:0002",
    ]


def test_legacy_associations_keep_viewer_inferred_sources():
    result = build_inspection("run_legacy", [
        {"event": "run_started"},
        {"event": "iteration_started", "iteration": 1, "iteration_id": "run_legacy:iteration:0001"},
        {"event": "prompt_built", "prompt_metadata": {"prompt_chars": 10}},
        {"event": "model_requested"},
        {"event": "model_parsed", "kind": "tool", "tool_name": "read_file"},
        {"event": "tool_requested", "name": "read_file", "args": {"path": "README.md"}},
        {"event": "tool_executed", "name": "read_file", "tool_status": "ok", "result": "text"},
    ])

    assert result["iterations"][0]["source"] == "viewer_inferred"
    assert result["models"][0]["source"] == "viewer_inferred"
    assert result["tools"][0]["source"] == "viewer_inferred"
