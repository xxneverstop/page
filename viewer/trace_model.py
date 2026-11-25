"""Normalize Page trace events into one read-only inspection model.

The viewer consumes both current detailed traces and older compact traces. This
module keeps compatibility rules in one place so every UI view shares the same
iteration, model, tool, context, and metric interpretation.

Design rules:
- Raw events stay the single source of evidence; derived views reference them
  by ``event_id`` instead of copying large Prompt/HTTP/tool bodies around.
- Missing evidence is reported as unknown, never synthesized into a success.
- Viewer-inferred IDs are marked so runtime records and compatibility guesses
  stay distinguishable.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from difflib import unified_diff

TERMINAL_STATUSES = {"completed", "failed", "stopped", "error"}
# Diff 只用于界面阅读，超长 Prompt 截断后由 text_truncated 明确标记。
MAX_DIFF_LINES = 240
MAX_PREVIEW_CHARS = 300
CATEGORY_BY_PREFIX = {
    "prompt_": "context",
    "context_": "context",
    "model_http_": "model",
    "model_": "model",
    "tool_": "tools",
    "checkpoint_": "recovery",
    "recovery_": "recovery",
    "runtime_identity_": "recovery",
    "journal_": "recovery",
    "action_": "recovery",
    "evaluation_": "evaluation",
    "verifier_": "evaluation",
}
MODEL_EVENTS = {
    "prompt_built",
    "prompt_rendered",
    "model_requested",
    "model_http_request",
    "model_http_response",
    "model_http_error",
    "model_extracted",
    "model_parsed",
    "model_failed",
}
FAILURE_OUTCOMES = {"model_failed", "context_failed"}
STOPPED_OUTCOMES = {"stopped", "finalization_tool_rejected"}


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _text(value):
    return str(value).strip() if value is not None else ""


def _clip_text(value, limit=MAX_PREVIEW_CHARS):
    text = _text(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"… [truncated {len(text) - limit} chars]"


def event_category(event_name):
    name = _text(event_name)
    if name in {"run_started", "run_finished", "iteration_started", "iteration_finished"}:
        return "lifecycle"
    if name in {"model_parsed", "finalization_requested"}:
        return "decision"
    for prefix, category in CATEGORY_BY_PREFIX.items():
        if name.startswith(prefix):
            return category
    if "recovery" in name or "checkpoint" in name or "journal" in name:
        return "recovery"
    return "other"


def _iteration_id(run_id, number):
    return f"{run_id}:iteration:{int(number):04d}" if number else ""


def _model_request_id(run_id, number):
    return f"{run_id}:model:{int(number):04d}" if number else ""


def _tool_call_id(run_id, iteration_number, ordinal):
    if not iteration_number:
        return ""
    return f"{run_id}:iteration:{int(iteration_number):04d}:tool:{int(ordinal)}"


def normalize_events(events, run_id="", state=None, report=None):
    """Add stable viewer fields while preserving the raw event payload."""
    normalized = []
    current_iteration = 0
    current_model_request = ""
    tool_ordinals = {}
    active_tool = {}
    previous_name = ""

    for index, original in enumerate(events, 1):
        if not isinstance(original, dict):
            continue
        event = dict(original)
        name = _text(event.get("event")) or "unknown"
        explicit_iteration_id = bool(_text(event.get("iteration_id")))
        explicit_model_request_id = bool(_text(event.get("model_request_id")))
        explicit_tool_call_id = bool(_text(event.get("tool_call_id") or event.get("call_id")))
        attempt = _integer(event.get("attempts"))
        explicit_iteration = _integer(event.get("iteration"))
        metadata = event.get("prompt_metadata") if isinstance(event.get("prompt_metadata"), dict) else {}
        if attempt is None:
            attempt = _integer(metadata.get("attempts"))
        if explicit_iteration is not None:
            current_iteration = explicit_iteration
        elif attempt is not None:
            current_iteration = attempt
        elif name == "prompt_built" and current_iteration == 0:
            current_iteration = 1
        elif name == "prompt_built" and previous_name in {"tool_executed", "model_parsed", "iteration_finished"}:
            current_iteration += 1

        event.setdefault("event_seq", index)
        event.setdefault("event_id", f"{run_id}:event:{index}" if run_id else f"event:{index}")
        event.setdefault("category", event_category(name))
        event.setdefault("iteration", current_iteration or None)
        event.setdefault("iteration_id", _iteration_id(run_id, current_iteration))
        if event.get("iteration_id"):
            event["iteration_source"] = "trace" if explicit_iteration_id else "viewer_inferred"

        if name == "iteration_started":
            # A new loop turn starts a new model request association.
            current_model_request = ""
        if name == "model_requested":
            current_model_request = _text(event.get("model_request_id")) or current_model_request or _model_request_id(run_id, current_iteration)
        if name == "prompt_built" and current_iteration:
            explicit_request = _text(event.get("model_request_id"))
            if explicit_request:
                current_model_request = explicit_request
            elif not current_model_request or previous_name in {"run_started", "tool_executed", "model_parsed", "iteration_finished", "iteration_started"}:
                current_model_request = _model_request_id(run_id, current_iteration)
            event.setdefault("model_request_id", current_model_request)
        elif name == "prompt_rendered" and current_iteration:
            current_model_request = current_model_request or _model_request_id(run_id, current_iteration)
            event.setdefault("model_request_id", current_model_request)
        if name.startswith("model_") and current_model_request:
            event.setdefault("model_request_id", current_model_request)
        if event.get("model_request_id") and name in MODEL_EVENTS:
            event["model_request_source"] = "trace" if explicit_model_request_id else "viewer_inferred"

        if name in {"tool_requested", "tool_stage", "tool_executed"}:
            explicit_tool = _text(event.get("tool_call_id") or event.get("call_id"))
            tool_name = _text(event.get("name"))
            key = (current_iteration, tool_name)
            # 序号按轮次递增而不是按工具名，避免同一轮不同工具的推导 ID 碰撞。
            if explicit_tool:
                tool_id = explicit_tool
            elif name == "tool_requested":
                tool_ordinals[current_iteration] = tool_ordinals.get(current_iteration, 0) + 1
                tool_id = _tool_call_id(run_id, current_iteration, tool_ordinals[current_iteration])
            elif key in active_tool:
                tool_id = active_tool[key]
            else:
                tool_ordinals[current_iteration] = tool_ordinals.get(current_iteration, 0) + 1
                tool_id = _tool_call_id(run_id, current_iteration, tool_ordinals[current_iteration])
            if tool_id:
                event.setdefault("tool_call_id", tool_id)
                event["tool_call_source"] = "trace" if explicit_tool_call_id else "viewer_inferred"
                active_tool[key] = tool_id
            if current_model_request:
                event.setdefault("model_request_id", current_model_request)

        normalized.append(event)
        previous_name = name

    return normalized


def _new_iteration(run_id, number):
    return {
        "id": _iteration_id(run_id, number) or f"iteration:{number}",
        "index": number,
        "source": "trace",
        "event_ids": [],
        "event_types": [],
        "event_count": 0,
        "model_request_ids": [],
        "tool_call_ids": [],
        "status": "incomplete",
        "outcome": "unknown",
        "finished_outcome": "",
        "started_at": "",
        "finished_at": "",
        "duration_ms": None,
        "context_event_id": "",
        "model_kind": "",
        "tool_names": [],
        "tools_failed": 0,
        "tools_rejected": 0,
        "answer_preview": "",
    }


def _append_unique(items, value):
    if value and value not in items:
        items.append(value)


def _new_context_snapshot():
    return {
        "event_id": "",
        "sequence": None,
        "iteration": None,
        "iteration_id": "",
        "prompt_event_id": "",
        "prompt_chars": None,
        "prompt_budget_chars": None,
        "prompt_over_budget": False,
        "token_estimate": None,
        "token_estimate_method": "",
        "section_order": [],
        "section_budgets": {},
        "sections": {},
        "context_blocks": [],
        "budget_reductions": [],
        "reduction_order": [],
        "history": {},
        "history_messages": None,
        "history_tool_results": None,
        "history_tool_call_ids": [],
        "relevant_memory": {},
        "stale_paths": [],
        "recovery_decision": {},
        "source": "trace",
        "detail_available": False,
    }


def _apply_context_metadata(snapshot, metadata):
    """Merge prompt_built metadata into a snapshot without inventing values."""
    if not isinstance(metadata, dict):
        return
    for key in ("prompt_chars", "prompt_budget_chars", "token_estimate", "history_messages", "history_tool_results"):
        if metadata.get(key) is not None:
            snapshot[key] = metadata.get(key)
    snapshot["prompt_over_budget"] = bool(metadata.get("prompt_over_budget", snapshot["prompt_over_budget"]))
    for key in ("token_estimate_method",):
        if metadata.get(key):
            snapshot[key] = metadata[key]
    for key in ("section_order", "context_blocks", "budget_reductions", "reduction_order", "stale_paths", "history_tool_call_ids"):
        if metadata.get(key):
            snapshot[key] = list(metadata[key])
    for key in ("section_budgets", "sections", "history", "relevant_memory", "recovery_decision"):
        if metadata.get(key):
            snapshot[key] = dict(metadata[key])


def _build_contexts(normalized):
    """One consolidated snapshot per iteration, in trace order."""
    snapshots = OrderedDict()
    for event in normalized:
        name = event.get("event")
        if name not in {"prompt_built", "prompt_rendered"}:
            continue
        key = event.get("iteration_id") or f"event:{event.get('event_id')}"
        snapshot = snapshots.get(key)
        if snapshot is None:
            snapshot = _new_context_snapshot()
            snapshots[key] = snapshot
        snapshot["iteration"] = event.get("iteration")
        snapshot["iteration_id"] = event.get("iteration_id", "")
        if event.get("iteration_source") == "viewer_inferred":
            snapshot["source"] = "viewer_inferred"
        # 事件身份以第一个上下文事件为准，后续合并保持稳定，便于迭代引用。
        snapshot["event_id"] = snapshot["event_id"] or event.get("event_id", "")
        snapshot["sequence"] = snapshot["sequence"] if snapshot["sequence"] is not None else event.get("event_seq")
        if name == "prompt_built":
            _apply_context_metadata(snapshot, event.get("prompt_metadata"))
        else:
            snapshot["prompt_event_id"] = event.get("event_id", "")
            snapshot["detail_available"] = bool(event.get("prompt"))
            if event.get("section_order"):
                snapshot["section_order"] = list(event["section_order"])
            if event.get("sections"):
                snapshot["sections"] = dict(event["sections"])
    return list(snapshots.values())


def diff_contexts(first, second, first_prompt="", second_prompt=""):
    """Compare two actual Context snapshots.

    Structured changes come from recorded metadata. Text differences are
    computed by the Viewer and must not be read as a Harness decision.
    """
    if not first or not second:
        return {
            "available": False,
            "reason": "需要两个有上下文证据的快照。",
            "sections": [],
            "recovery_decision": None,
            "text": "",
            "text_truncated": False,
            "source": "none",
        }
    changes = []
    before_sections = first.get("sections") or {}
    after_sections = second.get("sections") or {}
    section_names = list(dict.fromkeys([
        *(first.get("section_order") or []),
        *(second.get("section_order") or []),
        *before_sections,
        *after_sections,
    ]))
    for name in section_names:
        before = dict(before_sections.get(name) or {})
        after = dict(after_sections.get(name) or {})
        if before != after:
            changes.append({
                "name": name,
                "before": before,
                "after": after,
                "delta_rendered_chars": (_number(after.get("rendered_chars")) or 0) - (_number(before.get("rendered_chars")) or 0),
                "source": "metadata",
            })
    before_recovery = dict(first.get("recovery_decision") or {})
    after_recovery = dict(second.get("recovery_decision") or {})
    recovery_change = None
    if before_recovery != after_recovery:
        recovery_change = {"before": before_recovery, "after": after_recovery, "source": "metadata"}

    text_lines = []
    before_text = _text(first_prompt)
    after_text = _text(second_prompt)
    if before_text and after_text and before_text != after_text:
        text_lines = list(unified_diff(
            before_text.splitlines(), after_text.splitlines(),
            fromfile="previous", tofile="current", lineterm="",
        ))
    text_truncated = len(text_lines) > MAX_DIFF_LINES
    text = "\n".join(text_lines[:MAX_DIFF_LINES])
    source_parts = []
    if changes or recovery_change:
        source_parts.append("metadata")
    if text:
        source_parts.append("text")
    return {
        "available": True,
        "reason": "" if (changes or recovery_change or text) else "结构化元数据与 Prompt 文本都没有可见变化。",
        "sections": changes,
        "recovery_decision": recovery_change,
        "text": text,
        "text_truncated": text_truncated,
        "source": "+".join(source_parts) or "none",
    }


def _model_requests(events):
    requests = OrderedDict()
    current_id = ""
    for event in events:
        name = event.get("event")
        request_id = _text(event.get("model_request_id"))
        if name == "iteration_started":
            # Prevent lifecycle events from the next iteration leaking into this request.
            current_id = ""
            continue
        if name == "prompt_built" and not request_id:
            request_id = f"model:{len(requests) + 1}"
            current_id = request_id
        elif name == "model_requested":
            request_id = request_id or current_id or f"model:{len(requests) + 1}"
            current_id = request_id
        elif not request_id and name in MODEL_EVENTS:
            request_id = current_id
        elif request_id and name in MODEL_EVENTS:
            current_id = request_id
        if not request_id or name not in MODEL_EVENTS:
            continue
        item = requests.setdefault(request_id, {
            "id": request_id,
            "iteration_id": event.get("iteration_id", ""),
            "iteration": event.get("iteration"),
            "event_ids": [],
            "requested_event_id": "",
            "prompt_event_id": "",
            "extracted_event_id": "",
            "parsed_event_id": "",
            "failed_event_id": "",
            "kind": "",
            "status": "unknown",
            "source": "trace" if event.get("model_request_source") == "trace" else "viewer_inferred",
            "http": [],
            "http_sends": 0,
            "error": "",
        })
        if event.get("model_request_source") == "trace":
            item["source"] = "trace"
        item["event_ids"].append(event.get("event_id", ""))
        if event.get("iteration_id") and not item["iteration_id"]:
            item["iteration_id"] = event["iteration_id"]
        if event.get("iteration") and not item["iteration"]:
            item["iteration"] = event["iteration"]
        if name == "model_requested":
            item["requested_event_id"] = event.get("event_id", "")
        elif name == "prompt_rendered":
            item["prompt_event_id"] = event.get("event_id", "")
        elif name == "model_http_request":
            _http_slot(item, event, "request_event_id")
            item["http_sends"] += 1
        elif name == "model_http_response":
            _http_slot(item, event, "response_event_id")
        elif name == "model_http_error":
            _http_slot(item, event, "error_event_id")
        elif name == "model_extracted":
            item["extracted_event_id"] = event.get("event_id", "")
        elif name == "model_parsed":
            item["parsed_event_id"] = event.get("event_id", "")
            item["kind"] = _text(event.get("kind"))
        elif name == "model_failed":
            item["failed_event_id"] = event.get("event_id", "")
            item["error"] = _clip_text(event.get("error") or event.get("error_type") or "")
    for item in requests.values():
        # 状态优先级：失败 > 解析判定 > 已收到响应 > 已发送 > 已准备。
        if item["failed_event_id"]:
            item["status"] = "failed"
        elif item["kind"]:
            item["status"] = item["kind"]
        elif any(slot.get("response_event_id") for slot in item["http"]):
            item["status"] = "responded"
        elif item["http_sends"]:
            item["status"] = "sent"
        elif item["requested_event_id"]:
            item["status"] = "requested"
        for index, slot in enumerate(item["http"], 1):
            slot["attempt"] = slot["attempt"] or index
        item["http"].sort(key=lambda slot: slot["attempt"] or 0)
    return list(requests.values())


def _http_slot(item, event, key):
    """Group request/response/error into one actual HTTP send lifecycle.

    A request event always owns a slot; response/error attach to the matching
    attempt (or the most recent open send when legacy logs omit ``attempt``).
    """
    attempt = _integer(event.get("attempt"))
    if key == "request_event_id":
        # 同一 attempt 只应该有一次实际发送；重复请求事件各自独立。
        slot = next((
            candidate for candidate in item["http"]
            if attempt is not None and candidate["attempt"] == attempt and not candidate["request_event_id"]
        ), None)
        if slot is None:
            slot = {"attempt": attempt, "request_event_id": "", "response_event_id": "", "error_event_id": "", "status": None, "url": ""}
            item["http"].append(slot)
    else:
        slot = next((
            candidate for candidate in reversed(item["http"])
            if attempt is not None and candidate["attempt"] == attempt and candidate["request_event_id"]
        ), None)
        if slot is None:
            slot = next((
                candidate for candidate in reversed(item["http"])
                if candidate["request_event_id"] and not candidate[key]
            ), None)
        if slot is None:
            slot = {"attempt": attempt, "request_event_id": "", "response_event_id": "", "error_event_id": "", "status": None, "url": ""}
            item["http"].append(slot)
    slot[key] = event.get("event_id", "")
    if event.get("url"):
        slot["url"] = _text(event.get("url"))
    if event.get("status") is not None:
        slot["status"] = event.get("status")
    if event.get("error"):
        slot["error"] = _clip_text(event.get("error"))


def _tool_calls(events):
    tools = OrderedDict()
    current_ids = {}
    for event in events:
        name = event.get("event")
        if name not in {"tool_requested", "tool_stage", "tool_executed"}:
            continue
        call_id = _text(event.get("tool_call_id") or event.get("call_id"))
        tool_name = _text(event.get("name")) or "unknown tool"
        key = (event.get("iteration_id", ""), tool_name)
        if not call_id:
            call_id = current_ids.get(key) or f"tool:{len(tools) + 1}"
        current_ids[key] = call_id
        item = tools.setdefault(call_id, {
            "id": call_id,
            "name": tool_name,
            "iteration_id": event.get("iteration_id", ""),
            "iteration": event.get("iteration"),
            "model_request_id": event.get("model_request_id", ""),
            "event_ids": [],
            "phase_event_ids": [],
            "stages": [],
            "request_event_id": "",
            "result_event_id": "",
            "status": "unknown",
            "execution": "requested",
            "risk_level": "",
            "approval": "",
            "read_only": None,
            "workspace_changed": None,
            "affected_paths": [],
            "diff_summary": [],
            "action_id": "",
            "action_phase": "",
            "recovery_action": "",
            "tool_error_code": "",
            "args_preview": "",
            "source": "trace" if event.get("tool_call_source") == "trace" else "viewer_inferred",
        })
        if event.get("tool_call_source") == "trace":
            item["source"] = "trace"
        item["event_ids"].append(event.get("event_id", ""))
        if name == "tool_requested":
            item["request_event_id"] = event.get("event_id", "")
            item["execution"] = "requested"
            item["args_preview"] = _clip_text(event.get("args") or {})
        elif name == "tool_stage":
            item["phase_event_ids"].append(event.get("event_id", ""))
            if event.get("stage"):
                item["stages"].append(event.get("stage"))
            if event.get("approval"):
                item["approval"] = event.get("approval")
        elif name == "tool_executed":
            item["result_event_id"] = event.get("event_id", "")
            status = _text(event.get("tool_status")) or "unknown"
            recovery_action = _text(event.get("recovery_action"))
            item["status"] = status
            item["execution"] = "executed"
            item["recovery_action"] = recovery_action
            # 重复动作和缓存读取都表示工具没有真正执行，单独标为 skipped。
            if recovery_action in {"skipped_duplicate", "cached_read"}:
                item["status"] = "skipped"
                item["execution"] = "skipped"
            elif status == "rejected":
                item["execution"] = "rejected"
            item["risk_level"] = event.get("risk_level", item["risk_level"])
            item["read_only"] = event.get("read_only", item["read_only"])
            item["workspace_changed"] = event.get("workspace_changed", item["workspace_changed"])
            item["affected_paths"] = list(event.get("affected_paths") or [])
            item["diff_summary"] = list(event.get("diff_summary") or [])
            item["action_id"] = _text(event.get("action_id"))
            item["action_phase"] = _text(event.get("action_phase"))
            item["tool_error_code"] = _text(event.get("tool_error_code"))
            item["args_preview"] = item["args_preview"] or _clip_text(event.get("args") or {})
    return list(tools.values())


def _status_from(report, events):
    report_status = _text((report or {}).get("status"))
    if report_status in TERMINAL_STATUSES:
        return report_status, "report"
    finished = next((event for event in reversed(events) if event.get("event") == "run_finished"), None)
    if finished and _text(finished.get("status")) in TERMINAL_STATUSES:
        return finished["status"], "trace"
    return "unknown", "incomplete_trace"


def _usage(model_requests, report):
    """Token usage with explicit completeness.

    Only metadata that actually carries numeric usage is counted. A report
    fallback describes the last request only and is marked as such.
    """
    calls_total = len(model_requests)
    records = []
    for request in model_requests:
        parsed = request.get("_parsed") or {}
        metadata = parsed.get("completion_metadata") if isinstance(parsed, dict) else None
        if not isinstance(metadata, dict):
            continue
        if any(_number(metadata.get(key)) is not None for key in ("input_tokens", "output_tokens", "total_tokens")):
            records.append(metadata)
    source, scope = "trace", "run"
    if not records:
        metadata = dict((report or {}).get("prompt_metadata") or {})
        if any(_number(metadata.get(key)) is not None for key in ("input_tokens", "output_tokens", "total_tokens")):
            records = [metadata]
            source, scope = "report", "last_request"
        else:
            return {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "status": "unknown",
                "source": "missing",
                "scope": "run",
                "calls_with_usage": 0,
                "calls_total": calls_total,
            }

    input_total = input_known = output_total = output_known = total_total = 0
    totals_known = True
    complete_records = 0
    for metadata in records:
        input_tokens = _number(metadata.get("input_tokens"))
        output_tokens = _number(metadata.get("output_tokens"))
        total_tokens = _number(metadata.get("total_tokens"))
        if input_tokens is not None:
            input_total += input_tokens
            input_known += 1
        if output_tokens is not None:
            output_total += output_tokens
            output_known += 1
        if total_tokens is not None:
            total_total += total_tokens
        elif input_tokens is not None and output_tokens is not None:
            total_total += input_tokens + output_tokens
        else:
            totals_known = False
        if input_tokens is not None and (output_tokens is not None or total_tokens is not None):
            complete_records += 1
    if len(records) == calls_total and complete_records == len(records) and totals_known and scope == "run":
        status = "complete"
    else:
        status = "partial"
    return {
        "input_tokens": int(input_total) if input_known else None,
        "output_tokens": int(output_total) if output_known else None,
        "total_tokens": int(total_total) if (totals_known or total_total) else None,
        "status": status,
        "source": source,
        "scope": scope,
        "calls_with_usage": len(records),
        "calls_total": calls_total,
    }


def _duration_between(start, end):
    if not start or not end:
        return None
    from datetime import datetime

    try:
        first = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return max(0, int((last - first).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def _evaluation(report):
    if not report:
        return {"status": "unknown", "source": "not_recorded", "evidence": None}
    for key in ("verifier", "verification", "evaluation", "evaluator", "metrics"):
        if key in report:
            return {"status": "recorded", "source": key, "evidence": report[key]}
    return {"status": "unknown", "source": "not_recorded", "evidence": None}


def _iteration_status(iteration):
    """轮次状态以失败证据优先，避免被通用 outcome=tool/final 覆盖成成功。"""
    outcome = iteration["outcome"]
    if outcome in FAILURE_OUTCOMES:
        return "failed", outcome
    if outcome in STOPPED_OUTCOMES:
        return "stopped", outcome
    if iteration["tools_failed"]:
        return "failed", ("tool_error" if outcome in {"tool", "unknown", "final", "retry"} else outcome)
    if outcome in {"final", "tool", "retry"}:
        return "completed", outcome
    if iteration["tools_rejected"]:
        return "rejected", "tool_rejected"
    return "incomplete", outcome


def build_inspection(run_id, events, report=None, state=None, truncated=False, skipped=0):
    report = dict(report or {})
    state = dict(state or {})
    normalized = normalize_events(events, run_id, state, report)
    event_by_id = {event.get("event_id"): event for event in normalized}
    model_requests = _model_requests(normalized)
    # 供 usage 计算读取解析事件，但不把整份事件复制进模型视图。
    for request in model_requests:
        request["_parsed"] = event_by_id.get(request["parsed_event_id"]) or {}
    tools = _tool_calls(normalized)
    tool_by_event = {}
    for tool in tools:
        for event_id in (tool["request_event_id"], tool["result_event_id"], *tool["phase_event_ids"]):
            if event_id:
                tool_by_event[event_id] = tool
    iterations = OrderedDict()
    contexts = _build_contexts(normalized)
    previous = None
    for context in contexts:
        first_prompt = event_by_id.get(previous["prompt_event_id"], {}).get("prompt", "") if previous else ""
        second_prompt = event_by_id.get(context["prompt_event_id"], {}).get("prompt", "") if context["prompt_event_id"] else ""
        context["diff"] = diff_contexts(previous, context, first_prompt, second_prompt)
        previous = context

    for event in normalized:
        number = _integer(event.get("iteration"))
        if not number:
            continue
        item = iterations.setdefault(event["iteration_id"], _new_iteration(run_id, number))
        if event.get("iteration_source") == "viewer_inferred":
            item["source"] = "viewer_inferred"
        item["event_ids"].append(event.get("event_id", ""))
        if event.get("event") not in item["event_types"]:
            item["event_types"].append(event.get("event"))
        item["event_count"] = len(item["event_ids"])
        name = event.get("event")
        if name == "iteration_started":
            item["started_at"] = event.get("created_at", "")
        elif name == "iteration_finished":
            item["finished_at"] = event.get("created_at", "")
            item["finished_outcome"] = _text(event.get("outcome")) or "unknown"
        elif name == "prompt_built":
            item["started_at"] = item["started_at"] or event.get("created_at", "")
        elif name == "model_parsed":
            item["model_kind"] = _text(event.get("kind"))
            if event.get("kind") == "final":
                item["answer_preview"] = _clip_text(event.get("answer_preview") or "")
        elif name in FAILURE_OUTCOMES:
            item["outcome"] = name
        elif name == "tool_executed":
            tool = tool_by_event.get(event.get("event_id"))
            if tool:
                _append_unique(item["tool_call_ids"], tool["id"])
                if tool["name"] and tool["name"] not in item["tool_names"]:
                    item["tool_names"].append(tool["name"])
                if tool["status"] in {"error", "partial_success"}:
                    item["tools_failed"] += 1
                elif tool["status"] == "rejected":
                    item["tools_rejected"] += 1
        elif name == "tool_requested":
            tool = tool_by_event.get(event.get("event_id"))
            if tool:
                _append_unique(item["tool_call_ids"], tool["id"])
                if tool["name"] and tool["name"] not in item["tool_names"]:
                    item["tool_names"].append(tool["name"])
        if event.get("model_request_id"):
            _append_unique(item["model_request_ids"], event["model_request_id"])
        if event.get("tool_call_id"):
            _append_unique(item["tool_call_ids"], event["tool_call_id"])

    for item in iterations.values():
        # 轮次快照引用必须指向 contexts 中的同一份对象。
        context = next((candidate for candidate in contexts if candidate["iteration_id"] == item["id"]), None)
        if context:
            item["context_event_id"] = context["event_id"]
        if item["started_at"] and item["finished_at"]:
            item["duration_ms"] = _duration_between(item["started_at"], item["finished_at"])
        if item["finished_outcome"]:
            item["outcome"] = item["finished_outcome"]
        elif item["outcome"] == "unknown" and item["model_kind"]:
            item["outcome"] = item["model_kind"]
        item["status"], item["outcome"] = _iteration_status(item)

    status, status_source = _status_from(report, normalized)
    started = next((event.get("created_at") for event in normalized if event.get("event") == "run_started"), "")
    finished_event = next((event for event in reversed(normalized) if event.get("event") == "run_finished"), None)
    finished = finished_event.get("created_at", "") if finished_event else ""
    finish_duration = _number((finished_event or {}).get("run_duration_ms"))
    estimated_duration = _duration_between(started, finished or (normalized[-1].get("created_at", "") if normalized else ""))
    usage = _usage(model_requests, report)
    for request in model_requests:
        request.pop("_parsed", None)
    context_budget = next((context.get("prompt_budget_chars") for context in reversed(contexts) if context.get("prompt_budget_chars") is not None), None)
    context_used = next((context.get("prompt_chars") for context in reversed(contexts) if context.get("prompt_chars") is not None), None)

    run_started = next((event for event in normalized if event.get("event") == "run_started"), {})
    run = {
        "id": run_id,
        "run_id": run_id,
        "task_id": _text(report.get("task_id") or state.get("task_id") or run_started.get("task_id")),
        "session_id": _text(report.get("session_id") or run_started.get("session_id")),
        "status": status,
        "status_source": status_source,
        "status_confidence": "recorded" if status_source in {"report", "trace"} else "unknown",
        "is_terminal": status in TERMINAL_STATUSES,
        "provider": _text(report.get("provider")),
        "model": _text(report.get("model")),
        "tool_protocol": _text(report.get("tool_protocol")),
        "started_at": started,
        "finished_at": finished,
        "duration_ms": finish_duration if finish_duration is not None else estimated_duration,
        "duration_source": "trace" if finish_duration is not None else "viewer_estimate" if estimated_duration is not None else "unknown",
        "stop_reason": _text(report.get("stop_reason") or (finished_event or {}).get("stop_reason")),
        "user_request": _text(run_started.get("user_request")),
        "final_answer": _text(report.get("final_answer") or (finished_event or {}).get("final_answer")),
        "trace_schema": _text(next((event.get("trace_schema") for event in normalized if event.get("trace_schema")), "page-trace-v1")),
        "detail_available": any(event.get("event") in {"prompt_rendered", "model_http_request", "model_http_response", "model_extracted"} for event in normalized),
    }

    stats = {
        "iterations": len(iterations),
        "model_calls": len(model_requests),
        # 以实际发送为单位；只有响应记录时也能确认该次尝试存在。
        "http_attempts": sum(
            1 for request in model_requests
            for slot in request.get("http") or []
            if slot.get("request_event_id") or slot.get("response_event_id")
        ),
        "http_attempts_known": any(request.get("http") for request in model_requests),
        "tool_calls": len(tools),
        "tool_requested": sum(1 for tool in tools if tool["request_event_id"]),
        "tool_executed": sum(1 for tool in tools if tool["result_event_id"]),
        "tool_succeeded": sum(tool["status"] == "ok" for tool in tools),
        "tool_failed": sum(tool["status"] in {"error", "partial_success"} for tool in tools),
        "tool_rejected": sum(tool["status"] == "rejected" for tool in tools),
        "tool_skipped": sum(tool["status"] == "skipped" for tool in tools),
        "model_retries": sum(request.get("kind") == "retry" for request in model_requests),
        "model_failed": sum(request.get("status") == "failed" for request in model_requests),
        "checkpoints": sum(event.get("event") == "checkpoint_created" for event in normalized),
        "recovery_events": sum(event.get("category") == "recovery" for event in normalized),
        "event_count": len(normalized),
        "invalid_events_skipped": int(skipped or 0),
        "trace_truncated": bool(truncated),
        "usage": usage,
        "context": {
            "budget_chars": context_budget,
            "used_chars": context_used,
            "budget_kind": "characters" if context_budget is not None else "unknown",
            "token_estimate": contexts[-1].get("token_estimate") if contexts else None,
            "token_estimate_method": contexts[-1].get("token_estimate_method", "") if contexts else "",
        },
    }
    # 兼容旧消费者：tool_calls 在基础 Trace 里可能没有独立的请求事件。
    stats["tool_requests_recorded"] = stats["tool_requested"] > 0

    recovery_events = [event for event in normalized if event.get("category") == "recovery"]
    return {
        "schema_version": "page-inspection-v2",
        "run": run,
        "stats": stats,
        "iterations": list(iterations.values()),
        "contexts": contexts,
        "models": model_requests,
        "tools": tools,
        "recovery": {
            "events": recovery_events,
            "decision": report.get("recovery_decision") or next((event for event in reversed(recovery_events) if event.get("event") == "recovery_reconciled"), None),
            "journal": report.get("action_journal"),
            "checkpoint_id": report.get("checkpoint_id") or state.get("checkpoint_id"),
        },
        "evaluation": _evaluation(report),
        "raw": {"events": normalized, "truncated": bool(truncated), "skipped": int(skipped or 0)},
        "report": report or None,
    }
