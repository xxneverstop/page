# Page 项目面试问题与回答（口语版）

> 更新于 2026-08-06  
> 适合岗位：AI 应用开发、Agent 工程、平台后端  
> 演示环境：Windows 11 本地 CLI

这份材料不是让你逐字背诵。先记住项目主线、关键数字和能力边界，再用自己的话回答。

## 一、先记住事实边界

面试时遵守 3 条规则：

1. 有代码、有测试或有实验工件，才说“已经实现”。
2. 只有想法、没有代码，要说“如果生产化，我会这样设计”。
3. 小样本结果只说明当前实验，不外推成线上效果。

### 可以直接说已经实现

- Python 标准库实现的本地 Coding Agent Runtime；
- DeepSeek、OpenAI-compatible、Anthropic-compatible、Ollama 4 条模型配置路径；
- `list_files`、`read_file`、`search`、`run_shell`、`write_file`、`patch_file`、`delegate` 7 类工具；
- one-shot CLI、交互式 REPL、Session、Checkpoint 和 Resume；
- 分层 Context 与 Working、Episodic、Durable Memory；
- 工具白名单、参数和路径校验、重复调用阻断、审批、快照和 Secret 脱敏；
- `task_state.json`、`trace.jsonl`、`report.json` 3 类运行工件；
- Action Journal、3 个故障注入点、blind/guarded 恢复对照；
- 文件动作前后 Hash 对账，以及不确定 Shell 副作用转人工；
- freshness-aware Context：过期文件摘要和旧 `read_file` 结果不会进入新 Prompt；
- Harness、Context、Memory、Recovery 4 层评测。

### 这些数字必须带上边界

- Harness 的 12 个任务全部通过：这是 FakeModel 驱动的运行时合同测试，不是真实模型解决开放代码任务的 100% 成功率。
- Context 平均压缩 16.36%：是当前归档从 6994.33 字符降到 5575.67 字符；简历早期快照是 16.19%，模板变化会影响精确值。
- 重复读取 60 → 0：来自 12 个合成记忆任务，每个重复 5 次，不是线上统计。
- DeepSeek guarded 6/6：只来自 3 类故障 × 2 次重复；对照组 blind 是 4/6。
- Recovery 旧归档的 90% 和新实验的 6/6 是两套实验，不能混着说。

### 不能说已经实现

- SWE-bench 或真实线上流量评测；
- 完整 RAG、向量数据库和重排模型；
- Provider 原生 Function Calling；当前是模型输出 JSON/XML 文本，由 Runtime 解析；
- 生产级容器沙箱、完整 Prompt Injection 防御；
- HTTP 服务、高并发、多租户、分布式任务或分布式事务；
- Context 压缩已经证明真实任务成功率不下降。

## 二、项目介绍怎么说

### 30 秒版本

> 我做了一个本地 Coding Agent Runtime，叫 Page。它能读代码、改文件、运行命令，但我重点解决的不是工具数量，而是中断恢复。工具可能已经改完文件，Checkpoint 却还没保存；如果直接恢复旧对话，就可能重复修改。我用 Action Journal、文件 Hash 和后置条件先做确定性对账：完成了就跳过，没执行就重试，状态不确定就交给用户。然后再让模型继续任务，并用 freshness-aware Context 拦住过期文件信息。

### 两分钟版本

> 我在使用 Coding Agent 时发现，模型能力强不等于系统可靠。模型可能输出错格式、重复调用工具；任务时间一长，上下文会越来越大；进程中断后，旧对话也不一定反映当前文件状态。
>
> 所以我用 Python 标准库写了一个透明的 Agent Runtime。请求进来后，Context Manager 组装规则、记忆、历史和当前请求；模型选择工具后，Tool Executor 先做白名单、参数、路径、重复调用和审批检查，再执行动作。每次运行都会保存 Task State、Trace、Report 和 Checkpoint。
>
> Recovery 是主亮点。文件动作执行前先写 Action Journal，执行后记录 before/after Hash。恢复时由确定性代码核对当前文件，决定跳过、重试还是转人工。模型不负责猜底层状态。Context Manager 还会拒绝已经过期的文件摘要和读取结果。
>
> 评测分层做：FakeModel 验证运行时合同和状态机，DeepSeek 用 12 次成对任务做小样本真实模型验证。当前是 Windows 11 单机实验项目，不是生产级平台。

