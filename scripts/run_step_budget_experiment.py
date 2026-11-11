#!/usr/bin/env python3
"""Run deterministic step-budget sensitivity checks without API calls."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from page.evaluation.evaluator import run_fixed_benchmark  # noqa: E402


def _comma_ints(value):
    budgets = [int(item.strip()) for item in str(value).split(",") if item.strip()]
    if not budgets or any(item < 1 for item in budgets):
        raise argparse.ArgumentTypeError("budgets must be positive comma-separated integers")
    return budgets


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Run an offline FakeModel comparison of tool-step budgets."
    )
    parser.add_argument("--mode", choices=("fake",), default="fake")
    parser.add_argument("--budgets", type=_comma_ints, default=_comma_ints("3,6,9"))
    parser.add_argument("--benchmark-path", default="benchmarks/coding_tasks.json")
    parser.add_argument("--task-ids", default="", help="Optional comma-separated task ids.")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-total-runs", type=int, default=36)
    parser.add_argument("--workspace-root", default="artifacts/step-budget-workspaces")
    parser.add_argument("--output-json", required=True)
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    task_ids = [item.strip() for item in args.task_ids.split(",") if item.strip()]
    benchmark = json.loads(Path(args.benchmark_path).read_text(encoding="utf-8"))
    selected_count = sum(
        1 for task in benchmark["tasks"] if not task_ids or str(task["id"]) in task_ids
    )
    requested_runs = selected_count * args.repetitions * len(args.budgets)
    if requested_runs > args.max_total_runs:
        raise ValueError(
            f"requested {requested_runs} runs exceeds max_total_runs={args.max_total_runs}"
        )

    output_path = Path(args.output_json)
    rows = []
    for budget in args.budgets:
        detail_path = output_path.parent / f"step-budget-{budget}-details.json"
        payload = run_fixed_benchmark(
            benchmark_path=args.benchmark_path,
            artifact_path=detail_path,
            workspace_root=Path(args.workspace_root) / str(budget),
            task_ids=task_ids,
            repetitions=args.repetitions,
            tool_protocol="text",
            max_total_runs=selected_count * args.repetitions,
            step_budget_override=budget,
        )
        result_rows = payload["rows"]
        rows.append(
            {
                "budget": budget,
                "run_count": len(result_rows),
                "pass_rate": payload["summary"]["pass_rate"],
                "verifier_pass_rate": sum(1 for row in result_rows if row["verifier_passed"]) / len(result_rows),
                "avg_tool_steps": sum(row["tool_steps"] for row in result_rows) / len(result_rows),
                "max_tool_steps": max(row["tool_steps"] for row in result_rows),
                "stop_reason_counts": _counts(row["stop_reason"] for row in result_rows),
                "failure_category_counts": payload["failure_category_counts"],
                "detail_artifact": str(detail_path),
            }
        )

    result = {
        "mode": "fake",
        "budgets": args.budgets,
        "task_count": selected_count,
        "repetitions": args.repetitions,
        "total_runs": requested_runs,
        "rows": rows,
        "interpretation_boundary": (
            "FakeModel results verify budget enforcement and stop contracts only; "
            "they do not prove that six steps is globally optimal."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _counts(values):
    result = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
