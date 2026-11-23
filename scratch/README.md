# 模块演示与学习草稿

这里保存可手动运行的教学脚本，不是主运行框架或自动化测试入口。

| 文件 | 用途 |
| --- | --- |
| `demo_context_layers.py` | 观察上下文分层与预算裁剪 |
| `demo_memory_layers.py` | 观察分层记忆和召回 |
| `demo_checkpoint_resume.py` | 观察 Checkpoint 与恢复状态 |
| `demo_tool_safety.py`、`demo_tool_governance.py` | 逐步观察工具校验、审批和执行元数据 |
| `demo_evaluation.py` | 观察固定评测与运行工件 |
| `echo_agent.py`、`tool_calling_agent.py`、`safe_write_agent.py` | 从最小控制循环学习文本协议、工具调用与写入审批 |
| `my-test-1.py` | 手动构造长历史，观察 ContextManager 预算 |

在项目根目录运行，例如：

```powershell
python scratch/demo_checkpoint_resume.py
python scratch/demo_context_layers.py
```

这些脚本使用确定性示例或 FakeModel，不代表真实模型效果。模块演示通常创建临时工作区；`safe_write_agent.py` 的独立示例会向 `scratch/` 写示例文件，运行前先阅读脚本。草稿中的说明可能落后于实现，以主包和测试为准。

正式命令位于 [`scripts/`](../scripts/)，自动化测试位于 [`tests/`](../tests/)，独立教学包位于 [`examples/mini-page/`](../examples/mini-page/README.md)。

术语：spec 是一份明确规则、结构、约束与能力的标准化描述。