## 三、架构与执行流程

### Q1：一次请求是怎么执行的？

可以按 6 步说：

1. `AgentLoop.run()` 创建任务状态和 Run 目录。
2. `ContextManager.build()` 组装本轮 Prompt，并记录每段 Context 的处理原因。
3. Provider 返回工具调用或最终答案。
4. 如果是工具调用，`ToolExecutor` 做白名单、参数、路径、重复调用和审批检查。
5. 工具执行后，Runtime 记录结果、受影响文件、工作区指纹和 Checkpoint，然后进入下一轮。
6. 如果模型返回 final，任务完成并写入 Trace 和 Report。

格式错误会消耗模型尝试次数，但不消耗工具步骤；两种预算分开，避免模型无限重试。

源码入口：[`page/agent_loop.py`](../../page/agent_loop.py)、[`page/context_manager.py`](../../page/context_manager.py)、[`page/tool_executor.py`](../../page/tool_executor.py)。

### Q2：为什么自己写 Runtime，不直接用 LangChain 或 LangGraph？

> 我的目标不是最快拼一个 Demo，而是看清 Prompt 怎么组装、工具为什么执行、失败怎么记录、恢复为什么安全。自己写最小 Runtime，控制面更透明，也方便逐层测试。
>
> 如果以后做复杂业务，我不排斥 LangGraph。它适合显式状态机、人工审批和长流程，但权限、一致性、评测和审计仍然要自己设计。

### Q3：这不就是一个 while 循环吗？

> 控制循环确实可以写成 while，难点在循环外面：输出是否合法、错误怎么算预算、工具能不能越权、重复调用怎么停、文件改到一半怎么恢复、上下文超限保留什么、最后由谁验收。Page 的价值是把这些问题拆到解析、执行、Context、恢复和评测层，而不是全靠 System Prompt。

### Q4：Agent 和 Workflow 有什么区别？Page 属于哪个？

> Workflow 的路线主要由开发者写死；Agent 会让模型根据当前状态选择下一步。Page 的工具选择和停止时机由模型决定，所以有 Agent 特征；但权限、预算、恢复和验收是确定性的 Workflow。实际系统通常是两者结合。

### Q5：为什么模型说“完成了”还不算成功？

> 模型的 final 只是一个输出。Benchmark 还要检查步骤有没有超限、verifier 是否通过、预期文件是否存在、停止原因是否正常。验收程序才是成功标准。

## 四、Recovery：主亮点高频追问

### Q6：Recovery 到底解决什么问题？

> 它解决“外部动作可能已经发生，但系统状态还没保存”的问题。比如 Patch 已经写进文件，进程却在记录成功前崩溃。直接重放旧历史可能再次 Patch。Page 会先核对真实文件，再决定是否继续。

### Q7：Session、Task、Run、Checkpoint 分别是什么？

- Session：多轮对话和记忆的容器；
- Task：一条用户请求及其状态；
- Run：一次具体执行，有独立工件目录；
- Checkpoint：某个执行点的进度快照，用于恢复。

### Q8：为什么 Checkpoint 还不够？

> Checkpoint 只说明“任务进行到哪里”，不能单独证明某个文件动作有没有真正完成。Action Journal 记录具体动作是 planned、started 还是 succeeded，还保存文件前后 Hash。两者一起用，恢复器才能核对真实状态。

### Q9：Action Journal 的状态是什么意思？

```text
planned → started → succeeded
                  ↘ failed
                  ↘ reconciled
                  ↘ manual-review-required
```

