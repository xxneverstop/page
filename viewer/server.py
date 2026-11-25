"""只读的本地 Page Trace 查看服务，仅使用 Python 标准库。"""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, unquote, urlsplit


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
                if len(line) > MAX_FILE_BYTES:
                    raise OverflowError("单条日志超过 8 MiB，无法在浏览器中展开。")
                if not line.endswith(b"\n"):
                    break
                consumed += len(line)
                offset = stream.tell()
                try:
                    event = json.loads(line, parse_constant=_finite_number, parse_float=_finite_number)
                    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                        raise ValueError
                except (ValueError, UnicodeError, RecursionError):
                    skipped += 1
                    continue
                events.append(event)
            else:
                has_more = offset < size
    except FileNotFoundError:
        reset = offset > 0
        offset = 0
    return {"events": events, "next_offset": offset, "has_more": has_more, "skipped": skipped, "reset": reset}


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
            if path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                asset = VIEWER_DIR / filename
                if _is_link(asset):
                    raise PermissionError
                self._send(200, asset.read_bytes(), content_type)
            elif path == "/api/runs":
                self._send(200, list_runs(self.server.runs_dir))
            else:
                parts = path.split("/")
                if len(parts) != 5 or parts[1:3] != ["api", "runs"] or parts[4] not in {"events", "report"}:
                    raise FileNotFoundError
                filename = "trace.jsonl" if parts[4] == "events" else "report.json"
                artifact = _run_file(self.server.runs_dir, parts[3], filename)
                if parts[4] == "report":
                    self._send(200, _read_object(artifact))
                else:
                    values = parse_qs(parsed.query, keep_blank_values=True).get("offset", ["0"])
                    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
                        raise ValueError
                    self._send(200, read_events(artifact, int(values[0])))
        except FileNotFoundError:
            self._send(404, {"error": "没有找到这份工件。"})
        except PermissionError:
            self._send(403, {"error": "不允许访问链接或运行目录外的文件。"})
        except OverflowError as exc:
            self._send(413, {"error": str(exc)})
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
