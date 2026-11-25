"""Agent control loop extracted from the runtime facade."""

from functools import partial
import time

from .recovery.checkpoint import CHECKPOINT_NONE_STATUS, CHECKPOINT_PARTIAL_STALE_STATUS, CHECKPOINT_WORKSPACE_MISMATCH_STATUS
from .context.manager import ProtectedContextOverflow
from .providers.tool_calling import ModelResponse
from .task_state import TaskState
from .workspace import clip, now


class AgentLoop:
    def __init__(self, agent):
        self.agent = agent

    def run(self, user_message):
        agent = self.agent
        trace_detail = agent.trace_detail
        run_started_at = time.monotonic()
        agent.memory.set_task_summary(user_message)
        agent.record({"role": "user", "content": user_message, "created_at": now()})

        task_state = TaskState.create(run_id=agent.new_run_id(), task_id=agent.new_task_id(), user_request=user_message)
        task_state.resume_status = agent.resume_state.get("status", CHECKPOINT_NONE_STATUS)
        agent.current_task_state = task_state
        agent._trace_sequence = 0
        agent._active_trace_tool_call = None
        agent.current_run_dir = agent.run_store.start_run(task_state)
        agent.emit_trace(
            task_state,
            "run_started",
            {
                "task_id": task_state.task_id,
                "user_request": user_message if trace_detail else clip(user_message, 300),
                **({"full_request": True} if trace_detail else {}),
            },
        )
        agent.emit_trace(
            task_state,
            "recovery_reconciled",
            dict(getattr(agent, "recovery_decision", {}) or {}),
        )

        tool_steps = 0
        attempts = 0
        max_attempts = max(agent.max_steps * 3, agent.max_steps + 4)
        finalization_attempted = False
        iteration_closed = False

        def finish_iteration(outcome, **details):
            nonlocal iteration_closed
            if iteration_closed:
                return
            iteration_closed = True
            agent.emit_trace(
                task_state,
                "iteration_finished",
                {"outcome": outcome, "tool_steps": task_state.tool_steps, **details},
            )

        # 这是 agent 的主循环，可以按“感知 -> 决策 -> 行动 -> 记录”来理解：
        # 1. 感知：重新组 prompt，把当前状态整理给模型看
        # 2. 决策：让模型返回一个工具调用，或一个最终答案
        # 3. 行动：如果是工具调用，就执行工具
        # 4. 记录：把结果写回 history / task_state / trace / memory
        # 然后进入下一轮，直到停机条件满足
        # max_steps is the tool budget, not the answer budget.  After the last
        # tool result, give the model one synthesis-only turn so useful evidence
        # is not discarded just because every tool slot was used.
        while attempts < max_attempts and (tool_steps < agent.max_steps or not finalization_attempted):
            finalizing = tool_steps >= agent.max_steps
            if finalizing:
                finalization_attempted = True
            attempts += 1
            task_state.record_attempt()
            iteration_closed = False
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                "iteration_started",
                {"attempt": task_state.attempts, "tool_steps": task_state.tool_steps},
            )
            prompt_started_at = time.monotonic()
            try:
                prompt, prompt_metadata = agent._build_prompt_and_metadata(user_message)
                if finalizing:
                    final_format = (
                        "as normal text"
                        if agent.tool_protocol == "native"
                        else "wrapped in <final>...</final>"
                    )
                    prompt += (
                        "\n\nFINALIZATION PHASE:\n"
                        "The tool-call budget is exhausted. Do not request or call another tool. "
                        "Return the best answer supported by the evidence already collected, "
                        f"{final_format}. If something is missing, state the blocking fact and "
                        "the next concrete action instead of attempting another tool call."
                    )
                    prompt_metadata["finalization_only"] = True
                    agent.emit_trace(
                        task_state,
                        "finalization_requested",
                        {
                            "attempts": task_state.attempts,
                            "tool_steps": task_state.tool_steps,
                        },
                    )
            except ProtectedContextOverflow as exc:
                final = "Stopped because protected context exceeds the configured prompt budget."
                task_state.stop_context_overflow(final)
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "context_failed",
                    {"error_code": "protected_context_overflow", "error": str(exc)},
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="protected_context_overflow")
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "protected_context_overflow"},
                )
                finish_iteration("context_failed", reason="protected_context_overflow")
                agent.emit_trace(
                    task_state,
                    "run_finished",
                    {
                        "status": task_state.status,
                        "stop_reason": task_state.stop_reason,
                        "final_answer": final,
                        "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
                    },
                )
                agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
                return final
            agent.emit_trace(
                task_state,
                "prompt_built",
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                },
            )
            if trace_detail:
                # 原生工具续接可能只发送工具结果，本地拼接文本与实际请求体分开记录。
                agent.emit_trace(task_state, "prompt_rendered", {
                    "attempts": task_state.attempts,
                    "tool_protocol": agent.tool_protocol,
                    # 这是本地渲染文本；原生工具续接时 Provider 实际入参以 HTTP 请求体为准。
                    "prompt_source": "local_render",
                    "section_order": prompt_metadata.get("section_order", []),
                    "sections": prompt_metadata.get("sections", {}),
                    "prompt": prompt,
                    "finalization_only": finalizing,
                })
            if prompt_metadata.get("resume_status") == CHECKPOINT_PARTIAL_STALE_STATUS:
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="freshness_mismatch")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "freshness_mismatch",
                    },
                )
            elif prompt_metadata.get("resume_status") == CHECKPOINT_WORKSPACE_MISMATCH_STATUS:
                agent.emit_trace(
                    task_state,
                    "runtime_identity_mismatch",
                    {
                        "fields": list(prompt_metadata.get("runtime_identity_mismatch_fields", [])),
                    },
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="workspace_mismatch")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "workspace_mismatch",
                    },
                )
            if prompt_metadata.get("budget_reductions"):
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="context_reduction")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "context_reduction",
                    },
                )
            agent.emit_trace(
                task_state,
                "model_requested",
                {
                    "attempts": task_state.attempts,
                    "tool_steps": task_state.tool_steps,
                    "prompt_cache_key": prompt_metadata.get("prompt_cache_key"),
                },
            )
            prompt_cache_key = None
            prompt_cache_retention = None
            if getattr(agent.model_client, "supports_prompt_cache", False):
                # 只有后端明确支持时，才把稳定前缀的 hash 作为 cache key 发出去。
                prompt_cache_key = prompt_metadata.get("prompt_cache_key")
                prompt_cache_retention = "in_memory"
            model_started_at = time.monotonic()
            try:
                model_kwargs = agent.model_request_kwargs()
                # 按调用绑定 run，子 Agent 共享客户端时也不会写错日志文件。
                if trace_detail and getattr(agent.model_client, "supports_http_trace", False):
                    model_kwargs["trace_callback"] = partial(agent.emit_trace, task_state)
                raw = agent.model_client.complete(
                    prompt,
                    agent.max_new_tokens,
                    prompt_cache_key=prompt_cache_key,
                    prompt_cache_retention=prompt_cache_retention,
                    **model_kwargs,
                )
            except Exception as exc:
                final = f"Stopped because the model request failed: {type(exc).__name__}."
                task_state.stop_model_error(final)
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "model_failed",
                    {
                        "error_type": type(exc).__name__,
                        "error": agent.redact_text(str(exc)),
                        "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                    },
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="model_error")
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "model_error"},
                )
                finish_iteration("model_failed", reason=type(exc).__name__)
                agent.emit_trace(
                    task_state,
                    "run_finished",
                    {
                        "status": task_state.status,
                        "stop_reason": task_state.stop_reason,
                        "final_answer": final,
                        "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
                    },
                )
                agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
                return final
            if trace_detail:
                native_response = isinstance(raw, ModelResponse)
                agent.emit_trace(task_state, "model_extracted", {
                    "format": "native" if native_response else "text",
                    "text": raw.text if native_response else str(raw),
                    "tool_calls": [call.to_dict() for call in raw.tool_calls] if native_response else [],
                })
            agent.accept_model_response(raw)
            completion_metadata = dict(getattr(agent.model_client, "last_completion_metadata", {}) or {})
            response_metadata = dict(getattr(raw, "metadata", {}) or {})
            completion_metadata.update(response_metadata)
            if completion_metadata:
                # 把后端返回的 usage/cache 统计并回 prompt_metadata，
                # 方便统一写入 report 和 trace。
                prompt_metadata.update(completion_metadata)
            agent.last_completion_metadata = completion_metadata
            agent.last_prompt_metadata = prompt_metadata
            kind, payload = agent.parse_model_response(raw)
            agent.emit_trace(
                task_state,
                "model_parsed",
                {
                    "kind": kind,
                    "tool_name": payload.get("name", "") if kind == "tool" and isinstance(payload, dict) else "",
                    "answer_preview": agent.redact_text(clip(payload, 120)) if kind == "final" else "",
                    "completion_metadata": completion_metadata,
                    "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                    **({"payload": payload} if trace_detail else {}),
                },
            )

            if kind == "tool":
                if finalizing:
                    finish_iteration("finalization_tool_rejected", next_step="stop")
                    break
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                call_id = str(payload.get("call_id") or f"{task_state.run_id}:iteration:{task_state.attempts:04d}:tool:1")
                task_state.record_tool(name)
                # 请求事件始终落盘，才能区分"模型请求了工具"和"工具实际执行"；
                # 参数正文只在详细采集时记录，基础 Trace 保持精简。
                agent.emit_trace(task_state, "tool_requested", {
                    "name": name,
                    "call_id": call_id,
                    "tool_call_id": call_id,
                    **({"args": args} if trace_detail else {}),
                })
                tool_started_at = time.monotonic()
                agent._active_trace_tool_call = {
                    "tool_call_id": call_id,
                    "model_request_id": f"{task_state.run_id}:model:{task_state.attempts:04d}",
                }
                try:
                    tool_result = agent.execute_tool(name, args)
                finally:
                    agent._active_trace_tool_call = None
                result = tool_result.content
                agent.record(
                    {
                        "role": "tool",
                        "name": name,
                        "args": args,
                        "content": result,
                        "metadata": dict(tool_result.metadata or {}),
                        "call_id": call_id,
                        "created_at": now(),
                    }
                )
                agent.record_native_tool_observation(
                    call_id,
                    name,
                    result,
                    is_error=tool_result.metadata.get("tool_status") != "ok",
                )
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "tool_executed",
                    {
                        "name": name,
                        "args": args,
                        "call_id": call_id,
                        "tool_call_id": call_id,
                        "result": result if trace_detail else clip(result, 500),
                        "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                        **({"verbose": True} if trace_detail else {}),
                        **dict(tool_result.metadata or {}),
                    },
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="tool_executed")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "tool_executed",
                    },
                )
                finish_iteration("tool", tool_call_id=call_id, tool_name=name, next_step="context")
                continue

            if kind == "retry":
                agent.record({"role": "assistant", "content": payload, "created_at": now()})
                agent.run_store.write_task_state(task_state)
                finish_iteration("retry", next_step="model")
                if finalizing:
                    break
                continue

            final = str(payload or "").strip()
            agent.record({"role": "assistant", "content": final, "created_at": now()})
            agent.clear_native_tool_state()
            task_state.finish_success(final)
            agent.promote_durable_memory(user_message, final)
            # 普通 CLI 运行没有独立 Verifier，不能把最终回答写成验收通过。
            finish_iteration("final", next_step="run_finished", answer_preview=agent.redact_text(clip(final, 120)))
            checkpoint = agent.create_checkpoint(task_state, user_message, trigger="run_finished")
            agent.run_store.write_task_state(task_state)
            agent.emit_trace(
                task_state,
                "checkpoint_created",
                {
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "trigger": "run_finished",
                },
            )
            agent.maybe_inject_fault("after_checkpoint_before_final")
            agent.emit_trace(
                task_state,
                "run_finished",
                {
                    "status": task_state.status,
                    "stop_reason": task_state.stop_reason,
                    "final_answer": final,
                    "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
                },
            )
            agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
            return final

        if attempts >= max_attempts and tool_steps < agent.max_steps:
            final = "Stopped after too many malformed model responses without a valid tool call or final answer."
            task_state.stop_retry_limit(final)
        else:
            final = "Stopped after reaching the step limit without a final answer."
            task_state.stop_step_limit(final)
        agent.record({"role": "assistant", "content": final, "created_at": now()})
        agent.promote_durable_memory(user_message, final)
        finish_iteration("stopped", reason=task_state.stop_reason)
        agent.run_store.write_task_state(task_state)
        checkpoint = agent.create_checkpoint(task_state, user_message, trigger=task_state.stop_reason or "run_stopped")
        agent.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": task_state.stop_reason or "run_stopped",
            },
        )
        agent.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
        return final