- `planned`：准备执行；
- `started`：开始了，但还不能确认最终结果；
- `succeeded`：明确成功；
- `reconciled`：恢复时根据当前文件确认，其实已经完成；
- `manual-review-required`：无法安全判断，需要用户处理。

### Q10：恢复时怎么判断下一步？

> 如果当前文件等于 after Hash，说明动作已经完成，直接跳过；如果仍等于 before Hash，说明动作没生效，可以重试；如果两个都不等，说明文件被其他人或进程改过，停止自动恢复并转人工。

### Q11：为什么不能直接加载旧 History？

> History 只能说明过去记录了什么，不能保证当前工作区没变化。恢复时必须重新检查文件 Hash、工作区指纹、工具签名和数据版本。旧状态只能当缓存，不能当最终事实。

### Q12：为什么不让 DeepSeek 判断动作有没有执行？

> 模型看到的历史可能不完整，也看不到进程崩溃后的真实副作用。让模型猜，会把一致性问题变成概率问题。Page 先用确定性代码对账，再把恢复结论交给模型继续推理。

### Q13：哪些动作可以自动恢复？

> `write_file` 和 `patch_file` 有明确目标文件、before/after Hash 和后置条件，所以可以对账。`read_file` 没有写副作用，但文件变化后旧结果必须失效。任意 `run_shell` 可能改数据库、发请求或启动进程，单靠文件 Hash 不能证明副作用，因此中断后默认转人工。

### Q14：3 个故障注入点是什么？

1. 工具执行前中断；
2. 工具已经修改文件，但成功记录还没提交时中断；
3. Checkpoint 已保存，但 final 还没返回时中断。

这些故障由参数控制，只在测试目录中启用，不会随机影响普通 CLI。

### Q15：blind 和 guarded 有什么区别？

> `blind_resume` 直接加载旧状态，是实验对照组；`guarded_resume` 会先核对 Journal、文件和运行环境，再构建新的 Recovery Context。正常产品应该使用 guarded，blind 不能作为默认模式。

### Q16：DeepSeek 为什么只跑 12 次？

> 计算方式是 3 个故障任务 × blind/guarded 两种模式 × 2 次重复。目标是用有限时间和费用做机制冒烟，不是估计线上总体成功率。结果 blind 4/6、guarded 6/6，只能说明当前 3 类任务里的观察。

### Q17：结果稳定吗？

> FakeModel 是确定性的，可以稳定验证状态机和不变量。DeepSeek 每格只有两次，统计证据不足。最可信的是机制结论，比如 after Hash 匹配时不会重复执行，stale Hash 不会进入 Prompt；模型成功率只能说是小样本现象。

### Q18：Recovery 最大的边界是什么？

> 现在只完成 Windows 单机文件工具闭环。没有多进程锁、数据库事务、分布式共识或容器级 Shell 隔离，所以不能说成生产级高可用。

## 五、测试集和指标怎么解释

### Q19：项目有哪几层评测？

1. Harness regression：12 个固定任务，检查运行时合同；
2. Context matrix：`3 档 History × 2 档 Note × 2 档 Request = 12` 组；
3. Memory ablation：12 个记忆依赖任务；
4. Recovery：旧版 10 个任务的消融，加新版 3 类故障的 blind/guarded 成对实验。

每层回答的问题不同，不能合成一个总分。

### Q20：对照组分别是什么？

- Context：开启压缩和关闭压缩；
- Memory：`memory_on` 和 `memory_off`，另有 `memory_irrelevant` 检查错误召回；
- Recovery：旧实验比较 resume on/off，新实验比较 blind/guarded；
- Harness regression 没有传统对照组，它是固定输入的合同测试。

### Q21：12 组是不是太少？

> Context 的 12 组是完整的 3×2×2 因子组合，用来覆盖机制，不是从线上随机抽 12 个用户任务。它能说明不同压力组合如何影响裁剪，但不能证明真实任务上的统计稳定性。

