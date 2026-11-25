"""Normalize Page trace events into one read-only inspection model.

The viewer consumes both current detailed traces and older compact traces. This
module keeps compatibility rules in one place so every UI view shares the same
iteration, model, tool, context, and metric interpretation.
"""

from __future__ import annotations

from collections import OrderedDict
from difflib import unified_diff

TERMINAL_STATUSES = {"completed", "failed", "stopped", "error"}
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
    return int(number) if number is not None and float(number).is_integer() else None


def _text(value):
    return str(value).strip() if value is not None else ""


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
        if name == "model_http_request" and current_model_request:
            event.setdefault("http_attempt", _integer(event.get("attempt")))
        if name in {"model_extracted", "model_parsed", "model_failed"} and current_model_request:
            event.setdefault("model_request_id", current_model_request)
        if event.get("model_request_id") and name in {"prompt_built", "prompt_rendered", "model_requested", "model_http_request", "model_http_response", "model_http_error", "model_extracted", "model_parsed", "model_failed"}:
            event["model_request_source"] = "trace" if explicit_model_request_id else "viewer_inferred"

        if name in {"tool_requested", "tool_stage", "tool_executed"}:
            explicit_tool = _text(event.get("tool_call_id") or event.get("call_id"))
            tool_name = _text(event.get("name"))
            key = (current_iteration, tool_name)
            if name == "tool_requested" or key not in active_tool:
                tool_ordinals[key] = tool_ordinals.get(key, 0) + 1
            tool_id = explicit_tool or active_tool.get(key) or _tool_call_id(run_id, current_iteration, tool_ordinals[key])
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
        "events": [],
        "model_request_ids": [],
        "tool_call_ids": [],
        "status": "incomplete",
        "outcome": "unknown",
        "started_at": "",
        "finished_at": "",
        "duration_ms": None,
        "context": None,
        "model": None,
        "tools": [],
        "evidence": [],
    }


def _append_unique(items, value):
    if value and value not in items:
        items.append(value)


def _context_snapshot(event):
    metadata = dict(event.get("prompt_metadata") or {})
    if not metadata and event.get("sections"):
        metadata = {
            "sections": event.get("sections"),
            "section_order": event.get("section_order"),
            "budget_reductions": event.get("budget_reductions"),
        }
    sections = dict(metadata.get("sections") or {})
    return {
        "event_id": event.get("event_id", ""),
        "sequence": event.get("event_seq"),
        "iteration_id": event.get("iteration_id", ""),
        "prompt": event.get("prompt", ""),
        "prompt_chars": metadata.get("prompt_chars"),
        "prompt_budget_chars": metadata.get("prompt_budget_chars"),
        "prompt_over_budget": bool(metadata.get("prompt_over_budget", False)),
        "token_estimate": metadata.get("token_estimate"),
        "token_estimate_method": metadata.get("token_estimate_method", ""),
        "section_order": list(metadata.get("section_order") or []),
        "section_budgets": dict(metadata.get("section_budgets") or {}),
        "sections": sections,
        "context_blocks": list(metadata.get("context_blocks") or []),
        "budget_reductions": list(metadata.get("budget_reductions") or []),
        "reduction_order": list(metadata.get("reduction_order") or []),
        "history": dict(metadata.get("history") or {}),
        "relevant_memory": dict(metadata.get("relevant_memory") or {}),
        "stale_paths": list(metadata.get("stale_paths") or metadata.get("stale_rejected_paths") or []),
        "recovery_decision": dict(metadata.get("recovery_decision") or {}),
        "source": event.get("iteration_source", "trace"),
        "detail_available": bool(event.get("prompt")),
    }


def _context_diff(previous, current):
    if not previous or not current:
        return {"available": False, "reason": "需要两个有上下文证据的轮次。", "sections": [], "text": ""}
    changes = []
    before_sections = previous.get("sections") or {}
    after_sections = current.get("sections") or {}
    section_names = list(dict.fromkeys([*previous.get("section_order", []), *current.get("section_order", []), *before_sections, *after_sections]))
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
    before_text = _text(previous.get("prompt"))
    after_text = _text(current.get("prompt"))
    diff_text = ""
    if before_text and after_text and before_text != after_text:
        lines = list(unified_diff(before_text.splitlines(), after_text.splitlines(), fromfile="previous", tofile="current", lineterm=""))
        diff_text = "\n".join(lines[:240])
    return {
        "available": True,
        "source": "metadata" if changes else ("viewer_text_diff" if diff_text else "metadata"),
        "sections": changes,
        "text": diff_text,
        "truncated": bool(diff_text and len(diff_text.splitlines()) > 240),
    }


