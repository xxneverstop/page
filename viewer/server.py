"""只读的本地 Page Trace 查看服务，仅使用 Python 标准库。"""

import argparse
import json
import math
import re
import stat
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from .trace_model import build_inspection
except ImportError:
    from trace_model import build_inspection


VIEWER_DIR = Path(__file__).resolve().parent
DEFAULT_RUNS_DIR = VIEWER_DIR.parent / ".page" / "runs"
RUN_ID = re.compile(r"run_[A-Za-z0-9_-]{1,128}\Z")
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/styles.css": ("styles.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
MAX_RECORDS = 200
MAX_BATCH_BYTES = 1024 * 1024
# shortcut: 单份 JSON 工件和单条日志限 8 MiB，更大记录需改为分块展示。
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_INSPECTION_RECORDS = 12000
MAX_INSPECTION_BYTES = 32 * 1024 * 1024
# 超长单行用有限次读取丢弃，避免一条坏记录永久挡住后面的有效事件。
MAX_RECORD_SKIP_BYTES = 256 * 1024 * 1024
# Inspection 只在工件变更后重建；保留最近几个运行，缓存体本身有上限。
INSPECTION_CACHE_MAX_ENTRIES = 4
INSPECTION_CACHE_MAX_BODY = 8 * 1024 * 1024
_INSPECTION_CACHE = OrderedDict()
_INSPECTION_CACHE_LOCK = threading.Lock()
TERMINAL_STATUSES = {"completed", "failed", "stopped"}


def _is_link(path):
    try:
        # Windows 的目录联接也属于重解析点，不能借它越过运行目录。
        info = path.lstat()
        return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False


def _check_root(path):
    if any(_is_link(part) for part in (path, *path.parents)):
        raise PermissionError("运行目录不能包含符号链接或目录联接。")
    if path.exists() and not path.is_dir():
        raise ValueError("运行目录必须是目录。")


def _run_file(root, run_id, filename):
    _check_root(root)
    if not RUN_ID.fullmatch(run_id):
        raise FileNotFoundError
    directory = root / run_id
    path = directory / filename
    if _is_link(directory) or _is_link(path):
        raise PermissionError
    if not directory.is_dir():
        raise FileNotFoundError
    if path.exists() and not path.is_file():
        raise PermissionError
    return path


def _finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON 数字必须有限。")
    return number