### Q22：Context 压缩会不会影响成功率？

> 现有数据只能证明当前请求没有被裁掉，不能证明开放任务成功率完全不受影响。要证明这一点，需要固定模型、工作区和任务，只开关 Context Reduction，再比较 verifier、工具步数、耗时和失败类型。

### Q23：为什么平均压缩数字有两个版本？

> 简历的 16.19% 来自早期 Prompt 模板；当前归档复跑是 16.36%，从 6994.33 字符降到 5575.67 字符。Prefix 和工具说明变化会影响长度，所以精确数字必须绑定代码版本，不能把两次结果说成同一次实验。

### Q24：哪类 Context 压缩最多？

> 当前最高是 `long-low-short`，从约 9508 字符压到 6314，压缩 33.59%。主要原因是长 History 里重复和可摘要内容最多。短 History 的 4 组都是 0%，说明主要优化目标应该是历史，不是当前用户请求。

### Q25：为什么按字符数，不按 token？

> 字符数实现简单、零依赖、跨 Provider 可复现，但只是近似。中文、英文和代码的 token/char 比例不同。生产化应优先使用 Provider usage 或对应 tokenizer；报告里必须写“Prompt 字符数”，不能说成精确 token。

### Q26：FakeModel 有什么意义？

> 它相当于单元测试里的 Mock。固定模型输出后，可以稳定覆盖错格式、重复调用、路径逃逸、恢复等分支，方便判断是 Runtime 回归还是模型随机性。它能测框架，不能测真实模型理解能力。

### Q27：12 个 Harness 任务都是 100%，是不是太简单？

> 是，它们故意设计成小而确定的合同任务。100% 只说明这些已知边界没有回归，不代表真实模型很强。真实能力评测还需要未知仓库、真实 Bug 和真实模型。

## 六、Context 和 Memory

### Q28：Prompt 分哪几层？

主要包括：

1. Prefix：系统规则、工具说明和工作区信息；
2. Working Memory：任务摘要、近期文件和文件摘要；
3. Relevant Memory：根据当前问题召回的 Episodic / Durable Notes；
4. History：用户、助手和工具历史；
5. Current Request：本轮用户请求；
6. Recovery Context：恢复时的对账结果和安全状态。

默认总预算是 12000 字符。普通裁剪顺序是 `Relevant Memory → History → Working Memory → Prefix`。

### Q29：哪些内容不能随便裁？

> Current Request 和 Recovery Context 是受保护内容，不参加普通裁剪。如果受保护内容本身就超过总预算，系统返回 `protected_context_overflow`，不能悄悄删掉关键请求或恢复信息。

### Q30：为什么先裁 Relevant Memory？

> Relevant Memory 是检索出来的候选信息，可能召回不准，属于软上下文；History 是本轮真实动作，Working Memory 是任务状态，Prefix 里还有执行规则，所以先牺牲候选记忆。用户明确要求长期保留的硬约束应该升级成受保护内容。

### Q31：为什么优先保留最近的 History？

> 下一步通常最依赖刚才的工具结果和决定，所以近期历史保留更多原文，旧历史再摘要。最近 6 条只是工程经验值，不是理论最优值，应该通过成功率、重试率和成本继续验证。

### Q32：如果摘要写错了怎么办？

> 摘要不能成为没有来源的真相。文件摘要要保存路径、Hash 和生成时间；模型准备做高风险写入时，可以重新读取关键原文。正确做法是可追溯、按风险重验证，不是永久保存全部原文。

### Q33：Context 和 Memory 有什么区别？

> Context 是这一轮真正发给模型的有限输入；Memory 是跨轮保存、按需取用的状态。Memory 可以很多，但每轮只挑一部分进入 Context。

### Q34：Memory 分几层？