def _model_requests(events):
    requests = OrderedDict()
    current_id = ""
    model_events = {
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
        elif not request_id and name in model_events:
            request_id = current_id
        elif request_id and name in model_events:
            current_id = request_id
        if not request_id or name not in model_events:
            continue
        item = requests.setdefault(request_id, {
            "id": request_id,
            "iteration_id": event.get("iteration_id", ""),
            "iteration": event.get("iteration"),
            "event_ids": [],
            "requested": None,
            "http_attempts": [],
            "prompt": None,
            "extracted": None,
            "parsed": None,
            "status": "unknown",
            "source": "trace" if event.get("model_request_source") == "trace" else "viewer_inferred",
        })
        if event.get("model_request_source") == "trace":
            item["source"] = "trace"
        item["event_ids"].append(event.get("event_id", ""))
        if event.get("iteration_id") and not item["iteration_id"]:
            item["iteration_id"] = event["iteration_id"]
        if name == "model_requested":
            item["requested"] = event
        elif name == "prompt_rendered":
            item["prompt"] = event
        elif name == "model_http_request":
            item["http_attempts"].append({"direction": "request", **event})
        elif name == "model_http_response":
            item["http_attempts"].append({"direction": "response", **event})
        elif name == "model_http_error":
            item["http_attempts"].append({"direction": "error", **event})
        elif name == "model_extracted":
            item["extracted"] = event
        elif name == "model_parsed":
            item["parsed"] = event
        elif name == "model_failed":
            item["status"] = "failed"
        if item["parsed"]:
            kind = item["parsed"].get("kind")
            item["status"] = {"tool": "tool", "final": "final", "retry": "retry"}.get(kind, kind or item["status"])
        elif item["http_attempts"]:
            item["status"] = "http_observed"
    return list(requests.values())


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
            "phases": [],
            "request": None,
            "result": None,
            "status": "unknown",
            "risk_level": "",
            "approval": "",
            "read_only": None,
            "workspace_changed": None,
            "affected_paths": [],
            "diff_summary": [],
            "action_id": "",
            "action_phase": "",
            "recovery_action": "",
            "source": "trace" if event.get("tool_call_source") == "trace" else "viewer_inferred",
        })
        if event.get("tool_call_source") == "trace":
            item["source"] = "trace"
        item["event_ids"].append(event.get("event_id", ""))
        if name == "tool_requested":
            item["request"] = event
        elif name == "tool_stage":
            item["phases"].append(event)
            if event.get("approval"):
                item["approval"] = event.get("approval")
        elif name == "tool_executed":
            item["result"] = event
            item["status"] = event.get("tool_status") or item["status"]
            item["risk_level"] = event.get("risk_level", item["risk_level"])
            item["read_only"] = event.get("read_only", item["read_only"])
            item["workspace_changed"] = event.get("workspace_changed", item["workspace_changed"])
            item["affected_paths"] = list(event.get("affected_paths") or [])
            item["diff_summary"] = list(event.get("diff_summary") or [])
            item["action_id"] = _text(event.get("action_id"))
            item["action_phase"] = _text(event.get("action_phase"))
            item["recovery_action"] = _text(event.get("recovery_action"))
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
    values = []
    for request in model_requests:
        metadata = dict((request.get("parsed") or {}).get("completion_metadata") or {})
        if metadata:
            values.append(metadata)
    if not values:
        metadata = dict((report or {}).get("prompt_metadata") or {})
        if any(_number(metadata.get(key)) is not None for key in ("input_tokens", "output_tokens", "total_tokens")):
            values.append(metadata)
    input_total = sum(_number(item.get("input_tokens")) or 0 for item in values)
    output_total = sum(_number(item.get("output_tokens")) or 0 for item in values)
    total_values = [_number(item.get("total_tokens")) for item in values]
    total_known = all(value is not None for value in total_values) if values else False
    total = sum(value or 0 for value in total_values) if total_known else input_total + output_total
    return {
        "input_tokens": int(input_total) if any(_number(item.get("input_tokens")) is not None for item in values) else None,
        "output_tokens": int(output_total) if any(_number(item.get("output_tokens")) is not None for item in values) else None,
        "total_tokens": int(total) if values and (total_known or input_total or output_total) else None,
        "known": bool(values),
        "source": "trace" if any((request.get("parsed") or {}).get("completion_metadata") for request in model_requests) else "report",
        "calls_with_usage": len(values),
    }


