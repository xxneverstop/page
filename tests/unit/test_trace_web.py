import http.client
import io
import json
import os
from types import SimpleNamespace

import pytest

from viewer import server as trace_web


def _line(event):
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


@pytest.fixture
def web_viewer(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    server = SimpleNamespace(runs_dir=root, server_port=8765)

    class MemorySocket:
        def __init__(self, request):
            self.input = io.BytesIO(request)
            self.output = io.BytesIO()

        def makefile(self, mode, *args):
            return self.input

        def sendall(self, data):
            self.output.write(data)

    def fetch(path, headers=None):
        request_headers = {"Host": f"127.0.0.1:{server.server_port}", "Connection": "close"}
        request_headers.update(headers or {})
        request = f"GET {path} HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in request_headers.items()) + "\r\n"
        # 仍经过真实 HTTP handler 和响应解析，只把受沙箱限制的 socket 换成内存流。
        socket = MemorySocket(request.encode("ascii"))
        trace_web.TraceHandler(socket, ("127.0.0.1", 12345), server)
        response = http.client.HTTPResponse(MemorySocket(socket.output.getvalue()))
        try:
            response.begin()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            response.close()

    return root, server, fetch


def test_events_keep_partial_utf8_line_skip_damage_and_reset_after_truncation(tmp_path):
    path = tmp_path / "trace.jsonl"
    started = {"event": "run_started", "user_request": "中文问题"}
    legacy = {"event": "tool_executed", "result": "旧日志没有 run_id"}
    finished = {"event": "run_finished", "status": "completed"}
    prefix = (
        _line(started) + b"broken json\n[]\n"
        + b'{"event":"bad","value":NaN}\n{"event":"bad","value":1e999}\n'
        + _line(legacy)
    )
    pending = _line(finished)
    path.write_bytes(prefix + pending[:12])

    first = trace_web.read_events(path)

    assert first["events"] == [started, legacy]
    assert first["skipped"] == 4
    assert first["next_offset"] == len(prefix)
    assert first["has_more"] is False
    assert trace_web.read_events(path, first["next_offset"])["events"] == []
    with path.open("ab") as stream:
        stream.write(pending[12:])
    second = trace_web.read_events(path, first["next_offset"])
    assert second["events"] == [finished]
    assert second["next_offset"] == path.stat().st_size

    path.write_bytes(_line({"event": "run_started"}))
    restarted = trace_web.read_events(path, second["next_offset"])
    assert restarted["reset"] is True
    assert restarted["events"] == [{"event": "run_started"}]


def test_events_are_batched_without_losing_or_repeating_records(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    events = [{"event": "model_requested", "attempts": number} for number in range(5)]
    path.write_bytes(b"".join(_line(event) for event in events))
    monkeypatch.setattr(trace_web, "MAX_RECORDS", 2)

    first = trace_web.read_events(path)
    second = trace_web.read_events(path, first["next_offset"])
    third = trace_web.read_events(path, second["next_offset"])

    assert first["events"] + second["events"] + third["events"] == events
    assert [first["has_more"], second["has_more"], third["has_more"]] == [True, True, False]


def test_runs_use_redacted_trace_prompt_and_do_not_claim_stale_runs_are_live(web_viewer):
    root, _, fetch = web_viewer
    old = root / "run_old"
    old.mkdir()
    (old / "trace.jsonl").write_bytes(_line({"event": "run_started", "user_request": "<redacted> 的问题"}))
    (old / "task_state.json").write_text(json.dumps({
        "status": "running", "user_request": "RAW_SECRET", "final_answer": "RAW_FINAL",
        "provider": "RAW_PROVIDER", "attempts": 2, "tool_steps": 1,
    }), encoding="utf-8")
    latest = root / "run_new"
    latest.mkdir()
    report = {"status": "completed", "provider": "fake", "model": "offline", "stop_reason": "final_answer_returned"}
    (latest / "report.json").write_text(json.dumps(report), encoding="utf-8")
    for path in [old, *old.iterdir()]:
        os.utime(path, (100, 100))

    status, headers, body = fetch("/api/runs")
    data = json.loads(body)

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert data["total"] == 2
    assert [run["id"] for run in data["runs"]] == ["run_new", "run_old"]
    old_run = data["runs"][1]
    assert old_run["prompt"] == "<redacted> 的问题"
    assert old_run["status"] == "unknown"
    assert old_run["attempts"] == 2 and old_run["tool_steps"] == 1
    assert old_run["provider"] == ""
    assert b"RAW_" not in body
    assert json.loads(fetch("/api/runs/run_new/report")[2]) == report
    assert json.loads(fetch("/api/runs/run_old/report")[2]) is None
    assert json.loads(fetch("/api/runs/run_old/events?offset=0")[2])["events"][0]["event"] == "run_started"


def test_runs_list_is_limited_to_latest_hundred(tmp_path):
    for number in range(102):
        path = tmp_path / f"run_{number:03d}"
        path.mkdir()
        os.utime(path, (100 + number, 100 + number))

    result = trace_web.list_runs(tmp_path)

    assert result["total"] == 102
    assert len(result["runs"]) == 100
    assert result["runs"][0]["id"] == "run_101"
    assert result["runs"][-1]["id"] == "run_002"


def test_run_title_does_not_read_oversized_later_tool_record(tmp_path, monkeypatch):
    run = tmp_path / "run_large"
    run.mkdir()
    (run / "trace.jsonl").write_bytes(
        _line({"event": "run_started", "user_request": "保留标题"}) + b"x" * 1024 + b"\n"
    )
    monkeypatch.setattr(trace_web, "MAX_FILE_BYTES", 128)

    assert trace_web.list_runs(tmp_path)["runs"][0]["prompt"] == "保留标题"


def test_http_rejects_traversal_cross_origin_and_unexpected_host(web_viewer):
    root, server, fetch = web_viewer
    (root / "run_valid").mkdir()
    for path in (
        "/.env", "/server.py", "/api/runs/../events",
        "/api/runs/run_valid%2f..%2f..%2fsecret/events",
        "/api/runs/run_valid%5c..%5csecret/events",
    ):
        assert fetch(path)[0] == 404
    assert fetch("/api/runs", {"Host": f"evil.test:{server.server_port}"})[0] == 403
    assert fetch("/api/runs", {"Origin": "https://evil.test"})[0] == 403
    assert fetch("/api/runs", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert fetch("/api/runs", {"Origin": f"http://127.0.0.1:{server.server_port}"})[0] == 200
    assert fetch("/api/runs/run_valid/events?offset=-1")[0] == 400
    assert fetch("/api/runs/run_valid/events?offset=0&offset=1")[0] == 400


def test_http_rejects_symlinked_run_and_artifact(web_viewer, tmp_path):
    root, _, fetch = web_viewer
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.json").write_text('{"private": true}', encoding="utf-8")
    try:
        (root / "run_link").symlink_to(outside, target_is_directory=True)
        valid = root / "run_valid"
        valid.mkdir()
        (valid / "report.json").symlink_to(outside / "report.json")
    except OSError:
        pytest.skip("当前 Windows 账户没有创建符号链接的权限。")

    assert fetch("/api/runs/run_link/report")[0] == 403
    assert fetch("/api/runs/run_valid/report")[0] == 403
    assert json.loads(fetch("/api/runs")[2])["total"] == 0
    with pytest.raises(PermissionError):
        trace_web.create_server(root / "run_link", port=0)


def test_http_bounds_oversized_record_without_consuming_it(web_viewer, monkeypatch):
    root, _, fetch = web_viewer
    run = root / "run_large"
    run.mkdir()
    (run / "trace.jsonl").write_bytes(_line({"event": "model_response", "text": "x" * 100}))
    monkeypatch.setattr(trace_web, "MAX_FILE_BYTES", 64)

    assert fetch("/api/runs/run_large/events?offset=0")[0] == 413


def test_inspection_endpoint_returns_iteration_model_and_bounds_trace(web_viewer):
    root, _, fetch = web_viewer
    run = root / "run_inspect"
    run.mkdir()
    events = [
        {"event": "run_started", "created_at": "2026-11-25T00:00:00+00:00", "task_id": "task_1", "user_request": "safe request"},
        {"event": "model_requested", "created_at": "2026-11-25T00:00:01+00:00", "attempts": 1},
        {"event": "model_parsed", "created_at": "2026-11-25T00:00:02+00:00", "kind": "final", "answer_preview": "done"},
        {"event": "run_finished", "created_at": "2026-11-25T00:00:03+00:00", "status": "completed", "final_answer": "done"},
    ]
    (run / "trace.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
    (run / "report.json").write_text(json.dumps({"status": "completed", "task_id": "task_1", "final_answer": "done"}), encoding="utf-8")

    status, headers, body = fetch("/api/runs/run_inspect/inspection")
    data = json.loads(body)

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert data["schema_version"] == "page-inspection-v1"
    assert data["run"]["status"] == "completed"
    assert len(data["iterations"]) == 1
    assert data["iterations"][0]["outcome"] == "final"
    assert data["raw"]["events"][1]["iteration_id"].endswith("iteration:0001")

def test_inspection_snapshot_reports_truncation_at_record_limit(web_viewer, monkeypatch):
    root, _, fetch = web_viewer
    run = root / "run_bounded"
    run.mkdir()
    events = [{"event": "model_requested", "attempts": number} for number in range(3)]
    (run / "trace.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
    monkeypatch.setattr(trace_web, "MAX_INSPECTION_RECORDS", 2)

    status, _, body = fetch("/api/runs/run_bounded/inspection")
    data = json.loads(body)

    assert status == 200
    assert data["raw"]["truncated"] is True
    assert len(data["raw"]["events"]) == 2