- Working Memory：当前任务摘要、近期文件、文件摘要；
- Episodic Notes：当前会话中的事实、决定和过程笔记；
- Durable Memory：明确保存、跨会话使用的长期知识；
- Retrieval View：从 Episodic 和 Durable 中选出本轮最相关的少量内容。

### Q35：为什么不用向量库？

> 当前规模小，知识主要来自本地代码和文件。路径、标签和关键词检索更简单，也更容易解释“为什么召回”。缺点是同义词和语义改写能力弱。规模变大后，可以升级成路径过滤 + BM25 + embedding + reranker 的混合检索。

### Q36：重复读取 60 → 0 是怎么测的？

> 12 个任务每个重复 5 次，共 60 个 follow-up。关闭 Memory 或提供无关 Memory 时，每次都要重新读文件；正确 Memory 被召回时可以直接回答，所以重复读取降到 0。这是人为构造的机制实验，不是线上用户数据。

### Q37：Memory 关闭后为什么正确率还是 100%？

> 因为关闭后仍允许重新读文件，所以最终还能答对，只是多一次工具调用。这个实验测的是效率，不是能力上限。

### Q38：长期记忆会不会越来越脏？

> 会，这是已知问题。现在有显式晋升、去重、敏感内容拒绝和 supersede，但还没有完整 TTL、置信度和用户纠错。生产化应默认谨慎写入，并支持查看、删除、修改和过期；重要事实使用前还要重新验证。

### Q39：为什么 Coding Agent 不一定先做 RAG？

> 仓库事实已经在文件系统和代码索引中，精确读取、搜索和符号跳转往往比把整个仓库切块更可靠。RAG 更适合外部文档、跨仓库规范和语义相似检索。Page 先把工具和状态一致性做好，再按知识类型决定是否接 RAG。

## 七、工具调用与安全

### Q40：工具调用协议是什么？

> Provider 返回带 `<tool>` 的 JSON/XML 文本，或者用 `<final>` 返回答案，Runtime 再解析。优点是跨 Provider 简单，缺点是没有原生 Function Calling 的强 schema、并行调用和结构化错误。以后可以统一成内部 `ToolCall` 对象，原生协议和文本协议都转换到这一层。

### Q41：工具安全检查顺序是什么？

```text
白名单
→ 工具是否存在
→ 参数和路径
→ 重复调用
→ 用户审批
→ 执行前快照
→ 真正执行
→ 执行后快照和审计
```

非法参数应该在审批前拒绝，避免让用户批准一个本来就不能执行的动作。

### Q42：怎么防路径逃逸？

> 文件路径先锚定到工作区根目录，再解析 `..` 和符号链接，最后检查解析后的路径仍在工作区内。这样可以拦住普通的 `../secret` 和符号链接跳转。

### Q43：有路径限制，Shell 不还是能绕过吗？

> 是。文件工具受工作区路径保护，但 `run_shell` 仍是通用 Shell，只靠审批和环境变量过滤不能叫强沙箱。生产化需要容器或受限用户、只读根文件系统、网络策略、资源限制和命令审计。

### Q44：3 种审批策略是什么？

- `ask`：高风险操作前询问用户，默认选择；
- `auto`：自动批准，只适合隔离的 Benchmark；
- `never`：拒绝高风险操作，适合只读审查。

### Q45：怎么防重复工具调用？

> Runtime 会拦截“同一个工具 + 同一组参数”的重复调用，并把结构化错误返回给模型。它能防简单死循环，但识别不了语义相同、写法不同的命令。进一步可以加入参数规范化、错误签名和短期动作图。

### Q46：写文件是原子的吗？

> Action Journal 和 Session 保存使用临时文件加原子替换，但目标文件的普通 `write_file` / `patch_file` 还不能宣传成完整并发事务。当前依靠单机工作区、审批、写前后 Hash 和 Git diff 控制风险。生产化还需要原子替换、fsync、写前版本检查和工作区锁。

### Q47：怎么防 Prompt Injection？

