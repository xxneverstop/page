# Page — Minimal Agent Harness 从零重建计划

> 状态：待实施（工程计划，不代表已完成）  
> 日期：2026-11-25  
> 项目：[`xxneverstop/page`](https://github.com/xxneverstop/page)  
> 旧版参考基线：`926ea0e2c3fe4a81fb31cf15a5bd6add7f84233d`（实施前再次确认 HEAD）  
> 核心参考：[`earendil-works/pi`](https://github.com/earendil-works/pi)（开始实施时记录固定 commit，避免直接依赖移动的 `main`）  
> 目标：**从零构建一个简单、稳定、可靠、可读的 Python Coding Agent Harness；以此作为后续 Roadmap 的唯一开发基线。**

## 0. 决策与边界

### 0.1 采用的方案

- **重建代码核心，不是对旧 Runtime 进行重构或迁移。** 新的 Agent Loop、消息模型、工具编排、上下文入口与会话接口均由零实现；不复制旧的 `Page` / `AgentLoop` / `ActionJournal` 控制流。
- **在原 Page 仓库内完成重建**，保留 Git 历史、项目名称和已有有价值的资产。旧版冻结在 tag/branch，避免新旧代码同时充当运行真相。
- **参考 Pi 的设计而非整体移植 Pi。** 重点参考其结构化消息、Agent Loop、原生工具调用、事件生命周期、Context 转换、Skill 按需加载；不复制 Pi 的完整 TypeScript 技术栈、TUI、扩展系统及复杂持久化设施。
- **最小是核心架构原则，不是最终功能上限。** 先建立可信的最小 Coding Agent，再实现 Context Engineering、Skill Engineering、最小恢复和 Evaluation，构成有证据的简历项目。
- **优先复用原 Viewer 和评测资产**，但复用前要验证接口与统计口径，不能为了兼容旧实现把复杂性重新塞入核心。

### 0.2 不可妥协的工程原则

1. **简单、稳定、可靠 > 抽象完备 > 功能数量。** 不为“未来可能用到”引入 Factory、通用 Plugin Manager、任务调度服务或多层接口。
2. **主链路一眼可读。** Agent Loop 只协调“构建上下文 → 调用模型 → 处理回答/工具 → 回填结果 → 继续或结束”。审批、记录、持久化、恢复、观测通过明确的组件边界完成。
3. **数据结构优先于设计模式。** 明确定义 `Message`、`ToolCall`、`ToolResult`、`ModelTurn`、`Session`、`AgentEvent` 等少量结构；明确谁是数据事实源。
4. **注释说明为什么，不复述做什么。** 关键函数有简短 docstring，复杂分支注释约束、失败条件和设计理由；避免大段流水账注释。
5. **每阶段必须可运行、可测试、可观察。** 不先堆积一批模块再统一联调；不以“模型说 fixed”判定代码任务成功。
6. **新代码不背旧实现的兼容债。** 需要兼容的只包括明确列出的 CLI/公开入口、历史工件读取和可复用测试数据；旧版内部类、私有方法及其错误行为不要求兼容。
7. **不改变旧实验原件。** 历史 Benchmark、实验结果及 Provenance 原样保留；新结果使用新目录和新版本标签，不混算。

### 0.3 首轮范围

| 首轮必须有（MVP） | 后续逐步实现 | 暂不实施 |
| --- | --- | --- |
| 单 Agent、多轮决策 | Context 压缩和文件版本感知 | 多 Agent / Sub-agent / Delegate |
| 一个稳定的原生 Tool Calling Provider | Skill 按需注入 | 通用 MCP / Plugin 平台 |
| 读、查、改、测代码的工具 | 最小 Checkpoint / Action Journal | 自动并行写入与复杂调度 |
| 串行执行同轮多个 Tool Call | 恢复与故障注入 | 数据库、消息队列、分布式任务系统 |
| 权限、路径约束、预算、超时 | 真实 Coding Eval / 消融实验 | 向量数据库、复杂长期记忆系统 |
| Session、统一事件、CLI、Viewer 接入 | 按证据优化 Prompt / Context / Skill | 完整 IDE / 高级 TUI / Web 编辑器 |

> 旧 Page 的复杂 Memory、Recovery 和实验逻辑可以作为“需求与失败案例参考”，**不属于 MVP 的实现前提**。先确保普通 Coding 任务能连续完成，再按后续阶段重新引入相应能力。

### 0.4 开发目录隔离：Git Worktree（M0 强制实施）

**开发位置：沿用原 GitHub 仓库，但使用独立工作目录与独立分支。** 不在原目录直接改动新核心，不在仓库内新增长期并存的 `minimal/` 第二套实现，也不新建另一个 GitHub 仓库。

```text
projects/
├── page/                  # 原工作目录；保留 master/旧版供查阅、对照和回退
└── page-minimal/          # 新 Git Worktree；rebuild/minimal-agent 分支中实施 M0–M7
```

在原 `page/` 目录执行以下命令；如目标分支或目录已存在，先检查并按实际状态调整，**不得强制覆盖**：

```powershell
git status                        # 先检查并妥善保存未提交改动
git branch legacy/page-pre-minimal-rebuild HEAD  # 旧版冻结引用；已有则不重复创建
git worktree add -b rebuild/minimal-agent ../page-minimal HEAD
cd ../page-minimal
git status
```

约束与验收：

- `page/` 与 `page-minimal/` 共享 Git 历史，但工作区和分支相互隔离；不要用文件复制代替 Worktree。
- Worktree 创建时包含原仓库全部旧代码，这是正常现象；在**新分支**分阶段替换核心，不要先删除 Viewer、Benchmark、历史测试数据和 Provenance。
- 新版 `core/` Python 包最终只保留**一套**正式运行入口；旧 Runtime 不可被新入口间接导入。历史行为通过旧分支查阅，必要的工件由兼容适配器读取。
- M0 阶段记录原 HEAD、冻结分支、重建分支及两处 Worktree 路径；保留 `git worktree list` 输出作为操作证据。
- M7 验收全部通过且确认无未提交改动后，**人工审查**新旧文件及删除清单，再将 `rebuild/minimal-agent` 合并回原仓库主分支。不要在计划启动时自动合并，更不能以覆盖原目录的方式交付。
- 合并后的 `page-minimal/` 可作为后续开发目录继续使用；如需移除 Worktree，使用 `git worktree remove`，不要直接删除含未保存工作的目录。

## 1. 目标架构

```text
User / CLI
    │
    ▼
Agent.run(task, session)
    │
    ├── Context.build(session) ────────────────┐
    │                                         ▼
    ├── Provider.complete(messages, tools) → ModelTurn
    │                                         │
    ├── Session.append(assistant message) ◄────┘
    │
    ├── No tool calls → Finish (answer / stop reason)
    │
    └── Tool calls → ToolExecutor (sequential)
                       ├─ validate / authorize
                       ├─ execute read / edit / write / bash
                       └─ ToolResult → Session.append → next turn

EventSink ◄── Agent / Provider / ToolExecutor
    ├── CLI progress
    ├── Trace / RunStore ────> Viewer (read-only)
    └── Test assertions

Later: Context policies / Skills / Checkpoint & Resume / Evaluator
```

**核心不变量：** Session 中的结构化对话与工具结果是可回放事实源；每次请求发送给 Provider 的上下文由 Session 投影得到。Trace 是观测证据，不是 Agent 控制真相；Viewer 不参与决策。

### 1.1 建议目录（以实际复杂度为准）

```text
page/                               # 仓库根
├── AGENTS.md                       # 面向 Codex/通用编码 Agent 的协作规则
├── CLAUDE.md                       # Claude Code 入口；遵循 AGENTS.md，少量专属说明
├── README.md                       # 定位、快速启动、能力边界
├── pyproject.toml
├── uv.lock                         # 锁定依赖；根据实际环境生成
├── .env.example
├── core/                           # 新版 Python 包；不再使用嵌套的 page/ 包
│   ├── __init__.py                 # 少量稳定公开接口
│   ├── __main__.py
│   ├── cli.py                      # CLI 命令和交互；不包含业务控制流
│   ├── agent.py                    # Agent 组装 + 极简主循环
│   ├── models.py                   # Message / ModelTurn / ToolCall / Result / Event
│   ├── provider.py                 # 一个原生协议 Adapter；以后按需拆 providers/
│   ├── tools.py                    # 工具接口、注册、校验、执行；变大再拆 tools/
│   ├── context.py                  # Context.build；后续按需拆 context/
│   ├── session.py                  # 会话持久化（首先用本地 JSON/JSONL）
│   ├── events.py                   # EventSink + TraceWriter + Viewer 适配
│   ├── security.py                 # 工作区路径、审批和 Shell 限制
│   ├── skills.py                   # S3 时建立
│   └── recovery.py                 # S4 时建立；不提前建空模块
├── viewer/                         # 保留原 Viewer，优先只适配后端数据
├── benchmarks/                     # 旧数据原样存档，新任务与结果明确分开
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fault_injection/            # S4 开始
│   └── fixtures/
├── docs/
│   ├── README.md                   # 文档索引
│   ├── architecture.md             # 一页架构图 + 主链路解释
│   ├── contracts.md                # 消息、工具、事件、运行工件约定
│   ├── development.md              # 安装、运行、测试、调试
│   ├── viewer.md                   # Viewer 使用与兼容约束
│   ├── decisions/                  # 仅记录重大决策，避免文档膨胀
│   ├── plans/
│   │   └── minimal-agent-rebuild.md  # 本计划
│   └── roadmap/
│       ├── roadmap-v2.md           # 旧计划：留存，不再作为执行基准
│       └── roadmap-v3.md           # 新基线下的阶段路线图
└── scripts/                         # 只保留确有用途的运行/评测脚本
```

**目录与运行入口约定：** 仓库名称仍为 `page`，但新版源码包为根目录下的 `core/`，即 `page/core/agent.py`，**不再采用 `page/page/agent.py`**。因此在新工作区中：

- `pyproject.toml` 的包发现/打包配置应包含 `core`，并排除旧 `page` Python 包；根据选用的构建后端写实际配置，避免出现源码可运行而打包安装失败。
- 命令行品牌名称仍为 `page`，其 console script 指向 `core.cli:main`；模块启动命令改为 `python -m core`，并在 `core/__main__.py` 中统一调用 `core.cli:main`。不要继续把 `python -m page` 写作新版入口。
- 内部导入使用 `core.*` 或明确的相对导入；旧代码的 `from page ...` 不允许悄悄混入新运行链路。测试、文档、CLI 入口和 `AGENTS.md` / `CLAUDE.md` 必须同步更新。
- `core` 名称较通用，存在与其他环境包重名的潜在风险；在独立项目虚拟环境及可重现的打包测试中验证导入解析。若出现实际冲突，应单独记录架构决策，不擅自恢复双层 `page/page`。

**目录不是强制文件数目标。** 早期保持扁平；当某文件出现多种独立职责或阅读难度明显增加时才按职责拆包。现有旧模块不在新入口里被隐式导入。

### 1.2 核心接口（先定契约，再写实现）

```python
# 结构示意，具体签名在 M1 写 tests 后确定。
class Provider:
    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn: ...

class Context:
    def build(self, session: Session) -> list[Message]: ...

class ToolExecutor:
    def execute(self, call: ToolCall, *, context: ToolContext) -> ToolResult: ...

class EventSink:
    def emit(self, event: AgentEvent) -> None: ...

class Agent:
    def run(self, task: str, session: Session | None = None) -> AgentResult: ...
```

- 原生 Tool Call 保留 Provider 的 `call_id`，每一个请求必须对应一个结果（成功、失败或拒绝）；**同轮多调用先顺序执行**，不要求并行。
- `ModelTurn` 显式区分 `text / tool_calls / usage / finish_reason / error`；模型调用错误不是普通任务完成。
- `Session` 记录 `user → assistant(tool_calls) → tool_result → assistant`，提供最小 JSON/JSONL 持久化与原子写入；不得只存拼接后的大字符串 Prompt。
- `ToolResult` 明确成功/失败、退出码、被截断的输出、耗时和错误类型；**测试命令 exit=1 是模型可用于继续修复的观察结果**，不是自动触发任务拒绝。
- 终止状态区分：`completed / failed / stopped / interrupted`，并记录原因。`completed` 只代表 Agent 正常结束，**不等于独立 Verifier 验收通过**。
- Event 需带 `run_id`、`turn_id`、`model_request_id`、`tool_call_id` 等必要关联键；确保一个模型调用到多个工具结果可追溯。

### 1.3 期望的 Agent Loop 可读性

```python
# 概念伪代码：边界情况仍需由组件和少量明确分支处理。
def run(self, task, session):
    session.add_user(task)
    self.events.emit("agent_start")

    while self.budget.allow_turn():
        messages = self.context.build(session)
        turn = self.provider.complete(messages, self.tools.specs())
        session.add_assistant(turn)

        if turn.is_error:
            return self.stop("model_error")
        if not turn.tool_calls:
            return self.finish(turn.text)

        for call in turn.tool_calls:
            result = self.tools.execute(call, context=self.tool_context)
            session.add_tool_result(call.call_id, result)

        self.events.emit("turn_end")

    return self.stop("budget_exhausted")
```

**验收要求不是代码必须只有十几行，而是读者能在一个文件中看到完整主流程，复杂行为可循明确调用关系深入。** 不允许把恢复对账放进 `Context.build()`，也不允许让 Viewer 的字段要求决定 Agent 控制流。

## 2. 分阶段执行计划

### M0 — 冻结旧版、建立新基线与协作规范（必须先做）

**任务**

- [ ] 检查 `git status`、实际 HEAD、未提交改动；保留所有用户工作，禁止直接清理/覆盖。
- [ ] 按 **0.4 Git Worktree 方案**冻结旧版、建立 `rebuild/minimal-agent` 分支和仓库外并列的 `page-minimal/` 工作目录；记录 `git worktree list`。
- [ ] 归档旧版功能清单：CLI、Providers、7 类工具、Context/Memory、Session、Recovery、Trace、Viewer、Eval。分类为“新核心必须有 / Roadmap 后续引入 / 仅保留历史参考”。
- [ ] 保留 `viewer/`、`benchmarks/results/` 与必要的实验 Provenance；记录历史文件哈希、运行命令及测试基线。
- [ ] 写根目录 `AGENTS.md`、`CLAUDE.md`、`docs/README.md`、`docs/architecture.md`、`docs/contracts.md`、`docs/development.md`、`docs/roadmap/roadmap-v3.md`；更新 README，明确旧版不是新实现。
- [ ] 确认新目录采用 `core/` Python 包（仓库根目录为 `page/`），同步更新 `pyproject.toml` 的打包发现、`page = "core.cli:main"` 命令行入口、`python -m core` 模块入口、所有新代码导入及对应测试；旧 `page/` 包不得参与新版运行。
- [ ] 配置 Python/uv、依赖锁、pytest 和最简单的 lint；先不要引入生产部署、数据库或服务编排。
- [ ] 为新核心建立独立测试入口，旧测试不必无条件通过，但被替换、删除或改写的旧用例必须解释其原因。

**通过标准**：任意人能够恢复旧版、在干净环境启动新项目骨架；从项目虚拟环境分别验证 `page --help`、`python -m core --help` 和 `import core`；安装后的 CLI 不依赖旧 `page` 包；能找到开发约定和完整阶段计划，旧数据没有被覆盖。

### M1 — 从零实现 Minimal Agent Core（最优先）

**任务**

- [ ] 建立 `models.py`：结构化 Message、ModelTurn、ToolCall、ToolResult、AgentResult、AgentEvent。
- [ ] 实现一个 Provider Adapter：选一个**实际可用的、支持原生 Tool Calling** 的模型协议，固定测试配置。其他 Provider 留到稳定后再加。
- [ ] 实现 `agent.py`：模型请求、工具调用结果回填、下一轮调用、正常完成、明确停止。
- [ ] 实现最小 `Context.build()`：System + 当前任务 + 结构化历史；此阶段不做复杂记忆压缩。
- [ ] 实现 `Session`：保存每一轮消息及工具结果；模型输入从 Session 投影；保证工具调用/结果正确配对。
- [ ] 实现 `ToolExecutor`：先用确定性的 FakeProvider + FakeTool 测循环；支持同一轮多个 Tool Call 的串行执行。
- [ ] 实现调用次数、工具次数、运行时间、输出上限等基础预算；避免错误响应无限重试。
- [ ] 定义基础事件：`agent_start`、`turn_start`、`model_request`、`model_response`、`tool_start`、`tool_end`、`turn_end`、`agent_end`；名称/版本可调整，但含义固定。
- [ ] 为关键控制流编写注释和小型单测；对不完整工具参数、模型错误、错误停止原因设定明确行为。

**通过标准**：可用 FakeProvider 稳定跑通至少“直接回答”和“多轮工具调用”两种任务；原生协议能在真实模型下完成读文件任务；每个 Tool Call 有唯一配对结果；核心 Loop 能被独立讲解。

### M2 — Coding Agent 工具、权限和正常修复闭环

**任务**

- [ ] 建立 `read_file`、`search`、`write_file`、`edit_file`、`run_shell` 的最小实现；工具名以统一契约为准，旧脚本按需适配。
- [ ] 目录约束：路径正规化、禁止工作区逃逸、处理符号链接、限制输出体积；写入与 Shell 有明确审批/允许策略。
- [ ] Shell 限制工作目录、环境变量、超时、退出码和输出截断；不把任意 Shell 视为可以安全自动重放。
- [ ] 同轮多工具调用默认串行；即使某个工具失败，也保证结果被回填或按协议明确停止，不产生孤立 call_id。
- [ ] **确保测试失败 → 模型看到错误 → 修改文件 → 重跑测试 → 继续任务**。退出码非零通常属于工具结果，不应触发全局拒绝。
- [ ] 禁止通过“同一工具名 + 参数”粗暴阻止所有重复调用；根据当前任务状态和文件变化判断是否无进展；首版可只依赖最大步数/预算。
- [ ] 建立 2–3 个可复现的真实 Coding 小任务与独立测试验证（而不是单看最终回答）。

**通过标准**：离线测试覆盖多调用配对、审批拒绝、路径越界、超时、工具失败；真实模型至少能在受控仓库完成一次“失败—修复—再测”闭环。

### M3 — 统一观测、Viewer 复用与 CLI 体验

**优先方案：复用原 `viewer/`。** 原 Viewer 已读取 `.page/runs/<run_id>/` 下的 `trace.jsonl`、`task_state.json`、`report.json`，提供本地只读 Inspection API。新 Core 不直接依赖 Viewer；采用 Adapter 输出其可消费的运行工件。

**任务**

- [ ] 定义 `AgentEvent` 内部统一格式，所有运行事件通过 `EventSink` 发布；不要在 Agent Loop 中散布直接拼接 Trace JSON 的逻辑。
- [ ] `TraceWriter` 保存新格式；`ViewerTraceAdapter` 映射到现有 `page-trace-v2` 或经过明确版本化的兼容格式；**优先保留 `viewer/server.py`、`viewer/trace_model.py`、前端**。
- [ ] 将新运行结果输出到 `.page/runs/<run_id>/{trace.jsonl,task_state.json,report.json}`，遵守旧 Viewer 的关联 ID 与脱敏口径。
- [ ] 对照旧 Viewer 的核心视图验收：运行列表、Agent Loop、模型输入/输出、工具结果、Context、Trace。没有 Recovery/Skill/Eval 证据时明确展示 `unknown` 或 `not available`，不得伪造成功事件。
- [ ] 复用历史工件作为 Viewer 回归测试样本，保证旧版运行记录仍可阅读；新旧记录都可打开。必要时只修改 `trace_model.py` 的兼容层，不做 Web UI 大改。
- [ ] CLI 简洁呈现当前模型、轮次、工具动作、审批、失败信息和最终状态；实时进度由事件驱动，不与 Agent 内部逻辑耦合。
- [ ] 仅在当前 Viewer 无法表达关键新证据时增加字段/视图；保留“原始证据 vs 推导值”区分。

**通过标准**：同一真实运行可从 CLI 看到进度、在 Viewer 复盘工具调用及其结果；旧 Trace 仍可读；基本测试确认统计不把 Agent Final 当作 Verifier Pass。

**Viewer 备选方案（仅触发条件满足才启用）**：如果经 Spike 证明兼容成本明显高于实现一层小型只读新 Viewer，才考虑另起 Viewer；需记录对比（修改量、回归范围、历史数据兼容、维护成本），不能因为偏好新技术栈而重写。

### M4 — Context Engineering（核心技术亮点 1）

- [ ] 在 M1 的 `Context.build()` 上扩展，而非替换 Agent Loop。
- [ ] 建立可解释的上下文预算：系统规则、用户目标、关键最近工具结果优先；过长输出有界截断，保留错误码和关键定位信息。
- [ ] 增加简单压缩/摘要策略，并记录实际发送的模型输入；区分估算 Token 与 Provider 实际用量。
- [ ] 文件来源版本感知：复用读文件记录前检查版本；修改后失效，不让旧源码继续影响决策。
- [ ] 历史 Session 原始记录与请求时 Context 投影分离；压缩不破坏工具调用与结果配对。
- [ ] 通过 Context On/Off 对照测任务完成率、工具次数、Token、失败类型；无改善时诚实报告。

**通过标准**：真实请求证据证明内容确实被裁剪/保留/更新，且不会丢掉必要的工具结果；有固定任务对照与可复核数据。

### M5 — Skill Engineering（核心技术亮点 2）

- [ ] 使用简单目录 `skills/<name>/SKILL.md`；最初只实现名称、描述、路径、正文及来源校验。
- [ ] 启动时只暴露 Skill 元信息，**任务需要时才读取正文**；至少支持显式选择，不急于做自动推荐。
- [ ] 将 Skill 注入交给 Context 层；计入上下文预算，记录选择依据、来源 Hash、注入与裁剪情况。
- [ ] 首个 Skill 选 Coding/Bugfix 场景，以可执行流程与真实任务验证；测试适用与不适用任务。
- [ ] 保持 Skill 为“指令与资源”，不能绕过工具权限和执行审批。

**通过标准**：能独立演示有/无 Skill 的同条件对照；Viewer 可查看实际 Skill 注入证据与成本。

### M6 — Minimal Recovery（可靠性补充亮点，不反客为主）

- [ ] 基于结构化 Session 引入最小 `Checkpoint`，仅恢复有价值的任务状态与预算。
- [ ] 对具有副作用的动作引入最小 Action Journal：**每次逻辑 Tool Call 有独立身份**（不能仅由工具名与参数 Hash 决定）。
- [ ] 恢复对账只在显式 Resume/重启边界运行，普通 Context 构建和普通下一轮执行不得触发全局恢复拒绝。
- [ ] 区分可证实已应用、可安全重试、未知副作用三类；不对任意 Shell 自动承诺“恰好一次”。
- [ ] 未知副作用仅阻止受影响的恢复动作或请求人工确认；不得把一次测试失败当作未知副作用而阻塞后续正常改码。
- [ ] 通过故障注入覆盖“执行前/执行后未记录/结果已记录/重启后”的最小场景，保留复盘证据。

**通过标准**：新进程可恢复至少一个真实 Coding 任务，文件不被危险重复修改；不触发旧 Page 已暴露的“成功 Shell/失败测试后误拒绝”问题。

### M7 — Evaluation、优化与简历交付（核心技术亮点 3）

- [ ] 从旧 Page 的 Benchmark 中**选择性复用任务和独立 Verifier**；检查 fixture、环境假设和数据污染，不直接复用旧“通过率”结论。
- [ ] 建立 6–10 个可独立验收的 Coding 任务，覆盖读代码、修改、测试反馈、Context、Skill 和 Recovery；正式任务运行前冻结题目、版本、模型及预算。
- [ ] 评测报告区分 Agent 完成、独立 Verifier 通过、工具调用失败、权限拒绝、超时、恢复拒绝；保留原始分子/分母。
- [ ] 至少完成：Context 策略 A/B、Skill On/Off、一个失败案例“定位 → 最小修复 → 回归 → 同条件复测”。
- [ ] 使用 Viewer 复盘代表性案例，生成含真实 Trace、任务 diff、测试结论、Token/调用次数/费用边界的演示材料。
- [ ] 写出简历 STAR：① 从零构建可解释的 Coding Agent Core；② Context/Skill 的实验性优化；③ 真实 Coding Eval 和可靠恢复证据。
- [ ] 完善 README 的架构图、启动、限制、指标口径、复现实验和面试问题。
- [ ] 确认新旧核心替换范围、保留资产与删除清单；检查分支及工作树状态，完成全套验收后再人工审查并合并 `rebuild/minimal-agent` 到主分支。

**通过标准**：别人能够克隆仓库、按文档运行固定任务、在 Viewer 复盘，并复查报告对应的代码变更及独立验收结果。

## 3. 验收与质量门禁

### 3.1 必须长期保持的运行不变量

- [ ] 所有原生 Tool Call 都有稳定 `call_id` 和对应的 `ToolResult`；不丢调用、不伪造结果。
- [ ] Prompt/上下文管理不会改变工作区，也不会隐式执行 Resume 对账。
- [ ] 工具失败回填模型；只有明确安全策略或全局预算才阻止后续正常尝试。
- [ ] 工具校验和审批均发生在副作用之前；拒绝有清晰的原因码。
- [ ] `completed` 不代表代码已通过测试；Evaluator 使用独立 Verifier。
- [ ] Session/Trace 的来源、版本及关联可追踪；详细数据应脱敏，默认不包含凭据。
- [ ] Viewer 只读，不影响 Agent 决策；历史工件能够兼容查看。

### 3.2 每个阶段交付格式

每个阶段都在 `docs/plans/` 下保留简短实施记录，至少包括：

1. **What changed**：新增/修改哪些文件与接口；是否删除旧逻辑。
2. **Why**：设计选择以及为什么不采用更复杂方案。
3. **Evidence**：自动测试命令和结果、一次真实或 FakeProvider Trace、必要的 Viewer 截图/链接。
4. **Limits**：尚未解决的问题、非目标、已知风险。
5. **Next**：下一阶段依赖和明确入口。

无测试证据不标记完成；未经验证的“理论支持”不写成“已经支持”。

## 4. AGENTS.md 与 CLAUDE.md 的要求

### 4.1 `AGENTS.md`（规范唯一事实源）

必须包含这些规则，文字宜短，不要把整份 Roadmap 复制进去：

- 项目定位：Python Minimal Coding Agent Harness，设计原则：**简单、稳定、可靠、易读**。
- 执行顺序：读 `docs/README.md`、`docs/architecture.md`、`docs/roadmap/roadmap-v3.md` 和当前阶段计划；只实现当前阶段范围。
- 代码规则：遵循单向模块依赖，核心循环不得直接处理 UI、实验报告或恢复对账；优先标准库和少量成熟依赖。
- 注释规则：公共入口、关键控制流、边界条件写简短中文注释/docstring；不要重复代码表面含义。
- 变更规则：先读相关测试与接口；不引入抽象预留；不随意改历史 Benchmark、旧 Trace 或用户文件。
- 验证规则：每次修改执行相关单测，阶段完成执行完整离线回归、CLI 冒烟与一项运行证据；输出实际命令和结果。
- 安全规则：不泄露密钥；Shell/文件写入经过约束与审批；禁止把失败的模型回答当作代码验证成功。
- 维护规则：新增功能同步更新对应 docs、roadmap 状态和必要的 Viewer 字段/测试。

### 4.2 `CLAUDE.md`（轻量入口）

- 第一条明确：`Read and follow AGENTS.md as the canonical engineering rules.`
- 列出项目的 3–5 个关键入口：`core/agent.py`、`core/models.py`、`core/tools.py`、`docs/architecture.md`、当前阶段计划。
- 只写 Claude Code 特有的协作注意事项；**不要复制整份 AGENTS.md**，以免规则漂移。

## 5. Roadmap v3（新项目阶段表）

`docs/roadmap/roadmap-v3.md` 应以此表为执行入口，M0–M3 属于“建立可靠基础”，M4–M7 属于“形成简历亮点”。

| 阶段 | 输出 | 优先级 | 是否阻塞后续 |
| --- | --- | --- | --- |
| M0 旧版冻结与规范 | 分支/基线、AGENTS、CLAUDE、Docs、测试环境 | P0 | 是 |
| M1 Minimal Agent Core | 原生工具调用、简单 Loop、Session、事件 | P0 | 是 |
| M2 Coding 闭环 | 工具、安全、测试失败后修复 | P0 | 是 |
| M3 Viewer/CLI | 统一 Trace、旧 Viewer 复用、交互和复盘 | P0 | 是（作为观测基线） |
| M4 Context Engineering | 上下文预算、压缩、Freshness、对照 | P0 | 否，可按需与 M5 穿插 |
| M5 Skill Engineering | 按需加载、注入证据、对照 | P0 | 否，依赖 M4 的预算接口 |
| M6 Minimal Recovery | 安全恢复与故障注入 | P1 | 否，不阻塞 Context/Skill 实验 |
| M7 Evaluation & Delivery | 真实任务、Verifier、实验、简历 | P0 | 评测工件从 M2 持续积累 |

> **关键路径：M0 → M1 → M2 → M3 → M4/M5 → M7。** M6 是重要但限界的可靠性专题，不让其延误 Agent 特有亮点。M2 就应开始积累独立验证的 Coding 任务；M7 不应第一次接触真实任务。

## 6. 执行策略与停止条件

1. **先只做 M0；不要让 Codex 一次性实施所有阶段。** 当前文档是总体计划，每阶段再生成小型任务清单，逐步提交、逐步验收。
2. **旧版仅供参考，不是重建依赖。** 必须明确哪些旧代码是“查阅行为/测试案例”，哪些历史资产经过验证可直接复用；重建核心禁止 import 旧 Runtime。
3. **先验证再抽象。** 同一个组件出现实际第二种用例后，再判断是否需要接口层、插件化或拆包。
4. **遇到基础问题时优先修正边界，不用补丁堆补丁。** 特别关注 Session 真相、工具结果配对、恢复触发时机和 Trace 契约。
5. **如果 Viewer 适配将迫使 Agent Core 按旧 Viewer 的内部结构设计，应保留新 Core 的干净模型，改写独立适配层。**
6. **阶段回退条件：** 主流程变得难读、原生调用结果不再配对、普通失败不能继续修复、安全边界退化、Viewer 关键数据失真、回归不通过——出现其一就暂停扩展，先修复当前阶段。

## 7. 最终完成定义（不是“代码写完”）

Page 最终应满足：

- 一个初学 Agent 开发的人，顺着 `agent.py` 和 3–5 个配套模块，能理解完整 Coding Agent 的运行链路。
- 一次真实任务能够读代码、修改、执行测试、依据失败反馈再次修复，最终由独立测试确认结果。
- Context 与 Skill 是可替换、可对照、能量化收益和边界的 Agent 核心技术点。
- 恢复机制在限定场景下可靠，未知 Shell 副作用不被误判为安全。
- Viewer 能从事件重建执行与决策证据，旧运行工件不被破坏。
- 仓库有清晰的 `AGENTS.md`、`CLAUDE.md`、`docs/`、`roadmap-v3.md`、快速启动、测试与复现实验指引。
- 简历叙事以 **“自研 Minimal Coding Agent Core + Context/Skill 优化 + 真实任务评测”** 为主，而不是以“大量后端状态机/持久化设计”为主。

## 8. 参考源码（只借鉴必要思想）

- [Pi Agent Loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)：循环、模型回合、工具执行编排。
- [Pi Agent Core](https://github.com/earendil-works/pi/tree/main/packages/agent)：状态、事件、Provider 请求前后钩子。
- [Pi Agent Types](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts)：结构化消息、工具和事件数据模型。
- [Pi Coding Agent Tools](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/src/core/tools)：工具与工作区交互。
- [Pi Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)：描述发现、正文按需加载。
- [Page 旧 Viewer 设计](https://github.com/xxneverstop/page/blob/926ea0e2c3fe4a81fb31cf15a5bd6add7f84233d/viewer/README.md)：`page-trace-v2` / `page-inspection-v2` 和只读复盘。
- [Page 旧 Roadmap v2](https://github.com/xxneverstop/page/blob/926ea0e2c3fe4a81fb31cf15a5bd6add7f84233d/docs/roadmap/roadmap-v2.md)：保留任务需求与实验思路，不继承已知设计问题。

> 若直接复制 Pi 的代码片段，应核实许可证、保留必要署名/许可证说明；优先独立实现其设计思想。