def _read_object(path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        with path.open("rb") as stream:
            body = stream.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            return None
        data = json.loads(body, parse_constant=_finite_number, parse_float=_finite_number)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def _discard_oversized_line(stream):
    """Consume the rest of an oversized JSONL line.

    Returns True when the line was fully discarded. A pathological record over
    the hard cap returns False so one bad line cannot make every refresh read
    unbounded data.
    """
    remaining = MAX_RECORD_SKIP_BYTES
    while remaining > 0:
        chunk = stream.readline(min(remaining, 64 * 1024))
        if not chunk:
            return True
        if chunk.endswith(b"\n"):
            return True
        remaining -= len(chunk)
    return False


def _load_line(line):
    """Return a valid event dict, or None for damaged / non-event records."""
    try:
        event = json.loads(line, parse_constant=_finite_number, parse_float=_finite_number)
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            return None
        return event
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None


def read_events(path, offset=0):
    """只提交完整 JSONL 行的字节游标，正在写入的末行留到下次。"""
    events, skipped, consumed = [], 0, 0
    reset = False
    has_more = False
    try:
        with path.open("rb") as stream:
            size = path.stat().st_size
            reset = offset > size
            if reset:
                offset = 0
            stream.seek(offset)
            while len(events) + skipped < MAX_RECORDS and consumed < MAX_BATCH_BYTES:
                line = stream.readline(MAX_FILE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_FILE_BYTES:
                    # 超大记录跳过但继续推进游标，后面的有效事件仍然可读。
                    if not _discard_oversized_line(stream):
                        break
                    skipped += 1
                    consumed += len(line)
                    offset = stream.tell()
                    continue
                if not line.endswith(b"\n"):
                    break
                consumed += len(line)
                offset = stream.tell()
                event = _load_line(line)
                if event is None:
                    skipped += 1
                    continue
                events.append(event)
            else:
                has_more = offset < size
    except FileNotFoundError:
        reset = offset > 0
        offset = 0
    return {"events": events, "next_offset": offset, "has_more": has_more, "skipped": skipped, "reset": reset}


def read_all_events(path):
    """Read a bounded snapshot for the derived inspection model.

    Raw event streaming remains incremental. The bounded snapshot keeps a long
    trace from making a refresh unbounded while still exposing its truncation.
    Damaged or oversized records are skipped so later valid events stay visible.
    """
    events, skipped, consumed = [], 0, 0
    truncated = False
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            while len(events) + skipped < MAX_INSPECTION_RECORDS and consumed < MAX_INSPECTION_BYTES:
                line = stream.readline(MAX_FILE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_FILE_BYTES:
                    if not _discard_oversized_line(stream):
                        truncated = True
                        break
                    skipped += 1
                    consumed += len(line)
                    continue
                if not line.endswith(b"\n"):
                    # 正在写入的末行下一次刷新会补上，不视为截断。
                    break
                consumed += len(line)
                event = _load_line(line)
                if event is None:
                    skipped += 1
                    continue
                events.append(event)
            # 只有到达上限且文件还有未读内容时才算截断；刚好读到最后一条不算。
            if (len(events) + skipped >= MAX_INSPECTION_RECORDS or consumed >= MAX_INSPECTION_BYTES) and stream.tell() < size:
                truncated = True
    except FileNotFoundError:
        pass
    return {"events": events, "skipped": skipped, "truncated": truncated}


def _artifact_signature(paths):
    signature = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            signature.append(None)
        else:
            signature.append((info.st_mtime_ns, info.st_size))
    return tuple(signature)


def build_inspection_body(root, run_id):
    """Build (or reuse) the serialized inspection payload for one run.

    The cache is invalidated by artifact mtime/size, so a late report write or
    new trace lines rebuild while an idle finished run stays cached.
    """
    trace_path = _run_file(root, run_id, "trace.jsonl")
    state_path = _run_file(root, run_id, "task_state.json")
    report_path = _run_file(root, run_id, "report.json")
    signature = _artifact_signature((trace_path, state_path, report_path))
    cache_key = (str(root), run_id)
    with _INSPECTION_CACHE_LOCK:
        cached = _INSPECTION_CACHE.get(cache_key)
        if cached and cached["signature"] == signature:
            _INSPECTION_CACHE.move_to_end(cache_key)
            return cached["body"]
    snapshot = read_all_events(trace_path)
    state = _read_object(state_path)
    report = _read_object(report_path)
    inspection = build_inspection(
        run_id, snapshot["events"], report, state, snapshot["truncated"], snapshot["skipped"],
    )
    body = json.dumps(inspection, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) <= INSPECTION_CACHE_MAX_BODY:
        with _INSPECTION_CACHE_LOCK:
            _INSPECTION_CACHE[cache_key] = {"signature": signature, "body": body}
            _INSPECTION_CACHE.move_to_end(cache_key)
            while len(_INSPECTION_CACHE) > INSPECTION_CACHE_MAX_ENTRIES:
                _INSPECTION_CACHE.popitem(last=False)
    return body


def _read_prompt(path):
    # 列表会频繁刷新；标题只读开头几行，不解码后续大段模型与工具正文。
    remaining = 64 * 1024
    try:
        with path.open("rb") as stream:
            for _ in range(8):
                line = stream.readline(remaining + 1)
                if len(line) > remaining or not line.endswith(b"\n"):
                    break
                remaining -= len(line)
                try:
                    event = json.loads(line, parse_constant=_finite_number, parse_float=_finite_number)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                if isinstance(event, dict) and event.get("event") == "run_started":
                    prompt = event.get("user_request")
                    return prompt[:300] if isinstance(prompt, str) else ""
    except OSError:
        pass
    return ""


def list_runs(root):
    _check_root(root)
    candidates = []
    for directory in root.iterdir() if root.exists() else ():
        if not RUN_ID.fullmatch(directory.name) or _is_link(directory) or not directory.is_dir():
            continue
        try:
            paths = [_run_file(root, directory.name, name) for name in ("trace.jsonl", "task_state.json", "report.json")]
            updated = max([directory.stat().st_mtime, *(path.stat().st_mtime for path in paths if path.exists())])
            candidates.append((updated, directory.name, paths))
        except OSError:
            continue
    runs = []
    for updated, run_id, (trace_path, state_path, report_path) in sorted(candidates, reverse=True)[:100]:
        state = _read_object(state_path) or {}
        report = _read_object(report_path) or {}
        # task_state 的用户原文没有脱敏，只允许取计数和结束状态等元数据。
        status = report.get("status", state.get("status"))
        status = status if isinstance(status, str) and status in TERMINAL_STATUSES else "unknown"
        item = {
            "id": run_id, "status": status, "prompt": _read_prompt(trace_path), "provider": "", "model": "",
            "attempts": 0, "tool_steps": 0, "stop_reason": "",
            "updated_at": datetime.fromtimestamp(updated, timezone.utc).isoformat(),
        }
        for key in ("provider", "model", "stop_reason"):
            value = report.get(key, state.get(key, "") if key == "stop_reason" else "")
            if isinstance(value, str):
                item[key] = value[:200]
        for key in ("attempts", "tool_steps"):
            value = report.get(key, state.get(key, 0))
            if type(value) is int and value >= 0:
                item[key] = value
        runs.append(item)
    return {"runs": runs, "total": len(candidates)}


class TraceHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def _send(self, status, body, content_type="application/json"):
        if content_type == "application/json":
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send_bytes(status, body, content_type)

    def _send_bytes(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            hosts.update({"127.0.0.1", "localhost"})
        host = self.headers.get("Host", "").lower()
        origins = self.headers.get_all("Origin", [])
        # 限制 Host 防 DNS 重绑定；浏览器请求只接受本服务自己的源。
        if (len(self.headers.get_all("Host", [])) != 1 or host not in hosts
                or len(origins) > 1 or (origins and origins[0] != f"http://{host}")
                or self.headers.get("Sec-Fetch-Site", "none") not in {"none", "same-origin"}):
            self._send(403, {"error": "仅允许本机同源访问。"})
            return
        try:
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if path == "/favicon.ico":
                # 浏览器自动请求图标；返回空响应，避免控制台出现无意义的 404。
                self._send_bytes(204, b"", "text/plain")
            elif path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                asset = VIEWER_DIR / filename
                if _is_link(asset):
                    raise PermissionError
                self._send(200, asset.read_bytes(), content_type)
            elif path == "/api/runs":
                self._send(200, list_runs(self.server.runs_dir))
            else:
                parts = path.split("/")
                if len(parts) != 5 or parts[1:3] != ["api", "runs"] or parts[4] not in {"events", "report", "inspection"}:
                    raise FileNotFoundError
                if parts[4] == "report":
                    self._send(200, _read_object(_run_file(self.server.runs_dir, parts[3], "report.json")))
                elif parts[4] == "events":
                    values = parse_qs(parsed.query, keep_blank_values=True).get("offset", ["0"])
                    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
                        raise ValueError
                    self._send(200, read_events(_run_file(self.server.runs_dir, parts[3], "trace.jsonl"), int(values[0])))
                else:
                    self._send_bytes(200, build_inspection_body(self.server.runs_dir, parts[3]))
        except FileNotFoundError:
            self._send(404, {"error": "没有找到这份工件。"})
        except PermissionError:
            self._send(403, {"error": "不允许访问链接或运行目录外的文件。"})
        except (ValueError, RecursionError):
            self._send(400, {"error": "无效的请求参数。"})
        except OSError:
            self._send(503, {"error": "暂时无法读取工件，请稍后重试。"})

    def log_message(self, format, *args):
        pass


def create_server(runs_dir=DEFAULT_RUNS_DIR, port=8765):
    root = Path(runs_dir).absolute()
    _check_root(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), TraceHandler)
    server.runs_dir = root
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="在本机浏览 Page 的运行日志。")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    args = parser.parse_args(argv)
    try:
        with create_server(args.runs_dir, args.port) as server:
            print(f"Page Trace Viewer: http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