> 现在没有完整的 Injection 检测器。主要防线是最小权限：工具白名单、审批、路径限制、Secret 环境过滤和审计。即使仓库内容诱导模型，模型的能力仍受限制。真正生产化还要把仓库和工具输出标成不可信数据，并把高风险执行放进隔离环境。

### Q48：Secret 怎么保护？

> 配置会识别敏感变量名；Trace 和 Report 写入前递归脱敏；Shell 子进程只拿允许的环境变量，不默认继承所有 Key。面试时也绝不能显示 `.env` 内容。

## 八、Provider、性能和可观测性

### Q49：4 个 Provider 是 4 套完全不同的代码吗？

> 不是。Ollama、OpenAI-compatible、Anthropic-compatible 是 3 类 client，DeepSeek 复用兼容协议路径。CLI 读取模型、Base URL 和 Key，最后都转成统一的 `complete()` 接口。更准确的说法是“4 条 Provider 配置路径”。

### Q50：模型请求怎么重试？

> OpenAI-compatible 和 Anthropic-compatible 遇到 5xx 或连接错误最多尝试 3 次，等待 0.5 秒、1 秒；4xx 不盲目重试。Ollama 当前只尝试一次。429 的 `Retry-After`、指数退避、jitter 和熔断属于后续服务化设计。

### Q51：Prompt Cache 怎么做？

> 稳定 Prefix 会计算 Hash，只有 client 明确支持时才把它作为 cache key 传下去。动态 Memory、History 和 Request 不适合作为稳定前缀。当前 DeepSeek 报告显示 `prompt_cache_supported=false`，不能声称所有 Provider 都命中缓存。

### Q52：为什么没有流式输出？

> 当前优先保证控制流、解析和工件清楚，所以一次拿完整响应再判断 tool 或 final。以后可以流式展示普通文本，但必须等完整、合法的 ToolCall 到齐后才能执行工具，不能收到半段就执行。

### Q53：现在有哪些可观测性？

> 每次 Run 都有 Task State、事件级 Trace 和汇总 Report。可以看到 Context 长度和裁剪原因、模型尝试次数、工具步骤、耗时、受影响文件、工作区指纹、恢复状态和 Secret 脱敏数量。

### Q54：失败怎么归因？

> 我会按输入理解、规划、检索、Context、模型格式、工具校验、工具执行、环境、verifier、预算和恢复一致性分类。先找 Trace 中第一处偏离，再看后面的错误是根因还是连锁反应，不能把所有问题都归为“模型不够强”。

### Q55：如果要支持高并发，怎么设计？

先说明“下面是生产化方案，不是当前已实现”：

- API 收请求并持久化 Task，Worker 异步执行；
- 每个 Workspace 独立目录，同一 Workspace 串行或加锁；
- Provider 调用加并发限制、令牌桶和租户配额；
- 支持超时、取消、幂等 Key、重试、熔断和降级；
- 状态放数据库，工件放对象存储，事件通过 SSE 或 WebSocket 推送；
- 监控成功率、排队时间、P95/P99、429/5xx 和单成功任务成本。

### Q56：怎么做降级？

> 先减少非关键 Relevant Memory 和额外反思，再降低召回数量和输出长度；简单任务切便宜模型；高风险写入无法保证时退化为只读建议；Provider 故障时排队或切备用 Provider。每次降级都要写进 Trace，不能悄悄改变任务语义。

## 九、岗位针对性追问

### Q57：项目如何体现需求理解和问题归因？

> 我没有把目标写成“做一个更智能的 Agent”，而是拆成 Prompt 膨胀、重复读文件、中断丢状态、工具副作用和结果难复盘。每个问题都有对应模块和指标：Context 字符数、重复读取次数、恢复状态、受影响文件和 verifier 成功。这样需求才能验证。

### Q58：怎么把模糊业务问题转成 AI 目标？

