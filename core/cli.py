"""Small command-line entry point for the rebuilt core."""

from __future__ import annotations

import argparse
import os
from uuid import uuid4
from pathlib import Path

from .agent import Agent
from .context import Context
from .models import ModelTurn
from .observability import RunArtifacts, TraceWriter
from .provider import FakeProvider, OpenAICompatibleProvider
from .security import SecurityPolicy
from .skills import SkillStore, render_skill_context
from .tools import ToolExecutor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="page",
        description="Minimal Python coding agent harness",
    )
    parser.add_argument("task", nargs="?", help="one coding task; omit to show usage")
    parser.add_argument("--workspace", "--cwd", default=".", type=Path, help="workspace root")
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    parser.add_argument("--model", default=os.environ.get("PAGE_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("PAGE_API_BASE", ""))
    parser.add_argument("--api-key", default=os.environ.get("PAGE_API_KEY", ""))
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--allow-write", action="store_true", help="allow file writes")
    parser.add_argument("--allow-shell", action="store_true", help="allow shell commands")
    parser.add_argument("--trace-dir", type=Path, default=Path(".page/runs"))
    parser.add_argument("--skill", action="append", default=[], help="explicit skill name (metadata is loaded on demand)")
    return parser


def build_agent(args: argparse.Namespace):
    workspace = args.workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    policy = SecurityPolicy(workspace, allow_write=args.allow_write, allow_shell=args.allow_shell)
    tools = ToolExecutor.for_workspace(workspace, policy=policy)
    if args.provider == "openai":
        if not args.base_url or not args.model:
            raise ValueError("--provider openai requires --base-url and --model")
        provider = OpenAICompatibleProvider(args.base_url, args.api_key, args.model)
    else:
        provider = FakeProvider([ModelTurn(text="FakeProvider completed the requested turn.")])
    context = Context(system_prompt="You are a careful coding agent. Inspect before editing and report test results.")
    if args.skill:
        selected = SkillStore(workspace / "skills").select(args.skill)
        context.skill_context = render_skill_context(selected)
    run_id = f"run_{uuid4().hex}"
    artifacts = RunArtifacts.create(args.trace_dir, run_id)
    trace = TraceWriter(artifacts)
    return Agent(provider, context=context, tools=tools, events=trace, max_turns=args.max_turns), trace, artifacts


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.task:
        parser.print_help()
        return 0
    try:
        agent, trace, artifacts = build_agent(args)
        result = agent.run(args.task)
        trace.finish(
            status=result.status,
            stop_reason=result.stop_reason or "",
            session_id=result.session_id,
            turns=result.turns,
            tool_calls=result.tool_calls,
            answer=result.answer,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(result.answer)
    print(f"status={result.status} stop_reason={result.stop_reason} trace={artifacts.trace_path}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
