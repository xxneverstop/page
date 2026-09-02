# Page Recovery 实现与实验报告

> 更新于 2026-08-06

## 先说结论

Page 的主要亮点不是“功能多”，而是**任务中断后可以安全恢复**。

真正难的地方是：程序崩溃时，文件可能已经改完了，但系统还没来得及记录“动作成功”。如果恢复后直接重放旧对话，同一个修改可能再执行一次。

Page 的处理方式是：

1. 执行动作前，先写 Action Journal（动作日志）。
2. 动作完成后，记录文件修改前后的 Hash。Hash 可以理解为文件内容的“指纹”。
3. 恢复时先比较日志和当前文件，再决定下一步：
   - 已经完成：跳过，不重复执行；
   - 还没执行：安全重试；
   - 状态对不上：停止自动恢复，交给用户确认。
4. 状态核对完成后，模型才继续处理任务。

DeepSeek 小样本中，直接加载旧状态的 `blind_resume` 完成 4/6；先核对状态的 `guarded_resume` 完成 6/6，而且模型请求和工具步骤更少。

这个结果只说明该机制在当前 3 类合成故障中有效。样本很小，不能说成生产环境成功率。

## 1. 为什么只保存对话不够

一次文件修改大致会经过下面几步：

```text
决定修改
  → 记录动作开始
  → 真正修改文件
  → 记录动作成功
  → 保存 Checkpoint
  → 返回最终答案
```

进程可能在任何两步之间退出。最危险的情况是：**文件已经修改，但“成功”记录和 Checkpoint 还没保存。**

Page 支持 3 个故障注入点，用来稳定复现这类问题：

1. `before_tool_execution`：动作已经登记，但工具还没有运行。
2. `after_tool_execution_before_commit`：文件已经改变，但日志仍显示“执行中”。
3. `after_checkpoint_before_final`：动作和 Checkpoint 都完成了，但用户还没收到最终回答。

Checkpoint 是任务进度快照；Action Journal 记录具体动作有没有执行。两者用途不同，不能互相替代。

## 2. Page 怎么恢复

### Action Journal：先记账，再动文件

`page/action_journal.py` 会给每个动作生成稳定的 `action_id`。相同 Session、工具名和参数会得到相同 ID，恢复时就能识别“这是之前那个动作”。

动作状态如下：

```text
planned → started → succeeded
                  ↘ failed
                  ↘ reconciled
                  ↘ manual-review-required
```

- `planned`：准备执行。
- `started`：已经开始，但还不能确认是否完成。
- `succeeded`：已经成功。
- `reconciled`：恢复时根据文件状态确认，动作其实已经完成。
- `manual-review-required`：系统无法安全判断，需要用户处理。

Session 通过“先写临时文件，再原子替换”的方式保存，尽量避免留下半个 JSON 文件。

### 恢复时先对账，不让模型猜

对于文件动作，恢复器会比较当前文件 Hash：

| 当前文件状态 | 说明 | 处理方式 |
| --- | --- | --- |
| 等于预期的 after Hash | 动作已经落盘 | 标记为已对账，跳过重复动作 |
| 仍等于 before Hash | 动作没有改变文件 | 可以安全重试 |
| 两者都不等 | 文件被其他人或进程改过 | 停止自动恢复，转人工确认 |

另外还有几条安全规则：

- Action Journal 版本不兼容时，拒绝继续写文件。
- 中断的 `run_shell` 不会自动重放。Shell 可能发请求、改数据库或启动进程，单靠文件 Hash 无法证明副作用有没有发生。
- 恢复判断全部由确定性代码完成，模型不负责猜“刚才到底执行成功没有”。

### freshness-aware Context：旧信息不能继续用

`page/context_manager.py` 会检查上下文里的文件信息是否仍然有效。

文件摘要和 `read_file` 结果都会保存来源路径和内容 Hash。下一轮构建 Prompt 时，系统重新计算文件 Hash：

- Hash 没变：旧信息可以继续使用；
- Hash 变了：旧信息标记为 `stale_rejected`，不再发给模型。

`Current Request` 和 `Recovery Context` 是受保护内容，不参加普通裁剪。如果仅这两部分就超过总预算，系统会返回 `protected_context_overflow`，而不是悄悄删掉安全信息。

每个 Context Block 都会记录自己的处理结果：`keep`、`summarize`、`drop` 或 `stale_rejected`，并说明原因。

### 失败也要留下证据

每次运行都会尽量保存：

- `task_state.json`：任务状态和停止原因；
- `trace.jsonl`：逐个事件的执行轨迹；
- `report.json`：本次运行汇总；
- Checkpoint 和 Action Journal：恢复需要的状态。

模型报错、受保护上下文超预算、故障注入等失败，也会尽量写完这些文件。Provider 只记录响应内容类型，不保存 thinking-only 响应里的原始思考内容。

