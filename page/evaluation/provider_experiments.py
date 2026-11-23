"""Provider configuration and bounded benchmark experiments."""

from collections import Counter
from pathlib import Path

from ..config import load_project_env, provider_env
from ..providers.clients import AnthropicCompatibleModelClient, OpenAICompatibleModelClient
from .evaluator import run_fixed_benchmark


def _safe_mean(values):
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_ratio(numerator, denominator):
    if not denominator:
        return 0.0
    return numerator / denominator


def _provider_summary_from_artifact(payload):
    rows = list(payload.get("rows", []))
    cached_tokens = []
    cache_hits = []
    tool_steps = []
    attempts = []
    durations = []
    model_requests = []
    for row in rows:
        report = row.get("report", {})
        prompt_metadata = report.get("prompt_metadata", {})
        cached_tokens.append(int(prompt_metadata.get("cached_tokens", 0) or 0))
        cache_hits.append(bool(prompt_metadata.get("cache_hit")))
        tool_steps.append(int(row.get("tool_steps", 0)))
        attempts.append(int(row.get("attempts", 0)))
        durations.append(int(row.get("duration_ms", 0) or 0))
        model_requests.append(int(row.get("model_requests", 0) or 0))
    summary = payload.get("summary", {})
    return {
        "status": "completed",
        "task_count": int(summary.get("total_tasks", len(rows))),
        "pass_rate": float(summary.get("pass_rate", 0.0)),
        "avg_tool_steps": _safe_mean(tool_steps),
        "avg_attempts": _safe_mean(attempts),
        "avg_model_requests": _safe_mean(model_requests),
        "avg_duration_ms": _safe_mean(durations),
        "max_duration_ms": max(durations, default=0),
        "verifier_pass_rate": _safe_ratio(
            sum(1 for row in rows if row.get("verifier_passed")), len(rows)
        ),
        "total_input_tokens": sum(int(row.get("input_tokens", 0) or 0) for row in rows),
        "total_output_tokens": sum(int(row.get("output_tokens", 0) or 0) for row in rows),
        "total_tokens": sum(int(row.get("total_tokens", 0) or 0) for row in rows),
        "parse_retries": sum(int(row.get("parse_retries", 0) or 0) for row in rows),
        "unknown_tools": sum(int(row.get("unknown_tool_count", 0) or 0) for row in rows),
        "validation_errors": sum(int(row.get("validation_error_count", 0) or 0) for row in rows),
        "tool_errors": sum(int(row.get("tool_error_count", 0) or 0) for row in rows),
        "stop_reason_counts": dict(Counter(str(row.get("stop_reason", "")) for row in rows)),
        "failure_category_counts": dict(payload.get("failure_category_counts", {})),
        "cache_hit_rate": _safe_ratio(sum(1 for hit in cache_hits if hit), len(cache_hits)),
        "avg_cached_tokens": _safe_mean(cached_tokens),
        "artifact_path": payload.get("_artifact_path", ""),
    }


