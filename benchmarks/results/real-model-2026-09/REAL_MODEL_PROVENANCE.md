# 2026-09 Provider Eval Provenance

## Code state

- Date: 2026-09-02 (Asia/Shanghai)
- Commit at experiment preparation: `5a052a85ff17c59e21dc9eb305d3703dceb8fa3d`
- Branch: `master`
- Working tree: dirty; this execution intentionally preserved pre-existing user changes.

## Offline step-budget experiment

- Command: `python scripts/run_step_budget_experiment.py --mode fake --budgets 3,6,9 --output-json benchmarks/results/real-model-2026-09/step-budget-sensitivity.json`
- Benchmark: `benchmarks/coding_tasks.json`
- Tasks: all 12 fixed tasks
- Repetitions: 1
- Protocol: `text`
- Model: deterministic `FakeModelClient`
- Total runs: 36
- Environment secrets: none required

This experiment verifies budget enforcement, finalization, artifact creation, and verifier behavior. It does not measure real-model intelligence and does not prove that six steps is globally optimal.

## Real DeepSeek experiment

- Status: not run
- Intended provider: `deepseek`
- Intended environment variable names: `PAGE_DEEPSEEK_API_KEY`, optionally `PAGE_DEEPSEEK_API_BASE` and `PAGE_DEEPSEEK_MODEL`
- Intended first step: one read-only smoke task
- Recommended hard cap after smoke: at most 12 total runs

The run is intentionally blocked at the manual cost gate until the user explicitly confirms the model, protocol, and maximum number of paid calls. No secret value is recorded in this directory.

## Known limits

- FakeModel rows are deterministic contract tests, not real Agent success rates.
- A future real-model sample of 3–12 runs will only show a local trend, not statistical significance.
- OpenAI-compatible gateways may not implement every Responses API field; use `tool_protocol=text` when native tool calls are unsupported.