## 3. 实验怎么设计

实验包含 3 类任务：

| 任务 | 人为制造的问题 | 想验证什么 |
| --- | --- | --- |
| `write_after_commit_crash` | 文件已经写入，日志提交前崩溃 | 能否识别已完成写入，避免重复执行 |
| `patch_after_commit_crash` | Patch 已落盘，日志提交前崩溃 | 能否用 after Hash 对账后继续 |
| `stale_file_drift` | 读取文件后，文件被外部修改 | 能否拒绝旧读取结果，重新获取事实 |

每个任务都运行两种模式：

- `blind_resume`：不做恢复保护，直接加载旧 History 和 Checkpoint。这只是实验对照组。
- `guarded_resume`：先核对 Journal 和工作区，再构建带 Recovery Context 的 Prompt。这是实际推荐的恢复方式。

两组使用相同任务、模型配置、步骤上限和 verifier（验收程序），只改变恢复方式。

DeepSeek 的 12 次运行来自：

```text
3 个任务 × 2 种恢复模式 × 2 次重复 = 12 次
```

FakeModel 用来稳定覆盖状态机；DeepSeek 用来观察真实模型能否理解恢复后的安全上下文。

## 4. 实验结果

### FakeModel：验证机制是否按设计工作

实验文件：`artifacts/interview-recovery-fake-final.json`

| 指标 | blind | guarded |
| --- | ---: | ---: |
| verifier 通过 | 3/3 | 3/3 |
| Journal 中实际执行的文件写动作 | 3 | 2 |
| 被确定性跳过的重复动作 | 0 | 2 |
| 识别出的 stale 状态 | 0 | 1 |

两组最终都通过，不代表恢复保护没用。FakeModel 的输出是预设的，verifier 只检查最终文件。guarded 的价值在于：重复动作没有再次执行，旧状态被明确作废，而且 Trace 能解释每个决定。

### DeepSeek：观察真实模型的续跑效果

实验文件：`artifacts/interview-recovery-deepseek-final.json`

| 指标 | blind | guarded |
| --- | ---: | ---: |
| 任务成功 | 4/6（66.7%） | 6/6（100%） |
| 模型请求 | 25 | 22 |
| 工具步骤 | 22 | 16 |
| token usage | 10917 | 10489 |
| stale 信息失效次数 | 0 | 2 |

blind 的两次失败都发生在 `stale_file_drift`：模型反复读取文件，最后超过步骤上限。guarded 会先让旧读取失效，并明确告诉模型“本轮新的读取结果才是有效事实”，所以两次都完成了。

最终 DeepSeek 运行中，模型大多会先检查状态，没有主动重复写文件，因此 `skipped duplicate` 为 0。FakeModel 则能稳定证明重复文件动作会被跳过。两组实验回答的问题不同，不能合并成一个结论。

## 5. 测试和演示命令

快速测试：

```powershell
pytest -q -m "not slow"
```

最近一次结果：`120 passed, 1 skipped, 28 deselected`，约 52 秒。唯一的 skip 是 Windows 没有符号链接权限时的预期处理。

完整测试结果：`148 passed, 1 skipped`，耗时 7 分 56 秒。之后又修复了 3 处 `datetime.utcnow()` 弃用警告，相关 4 个慢速指标测试重新通过。

离线 Recovery 演示：

```powershell
python scripts\interview_demo.py --scenario recovery --model fake --repetitions 1 --output artifacts\interview-recovery-fake-demo.json
```

## 6. 面试时怎么讲

推荐回答：

> 长任务恢复最难的不是保存对话，而是确认外部动作是否真的发生过。我在文件工具执行前先写 Action Journal，执行后记录文件 Hash 和后置条件。恢复时，Runtime 先对账：已经完成就跳过，没有发生就重试，状态不确定就交给用户。模型只在安全状态已经确定后继续推理。Context Manager 还会拦住已经过期的文件摘要和读取结果，避免旧信息再次误导模型。

如果面试官问“是不是生产级”，直接回答：

> 目前完成的是 Windows 单机文件工具的恢复闭环，思路接近生产系统里的幂等、预写日志、状态对账和审计，但还没有多机共识、跨进程锁、数据库事务、容器级 Shell 隔离和大规模真实仓库评测。

## 7. 能力边界

- DeepSeek 只有 12 次成对运行，证据有限。
- 本地预算仍用“字符数 ÷ 4”估算 token；Provider 返回的 usage 只做事后统计。
- `write_file` 和 `patch_file` 可以用 Hash 对账；Shell、网络请求和第三方 API 不能直接套用相同保证。
- 当前没有 HTTP API、Worker、Redis、数据库、Docker、Web UI、完整 RAG 或多 Agent。
- 面试前不再增加功能。下一步是本人复跑、读源码、核对简历数字，并连续完成 3 次五分钟演示。