def _provider_profile(provider):
    load_project_env(Path.cwd())
    if provider == "gpt":
        api_key = provider_env(
            "PAGE_OPENAI_API_KEY",
            ("OPENAI_API_KEY", "PAGE_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "PAGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        )
        if not api_key:
            return {"provider": provider, "status": "blocked", "reason": "PAGE_OPENAI_API_KEY, OPENAI_API_KEY, or shared right.codes key missing"}
        return {
            "provider": provider,
            "status": "ready",
            "model": provider_env("PAGE_OPENAI_MODEL", ("OPENAI_MODEL",), "gpt-5.4"),
            "base_url": provider_env("PAGE_OPENAI_API_BASE", ("OPENAI_API_BASE",), "https://api.openai.com/v1"),
            "api_key": api_key,
        }
    if provider == "deepseek":
        api_key = provider_env("PAGE_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        if not api_key:
            return {"provider": provider, "status": "blocked", "reason": "PAGE_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY missing"}
        return {
            "provider": provider,
            "status": "ready",
            "model": provider_env("PAGE_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",), "deepseek-v4-pro"),
            "base_url": provider_env("PAGE_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), "https://api.deepseek.com/anthropic"),
            "api_key": api_key,
        }
    api_key = provider_env(
        "PAGE_ANTHROPIC_API_KEY",
        ("ANTHROPIC_API_KEY", "PAGE_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "PAGE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    if not api_key:
        return {"provider": "claude", "status": "blocked", "reason": "PAGE_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY missing"}
    return {
        "provider": "claude",
        "status": "ready",
        "model": provider_env("PAGE_ANTHROPIC_MODEL", ("ANTHROPIC_MODEL",), "claude-sonnet-4-6"),
        "base_url": provider_env("PAGE_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), "https://www.right.codes/claude/v1"),
        "api_key": api_key,
    }


def _make_provider_client(provider):
    profile = _provider_profile(provider)
    if profile["status"] != "ready":
        raise RuntimeError(profile["reason"])
    timeout = 60
    if provider == "gpt":
        return OpenAICompatibleModelClient(
            model=profile["model"],
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            temperature=0.0,
            timeout=timeout,
        )
    return AnthropicCompatibleModelClient(
        model=profile["model"],
        base_url=profile["base_url"],
        api_key=profile["api_key"],
        temperature=0.0,
        timeout=timeout,
    )


def run_provider_experiments(
    benchmark_path,
    workspace_root,
    artifact_root,
    max_new_tokens=64,
    providers=None,
    task_ids=None,
    repetitions=1,
    tool_protocol="text",
    max_total_runs=12,
):
    benchmark_path = Path(benchmark_path)
    workspace_root = Path(workspace_root)
    artifact_root = Path(artifact_root)
    provider_results = []
    selected_providers = tuple(providers or ("deepseek",))
    unknown_providers = sorted(set(selected_providers) - {"gpt", "claude", "deepseek"})
    if unknown_providers:
        raise ValueError(f"unknown providers: {', '.join(unknown_providers)}")
    completed_runs = 0
    for provider_name in selected_providers:
        profile = _provider_profile(provider_name)
        if profile["status"] != "ready":
            provider_results.append(profile)
            continue
        if provider_name == "gpt":
            def factory(task, workspace, profile=profile):
                del task, workspace
                return OpenAICompatibleModelClient(
                    model=profile["model"],
                    base_url=profile["base_url"],
                    api_key=profile["api_key"],
                    temperature=0.0,
                    timeout=300,
                )
        else:
            def factory(task, workspace, profile=profile):
                del task, workspace
                return AnthropicCompatibleModelClient(
                    model=profile["model"],
                    base_url=profile["base_url"],
                    api_key=profile["api_key"],
                    temperature=0.0,
                    timeout=300,
                )
        artifact_path = artifact_root / f"{provider_name}-benchmark.json"
        try:
            payload = run_fixed_benchmark(
                benchmark_path=benchmark_path,
                artifact_path=artifact_path,
                workspace_root=workspace_root / provider_name,
                model_name=profile["provider"],
                model_version=profile["model"],
                max_new_tokens=max_new_tokens,
                model_client_factory=factory,
                task_ids=task_ids,
                repetitions=repetitions,
                tool_protocol=tool_protocol,
                max_total_runs=max_total_runs - completed_runs,
            )
            completed_runs += len(payload.get("rows", []))
            payload["_artifact_path"] = str(artifact_path)
            result = _provider_summary_from_artifact(payload)
            result["provider"] = provider_name
            result["model"] = profile["model"]
            result["tool_protocol"] = tool_protocol
            provider_results.append(result)
        except Exception as exc:
            provider_results.append(
                {
                    "provider": provider_name,
                    "status": "error",
                    "model": profile["model"],
                    "reason": str(exc),
                }
            )
    return {
        "providers": provider_results,
        "configuration": {
            "selected_providers": list(selected_providers),
            "task_ids": list(task_ids or []),
            "repetitions": int(repetitions),
            "tool_protocol": tool_protocol,
            "max_total_runs": int(max_total_runs),
        },
        "completed_runs": completed_runs,
    }
