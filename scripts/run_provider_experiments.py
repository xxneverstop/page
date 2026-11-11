#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from page.evaluation.metrics import run_provider_experiments  # noqa: E402


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Run bounded provider experiments for page benchmark tasks.")
    parser.add_argument("--benchmark-path", default="benchmarks/coding_tasks.json", help="Path to benchmark task JSON.")
    parser.add_argument("--workspace-root", default="artifacts/provider-workspaces", help="Workspace root for provider experiment copies.")
    parser.add_argument("--artifact-root", default="artifacts/provider-artifacts", help="Directory to store provider benchmark artifacts.")
    parser.add_argument("--output-json", required=True, help="Path to output provider experiment JSON.")
    parser.add_argument("--max-new-tokens", type=int, default=64, help="Max output tokens per provider run.")
    parser.add_argument("--providers", default="deepseek", help="Comma-separated provider names: deepseek,gpt,claude.")
    parser.add_argument("--task-ids", default="", help="Optional comma-separated benchmark task ids.")
    parser.add_argument("--repetitions", type=int, default=1, help="Runs per selected task.")
    parser.add_argument("--tool-protocol", choices=("text", "native"), default="text")
    parser.add_argument("--max-total-runs", type=int, default=12, help="Hard cap across all providers.")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    payload = run_provider_experiments(
        benchmark_path=args.benchmark_path,
        workspace_root=args.workspace_root,
        artifact_root=args.artifact_root,
        max_new_tokens=args.max_new_tokens,
        providers=[item.strip() for item in args.providers.split(",") if item.strip()],
        task_ids=[item.strip() for item in args.task_ids.split(",") if item.strip()],
        repetitions=args.repetitions,
        tool_protocol=args.tool_protocol,
        max_total_runs=args.max_total_runs,
    )
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