> 先问用户要做什么决策、失败成本是什么；再拆哪些部分交给模型，哪些部分用确定性代码；知识从哪里来；允许哪些动作；成功由谁验收；无法判断时谁接管。最后建立基线、对照组和指标树。

### Q59：为什么没有单独的 Planner 和 Reflector？

> 当前任务规模下，模型在 ReAct 循环中隐式拆解已经够用，工具错误也会回到下一轮纠正，所以我没有临时增加新层。任务更复杂时，可以加入结构化的目标、子任务和完成条件，并只在 verifier 失败、重复错误或高风险决策前做有限次反思。

### Q60：为什么没有 API 或 SDK？

> 当前目标是验证 Windows 本地 Runtime，不是部署平台，所以只做 CLI。生产化时会保持 Core Runtime 不依赖 Web，在外层增加 Task API、异步 Worker、取消、鉴权和多租户隔离，让 CLI、API 和评测共用同一个核心。

### Q61：MCP、Skill 和 Page 工具是什么关系？

> Page 当前是进程内工具注册表；MCP 解决工具发现、schema 和跨进程调用标准化；Skill 更像可复用的任务说明和流程。即使接入 MCP，远端工具仍要经过本地白名单、审批、超时、脱敏和审计。协议统一不等于自动安全。

### Q62：如果接业务搜索场景，怎么改？

> 把文件工具换成查询理解、检索、特征查询、结果解释、实验平台和工单工具。Memory 保存用户或运营上下文，但要加权限和 TTL；RAG 接业务规则和案例库；Evaluator 从代码 verifier 变成离线标注、规则校验和线上 A/B。模型负责开放决策，确定性流程负责权限和验收。

### Q63：SFT 或 RL 在这里怎么用？

> 当前没有训练模型。应该先把 Prompt、工具和评测做好，积累高质量 Trace。之后可以用成功轨迹做 SFT，提高工具调用稳定性；再用 verifier、步骤成本和安全惩罚构造偏好或奖励。但训练前要处理数据泄露、错误轨迹和奖励投机。

### Q64：vLLM、KV Cache 和项目有什么关系？

> Page 的 Prompt Cache 是应用层稳定前缀复用；KV Cache 是推理引擎复用已经计算的 attention key/value。以后自托管模型时，vLLM 的 continuous batching、PagedAttention 和 prefix caching 可以提升吞吐。应用层也要保持前缀稳定，并记录首 token 和总延迟。

## 十、压力追问

### Q65：当前测试真的全部通过吗？

> Windows 快速集是 `120 passed, 1 skipped, 28 deselected`，约 52 秒；唯一 skip 是系统没有符号链接权限。完整套件是 `148 passed, 1 skipped`，耗时 7 分 56 秒。之后只改了 3 处 UTC 时间写法，相关 4 个慢速测试重新通过。现场跑快速集，完整慢速实验展示预生成工件。

### Q66：为什么完整测试要接近 8 分钟？

> 完整套件会创建多个临时工作区，并串行重复 Context、Memory 和 Recovery 消融。现场没必要等待，所以用 `pytest -q -m "not slow"` 跑快速集；慢实验提前生成 JSON，并绑定代码版本。

### Q67：这些数据是不是为了简历编的？

> 它们是为验证机制设计的合成 Benchmark，不是线上业务数据。我保存了任务定义、重复次数、verifier、汇总 JSON 和来源信息，可以复跑，也明确写了适用边界。合成数据可以用于机制验证，但不能包装成线上效果。

### Q68：项目最大的 3 个局限是什么？

> 第一，DeepSeek 只有 12 次小样本，任务类型少。第二，Shell 不是容器沙箱，也不能通用自动恢复。第三，Action Journal 是单机文件，没有多进程锁、数据库事务和分布式一致性。

### Q69：只能改一个地方，下一步做什么？

> 我会扩充真实恢复 Case，而不是继续加功能。从真实开发 Trace 中抽取复合 Patch、工具超时、文件规模变化和人工接管场景，保持 blind/guarded 成对实验并做失败归因。这样能直接增强核心亮点的可信度。

