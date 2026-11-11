# 2026-09 Eval Summary

## Step-budget sensitivity (offline)

| Tool budget | Passed | Pass rate | Maximum observed tool steps | Stop reasons |
| --- | ---: | ---: | ---: | --- |
| 3 | 11 / 12 | 91.67% | 3 | 11 final answers, 1 step-limit stop |
| 6 | 12 / 12 | 100% | 4 | 12 final answers |
| 9 | 12 / 12 | 100% | 4 | 12 final answers |

The defensible conclusion is: six steps is sufficient for the current fixed benchmark and is a more conservative default than nine. Since six and nine produced the same result, this experiment does not show a benefit from increasing the default to nine. Because the model is deterministic FakeModel, it also cannot prove that six is optimal for real models or larger repositories.

Raw aggregate: `step-budget-sensitivity.json`. Per-run evidence is in `step-budget-3-details.json`, `step-budget-6-details.json`, and `step-budget-9-details.json`; each row links to a run directory, task state, report, verifier result, tool signature, stop reason, and protocol.

## Real provider result

DeepSeek was not called because the plan requires explicit approval before spending API quota. `deepseek-coding-benchmark.json` records this as `not_run` instead of presenting fabricated or FakeModel data as a real result.
