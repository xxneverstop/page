"""在第二个终端查看 Page 的运行时间线。"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from textwrap import indent
import time


RUNS_DIR = Path(__file__).resolve().parents[1] / ".page" / "runs"
LABELS = {
    "run_started": "提问",
    "recovery_reconciled": "恢复",
    "iteration_started": "轮次开始",
    "iteration_finished": "轮次结束",
    "prompt_built": "上下文",
    "prompt_rendered": "完整提示词",
    "model_requested": "模型请求",
    "model_http_request": "HTTP 请求",
    "model_http_response": "HTTP 响应",
    "model_http_error": "HTTP 错误",
    "model_extracted": "适配器返回",
    "model_parsed": "模型响应",
    "tool_requested": "准备工具",
    "tool_stage": "工具阶段",
    "tool_executed": "工具",
    "checkpoint_created": "检查点",
    "finalization_requested": "收尾",
    "context_failed": "上下文错误",
    "model_failed": "模型错误",
    "run_finished": "结束",
}
STATUS = {
    "ok": "成功", "rejected": "已拒绝", "error": "失败", "partial_success": "部分成功",
    "completed": "已完成", "stopped": "已停止", "failed": "失败",
}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
TOOL_STAGES = {
    "validated": "参数校验通过", "approval_requested": "检查审批策略",
    "approval_granted": "审批已通过", "approval_denied": "审批已拒绝", "executing": "开始执行",
}
PROMPT_SECTIONS = {
    "prefix": "角色、工作区和工具规则",
    "recovery_context": "恢复信息",
    "memory": "工作记忆",
    "relevant_memory": "相关记忆",
    "history": "对话与工具历史",
    "current_request": "本轮请求",
}


def format_content(value):
    """结构化字段展开为中文 JSON，文本保留原始换行和全部内容。"""
    return json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)


def format_event(event, *, detail=False):
    """把 JSONL 事件整理成一行摘要和可选的缩进内容。"""
    name = event.get("event", "未知事件")
    label = LABELS.get(name, name)
    stamp = str(event.get("created_at", ""))
    try:
        stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        stamp = "--:--:--"

    extra = []
    match name:
        case "run_started":
            if event.get("full_request"):
                summary = "原始用户输入（完整）"
                extra.append(str(event.get("user_request", "")))
            else:
                summary = " ".join(str(event.get("user_request", "")).splitlines())
        case "recovery_reconciled":
            summary = " · ".join(str(event[key]) for key in ("decision", "resume_status", "reason") if event.get(key))
        case "iteration_started":
            summary = f"第 {event.get('attempt', event.get('iteration', '?'))} 轮 · 已用工具 {event.get('tool_steps', '?')} 次"
        case "iteration_finished":
            summary = f"{STATUS.get(event.get('outcome', '?'), event.get('outcome', '?'))} · 下一步 {event.get('next_step', '?')}"
        case "prompt_built":
            prompt = event.get("prompt_metadata", {})
            memory = prompt.get("relevant_memory", {})
            reductions = prompt.get("budget_reductions", [])
            summary = (f"{prompt.get('prompt_chars', '?')} / {prompt.get('prompt_budget_chars', '?')} 字符"
                       f" · 相关记忆 {memory.get('rendered_count', 0)} 条 · 压缩 {len(reductions)} 次")
            if reductions:
                extra.append("压缩段落 " + "、".join(dict.fromkeys(item["section"] for item in reductions)))
            if prompt.get("prompt_over_budget"):
                summary += " · 仍超预算"
        case "prompt_rendered":
            summary = f"第 {event.get('attempts', '?')} 次 · {event.get('tool_protocol', '?')} 协议"
            if event.get("finalization_only"):
                summary += " · 收尾"
            sections = event.get("sections", {})
            order = event.get("section_order", [])
            if order:
                extra.append("段落顺序（字符数：原始 → 实际）\n" + "\n".join(
                    f"{index}. {PROMPT_SECTIONS.get(section, section)} [{section}]："
                    f"{sections.get(section, {}).get('raw_chars', '?')}"
                    f" → {sections.get(section, {}).get('rendered_chars', '?')}"
                    for index, section in enumerate(order, 1)
                ))
            # 详细采集由运行端开启，查看器不再截短已经采集的提示词。
            extra.append("适配器收到的完整提示词\n" + str(event.get("prompt", "")))
        case "model_requested":
            summary = f"第 {event.get('attempts', '?')} 次 · 已用工具 {event.get('tool_steps', '?')} 次 · 等待响应"
        case "model_http_request" | "model_http_response" | "model_http_error":
            summary = f"第 {event.get('attempt', '?')} 次发送 · {event.get('url', '')}"
            if name == "model_http_response":
                summary += f" · HTTP {event.get('status', '?')}"
            if name == "model_http_error":
                extra.append(str(event.get("error", "")))
            else:
                body = event.get("body", "")
                title = "请求体" if name == "model_http_request" else "原始响应体"
                # 仅格式化可解析的 JSON 回包，SSE 保持原样，--detail 仍显示原始事件。
                if name == "model_http_response" and isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except ValueError:
                        pass
                    else:
                        title += "（JSON 展开）"
                extra.extend((title, format_content(body)))
        case "model_extracted":
            summary = f"{event.get('format', '?')} 协议 · 供运行框架解析的内容"
            extra.append("文本\n" + str(event.get("text", "")))
            if event.get("tool_calls"):
                extra.append("原生工具调用\n" + format_content(event["tool_calls"]))
        case "model_parsed":
            if "payload" in event:
                label = "操作判定"
            kind = event.get("kind", "?")
            summary = {
                "tool": f"请求工具 {event.get('tool_name', '')}",
                "final": "返回回答",
                "retry": "需要重试",
            }.get(kind, kind)
            usage = event.get("completion_metadata", {})
            if usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
                summary += f" · Token 输入 {usage['input_tokens']} / 输出 {usage['output_tokens']}"
            if "payload" in event:
                extra.append("判定内容\n" + format_content(event["payload"]))
        case "tool_requested":
            summary = f"{event.get('name', '?')} · 进入工具执行器"
            if event.get("call_id"):
                summary += f" · 调用 {event['call_id']}"
            extra.append("参数\n" + format_content(event.get("args", {})))
        case "tool_stage":
            stage = event.get("stage", "?")
            stage_label = TOOL_STAGES.get(stage, stage)
            if stage == "approval_requested" and event.get("approval") == "ask":
                stage_label = "等待人工审批"
            summary = f"{event.get('name', '?')} · {stage_label}"
            if event.get("approval") is not None:
                extra.append("审批 " + format_content(event["approval"]))
        case "tool_executed":
            status = event.get("tool_status", "?")
            summary = f"{event.get('name', '?')} · {STATUS.get(status, status)}"
            if event.get("tool_error_code"):
                summary += f" · {event['tool_error_code']}"
            if event.get("args"):
                extra.append("参数 " + json.dumps(event["args"], ensure_ascii=False))
            if event.get("result"):
                title = "工具返回内容" if event.get("verbose") else "结果预览"
                extra.append(title + "\n" + indent(event["result"], "│ "))
        case "checkpoint_created":
            summary = str(event.get("trigger", ""))
        case "context_failed" | "model_failed":
            summary = str(event.get("error_type", ""))
            if event.get("error"):
                extra.append(str(event["error"]))
        case "finalization_requested":
            summary = "工具步数已达上限，整理最终回答"
        case "run_finished":
            status = event.get("status", "?")
            reason = event.get("stop_reason", "?")
            summary = f"{STATUS.get(status, status)} · {reason}"
        case _:
            summary = ""

    elapsed = event.get("duration_ms", event.get("run_duration_ms"))
    if isinstance(elapsed, (int, float)):
        duration = f"{elapsed / 1000:.2f} 秒" if elapsed >= 1000 else f"{elapsed} 毫秒"
        summary = f"{summary} · {duration}" if summary else duration
    identity = []
    if event.get("iteration_id"):
        identity.append(str(event["iteration_id"]))
    if event.get("event_seq") is not None:
        identity.append(f"#{event['event_seq']}")
    header = f"{stamp}  【{label}】 {summary}" + (f" · {' · '.join(identity)}" if identity else "")
    header = header.rstrip()
    if detail:
        extra = [json.dumps(event, ensure_ascii=False, indent=2)]
    # 外部工具文本可能包含终端控制字符，查看时只保留可读内容。
    lines = [header, *(indent(item, "    ") for item in extra)]
    return CONTROL_CHARS.sub("", "\n".join(lines))


def read_events(path, offset, *, detail=False):
    finished = False
    with path.open("rb") as stream:
        stream.seek(offset)
        # 只提交完整行的字节偏移，保留正在写入的行供下次读取。
        while (line := stream.readline()).endswith(b"\n"):
            offset = stream.tell()
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("expected a JSON object")
            except ValueError:
                print("    跳过一条无法解析的日志。", flush=True)
                continue
            print(format_event(event, detail=detail), flush=True)
            finished |= event.get("event") == "run_finished"
    return offset, finished


def main(argv=None):
    parser = argparse.ArgumentParser(description="查看 Page 的中文运行日志。")
    parser.add_argument("--detail", action="store_true", help="显示解码和缩进后的完整事件字段")
    parser.add_argument("--once", action="store_true", help="只回看最近一条运行日志")
    args = parser.parse_args(argv)

    seen = set(RUNS_DIR.glob("run_*/trace.jsonl"))
    latest = max(seen, key=lambda path: path.stat().st_mtime_ns, default=None)
    new = [latest] if latest else []
    pending = {}
    print("Page 运行日志" + (" · 回看" if args.once else " · 实时跟踪 · Ctrl+C 退出"), flush=True)
    if not latest:
        print("暂时没有日志。在 Page 中发送提问后会生成日志。", flush=True)

    while True:
        pending.update(dict.fromkeys(new, 0))
        for path, offset in list(pending.items()):
            if path in new:
                print(f"\n── {path.parent.name} ──", flush=True)
            try:
                pending[path], finished = read_events(path, offset, detail=args.detail)
            except FileNotFoundError:
                finished = True
            if finished:
                del pending[path]
        if args.once:
            return
        # 同时记住已见文件和未结束的偏移，以便切换时仍能读完上一条。
        time.sleep(0.4)
        traces = set(RUNS_DIR.glob("run_*/trace.jsonl"))
        new = sorted(traces - seen)
        seen = traces


if __name__ == "__main__":
    # Windows 控制台和重定向到文件时，都使用 UTF-8 输出。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except KeyboardInterrupt:
        pass