def build_inspection(run_id, events, report=None, state=None, truncated=False, skipped=0):
    report = dict(report or {})
    state = dict(state or {})
    normalized = normalize_events(events, run_id, state, report)
    model_requests = _model_requests(normalized)
    tools = _tool_calls(normalized)
    iterations = OrderedDict()
    contexts = []
    previous_context = None

    for event in normalized:
        number = _integer(event.get("iteration"))
        if number:
            item = iterations.setdefault(event["iteration_id"], _new_iteration(run_id, number))
            if event.get("iteration_source") == "viewer_inferred":
                item["source"] = "viewer_inferred"
            item["event_ids"].append(event.get("event_id", ""))
            item["event_types"].append(event.get("event")) if event.get("event") not in item["event_types"] else None
            item["events"].append(event)
            if event.get("event") == "iteration_started":
                item["started_at"] = event.get("created_at", "")
            if event.get("event") == "iteration_finished":
                item["finished_at"] = event.get("created_at", "")
                item["outcome"] = event.get("outcome", "unknown")
            if event.get("event") == "prompt_built":
                item["started_at"] = item["started_at"] or event.get("created_at", "")
                snapshot = _context_snapshot(event)
                item["context"] = snapshot
                contexts.append(snapshot)
                snapshot["diff"] = _context_diff(previous_context, snapshot)
                previous_context = snapshot
            elif event.get("event") == "prompt_rendered":
                snapshot = _context_snapshot(event)
                item["context"] = snapshot
                if contexts and contexts[-1].get("iteration_id") == snapshot.get("iteration_id"):
                    merged = dict(contexts[-1])
                    for key, value in snapshot.items():
                        if value not in (None, "", [], {}):
                            merged[key] = value
                    snapshot = merged
                    contexts[-1] = snapshot
                else:
                    contexts.append(snapshot)
                snapshot["diff"] = _context_diff(previous_context, snapshot)
                previous_context = snapshot
            if event.get("event") == "model_parsed":
                item["model"] = next((request for request in model_requests if request["id"] == event.get("model_request_id")), None)
                kind = event.get("kind")
                if kind == "final":
                    item["outcome"] = "final"
                elif kind == "retry":
                    item["outcome"] = "retry"
                elif kind == "tool":
                    item["outcome"] = "tool"
            if event.get("event") in {"model_failed", "context_failed"}:
                item["outcome"] = "failed"
            if event.get("event") == "tool_executed":
                tool = next((candidate for candidate in tools if event.get("event_id") in candidate["event_ids"]), None)
                if tool:
                    item["tools"].append(tool)
                    _append_unique(item["tool_call_ids"], tool["id"])
                    if tool["status"] in {"error", "rejected", "partial_success"}:
                        item["outcome"] = "tool_error"
            if event.get("model_request_id"):
                _append_unique(item["model_request_ids"], event["model_request_id"])
            if event.get("tool_call_id"):
                _append_unique(item["tool_call_ids"], event["tool_call_id"])
            if event.get("event") in {"checkpoint_created", "recovery_reconciled", "runtime_identity_mismatch"}:
                item["evidence"].append(event)

    for item in iterations.values():
        if item["started_at"] and item["finished_at"]:
            item["duration_ms"] = _duration_between(item["started_at"], item["finished_at"])
        if item["outcome"] == "unknown":
            if item["tools"]:
                item["outcome"] = "tool"
            elif item["model"] and item["model"].get("status"):
                item["outcome"] = item["model"]["status"]
        item["status"] = "failed" if item["outcome"] in {"failed", "tool_error"} else "completed" if item["outcome"] in {"final", "tool", "retry"} else "incomplete"

    status, status_source = _status_from(report, normalized)
    started = next((event.get("created_at") for event in normalized if event.get("event") == "run_started"), "")
    finished_event = next((event for event in reversed(normalized) if event.get("event") == "run_finished"), None)
    finished = finished_event.get("created_at", "") if finished_event else ""
    finish_duration = _number((finished_event or {}).get("run_duration_ms"))
    estimated_duration = _duration_between(started, finished or (normalized[-1].get("created_at", "") if normalized else ""))
    logical_calls = len(model_requests) or _integer(report.get("attempts")) or _integer(state.get("attempts")) or 0
    executed_tools = [item for item in tools if item.get("result")]
    requested_tools = len(tools)
    usage = _usage(model_requests, report)
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
        "model_calls": logical_calls,
        "http_attempts": sum(len(request.get("http_attempts") or []) for request in model_requests),
        "http_attempts_known": any(request.get("http_attempts") for request in model_requests),
        "tool_calls": requested_tools or _integer(report.get("tool_steps")) or _integer(state.get("tool_steps")) or 0,
        "tool_executed": len(executed_tools),
        "tool_succeeded": sum(item.get("status") in {"ok", "partial_success"} for item in tools),
        "tool_failed": sum(item.get("status") in {"error", "partial_success"} for item in tools),
        "tool_rejected": sum(item.get("status") == "rejected" for item in tools),
        "model_retries": sum((request.get("parsed") or {}).get("kind") == "retry" for request in model_requests),
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

    recovery_events = [event for event in normalized if event.get("category") == "recovery"]
    return {
        "schema_version": "page-inspection-v1",
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
