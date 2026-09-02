"""Windows-friendly recovery demo and paired experiment entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from page.evaluation.recovery_experiment import RECOVERY_EXPERIMENT_TASKS, run_recovery_experiment


DEFAULT_FAKE_ARTIFACT = Path("artifacts/interview-recovery-fake.json")
DEFAULT_DEEPSEEK_ARTIFACT = Path("artifacts/interview-recovery-deepseek.json")


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Page recovery interview demo.")
    parser.add_argument("--scenario", default="recovery", choices=("recovery",))
    parser.add_argument("--model", default="fake", choices=("fake", "deepseek"))
    parser.add_argument("--repetitions", type=int, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--task", action="append", choices=RECOVERY_EXPERIMENT_TASKS)
    parser.add_argument("--mode", action="append", choices=("blind", "guarded"))
    parser.add_argument("--show-latest", action="store_true")
    parser.add_argument("--all", action="store_true", help="Compatibility alias for the offline recovery demo.")
    return parser


def _deepseek_factory(**_kwargs):
    from page.evaluation.metrics import _make_provider_client

    return _make_provider_client("deepseek")


def _print_summary(payload, artifact_path):
    summary = {
        "artifact": str(Path(artifact_path).resolve()),
        "model": payload["model"],
        "task_runs": payload["task_runs"],
        "variants": payload["variants"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main(argv=None):
    args = build_parser().parse_args(argv)
    model = "fake" if args.all else args.model
    default_path = DEFAULT_DEEPSEEK_ARTIFACT if model == "deepseek" else DEFAULT_FAKE_ARTIFACT
    artifact_path = Path(args.output) if args.output else default_path
    if args.show_latest:
        if not artifact_path.exists():
            raise SystemExit(f"artifact not found: {artifact_path}")
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        _print_summary(payload, artifact_path)
        return 0

    repetitions = args.repetitions if args.repetitions is not None else (2 if model == "deepseek" else 1)
    payload = run_recovery_experiment(
        artifact_path=artifact_path,
        repetitions=repetitions,
        model_client_factory=_deepseek_factory if model == "deepseek" else None,
        model_label=model,
        tasks=args.task,
        modes=args.mode,
    )
    _print_summary(payload, artifact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
