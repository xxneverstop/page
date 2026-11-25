from viewer.trace_model import build_inspection, normalize_events


def _context(chars, history_chars):
    return {
        "prompt_chars": chars,
        "prompt_budget_chars": 1000,
        "token_estimate": chars // 4,
        "token_estimate_method": "chars_div_4",
        "section_order": ["prefix", "history", "current_request"],
        "sections": {
            "prefix": {"raw_chars": 100, "rendered_chars": 100, "budget_chars": 200},
            "history": {"raw_chars": history_chars, "rendered_chars": history_chars, "budget_chars": 500},
            "current_request": {"raw_chars": 20, "rendered_chars": 20, "budget_chars": None},
        },
        "budget_reductions": [],
    }


def test_inspection_groups_iterations_http_retries_and_tool_lifecycle():
    events = [
        {"event": "run_started", "created_at": "2026-11-25T00:00:00+00:00", "task_id": "task_1", "user_request": "inspect"},
        {"event": "prompt_built", "created_at": "2026-11-25T00:00:01+00:00", "prompt_metadata": _context(500, 100)},
        {"event": "model_requested", "created_at": "2026-11-25T00:00:02+00:00", "attempts": 1},
        {"event": "model_http_request", "created_at": "2026-11-25T00:00:02+00:00", "attempt": 1, "url": "https://example.test"},
        {"event": "model_http_error", "created_at": "2026-11-25T00:00:03+00:00", "attempt": 1, "error": "timeout"},
        {"event": "model_http_request", "created_at": "2026-11-25T00:00:04+00:00", "attempt": 2, "url": "https://example.test"},
        {"event": "model_http_response", "created_at": "2026-11-25T00:00:05+00:00", "attempt": 2, "status": 200, "body": "{}"},
        {"event": "model_parsed", "created_at": "2026-11-25T00:00:06+00:00", "kind": "tool", "tool_name": "read_file"},
        {"event": "tool_requested", "created_at": "2026-11-25T00:00:07+00:00", "name": "read_file", "args": {"path": "README.md"}},
        {"event": "tool_stage", "created_at": "2026-11-25T00:00:08+00:00", "name": "read_file", "stage": "validated"},
        {"event": "tool_executed", "created_at": "2026-11-25T00:00:09+00:00", "name": "read_file", "tool_status": "ok", "result": "text"},
        {"event": "prompt_built", "created_at": "2026-11-25T00:00:10+00:00", "prompt_metadata": _context(650, 250)},
        {"event": "model_requested", "created_at": "2026-11-25T00:00:11+00:00", "attempts": 2},
        {"event": "model_parsed", "created_at": "2026-11-25T00:00:12+00:00", "kind": "final", "answer_preview": "done"},
        {"event": "run_finished", "created_at": "2026-11-25T00:00:13+00:00", "status": "completed", "stop_reason": "final_answer_returned"},
    ]

    result = build_inspection("run_1", events, {"status": "completed", "task_id": "task_1"})

    assert result["run"]["status"] == "completed"
    assert len(result["iterations"]) == 2
    assert result["iterations"][0]["outcome"] == "tool"
    assert result["iterations"][1]["outcome"] == "final"
    assert len(result["models"]) == 2
    assert result["models"][0]["iteration_id"] != result["models"][1]["iteration_id"]
    assert len(result["models"][0]["http_attempts"]) == 4
    assert len(result["tools"]) == 1
    assert result["tools"][0]["status"] == "ok"
    assert result["stats"]["model_calls"] == 2
    assert result["stats"]["http_attempts"] == 4
    assert result["contexts"][1]["diff"]["available"] is True
    assert any(item["name"] == "history" for item in result["contexts"][1]["diff"]["sections"])


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
