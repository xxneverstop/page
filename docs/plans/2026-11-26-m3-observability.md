# M3 实施记录

- What changed：新增 `core/observability.py`、CLI Trace 输出，并扩展 Viewer 对新生命周期事件的兼容映射。
- Why：让 Core 不依赖 Viewer 内部格式，仍可复用历史只读界面。
- Evidence：FakeProvider 运行生成三份工件；`build_inspection` 返回 `page-inspection-v2`。
- Limits：新事件没有伪造旧版 Recovery/Evaluation 证据。
- Next：用真实运行补充模型请求和工具结果复盘。