### Q70：你最满意的设计是什么？

> 我最满意的是把不确定性拆开：格式错误放在解析层，越权和副作用放在工具层，上下文膨胀放在 Context 层，过期状态放在恢复层，是否完成交给 verifier。这样能定位问题并做确定性兜底，而不是所有问题都继续堆 Prompt。

## 十一、生产化设计图怎么讲

先明确：**下图是未来方案，不是当前仓库已经实现的架构。**

```text
Client / CLI
     |
Task API -- 鉴权 / 配额 / 幂等
     |
Queue ---- 调度 / 取消 / 重试
     |
按 Workspace 隔离的 Worker
     |---- Context + Memory / RAG
     |---- Agent Runtime
     |---- Tool Gateway / MCP
     |---- Sandbox / Approval / Policy
     |---- Model Gateway / 限流 / 熔断
     |
State DB + Artifact Store + Trace / Metrics
     |
离线评测 / 回放 / 归因 / A-B
```

讲解顺序：任务先持久化再入队；同一 Workspace 避免并发写；工具经过策略网关和沙箱；模型经过统一网关；所有事件可以回放；离线评测和线上失败 Case 一起驱动迭代。

## 十二、五分钟 Recovery 话术

1. “我先用 FakeModel 跑离线演示，避免现场依赖网络。DeepSeek 的 12 次成对任务已经提前生成工件。”
2. “这里故意让文件已经修改，但 Journal 还停在 started。blind 直接续跑，guarded 会先核对 Hash 和后置条件。”
3. “guarded 发现目标结果已经存在，把动作标成 reconciled 或直接跳过，不会重复 Patch。这个决定来自 Runtime，不是模型猜的。”
4. “然后我从外部修改文件。旧 `read_file` 的来源 Hash 过期，被标成 `stale_rejected`，只有重新读取后的事实会进入 Prompt。”
5. “FakeModel 用来证明状态机，DeepSeek 是 3×2×2 的小样本：blind 4/6，guarded 6/6。”
6. “边界也很明确：文件动作可以对账，任意 Shell 中断要转人工；当前是单机恢复内核，不是分布式事务。”

## 十三、最后速记卡

### 必背数字

- 4 条 Provider 配置路径；
- 7 类工具；
- 3 类运行工件；
- Harness：12 个固定合同任务；
- Context：3×2×2 = 12 组，6994.33 → 5575.67 字符，平均压缩 16.36%，最高 33.59%；
- Memory：12 个任务 × 5 次，重复读取 60 → 0；
- Recovery 旧归档：10 个任务 × 3 次，成功率 90%，漂移识别 100%，false accept 为 0；
- Recovery 新实验：3 个任务 × 2 种模式 × 2 次；DeepSeek blind 4/6、guarded 6/6；FakeModel guarded 跳过 2 次重复文件动作；
- 当前请求保留率 100%，但不等于任务成功率不下降。

### 必背普通裁剪顺序

```text
Relevant Memory → History → Working Memory → Prefix
```

Current Request 和 Recovery Context 受保护，不参加普通裁剪。

### 必背工具治理顺序

```text
白名单 → 工具存在 → 参数/路径 → 重复 → 审批 → 前快照 → 执行 → 后快照/审计
```

### 必须主动承认

- 当前主要用字符预算，不是精确 token 硬预算；
- FakeModel 只能验证 Runtime，不能代表真实模型能力；
- Shell 不是强沙箱；
- DeepSeek 只有小样本；
- 完整 Prompt Injection 防御、真实大规模 Eval 和服务化尚未实现。

### 最后一句总结

> 大模型不是确定性函数，所以 AI 应用不能只优化 Prompt。要给模型划清知识边界、动作边界、状态边界和证据边界。Page 的设计主线就是：让模型负责开放决策，让 Runtime 负责可控、可恢复和可验证。
