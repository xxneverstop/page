> 记录于 2026-07-03 15:30

## 变更概述

优化 `page` CLI 交互体验，参照 Claude Code 的设计思路，在不引入新依赖的前提下，用约 80 行改动覆盖 6 个核心交互痛点：Ctrl-C 行为、提示符信息量、响应元数据、命令行历史、配置查看、session 浏览。

## 变更前后对比

### 1. Ctrl-C 中断但不退出

**之前**：任何时候按 Ctrl-C 直接退出 REPL，用户手滑就丢失 session。

**之后**：模型正在跑时按 Ctrl-C → 中断当前 ask 但保留 session 和 REPL，提示用户再按一次才会退出。空闲时按 Ctrl-C → 照常退出。

```
interrupted — press Ctrl-C again or /exit to quit
```

### 2. 提示符显示模型名

**之前**：永远显示裸的 `page>`。

**之后**：显示 `page[deepseek-v4]>`（模型名截断到 12 字符），用户一眼确认当前连接的后端。

### 3. 响应后打印元数据

**之后**：每次 `ask()` 完成后打印一行 dim 元数据：

```
← 2 steps · 1847 chars
```

让用户对每次消耗有感知——之前是黑盒。

### 4. readline 历史

在 `main()` 开头 `import readline`（Windows 上装 `pyreadline3` 即可生效），`input()` 立刻获得 ↑↓ 翻历史、Ctrl-A/E 等 Emacs 键绑定，零侵入。

### 5. `/status` 命令

新增命令，查看当前生效配置：

```
provider:       deepseek
model:          deepseek-v4-pro
endpoint:       https://api.deepseek.com/anthropic
temperature:    0.2
approval:       ask
max_steps:      6
max_new_tokens: 512
session:        20260703-143022-a1b2c3
workspace:      D:/workspace/page
```

### 6. `/sessions` 命令

新增命令，列出当前 workspace 下可恢复的 session（按修改时间倒序），当前 session 标注 `(current)`。

### 7. 错误信息红色显示

RuntimeError 输出加上 ANSI 红色前缀 `✖`，与普通输出区分开。

## 涉及文件

| 文件 | 改动性质 |
|---|---|
| `page/cli.py` | 修改 — 核心改动：main() 重构、新增 _status_text / _sessions_text / _print_turn_meta 三个 helper、HELP_DETAILS 扩展 |
| `page/providers/clients.py` | 修改 — OllamaModelClient / OpenAICompatibleModelClient / AnthropicCompatibleModelClient 各自新增 `provider_name` 属性 |

## 注意事项

- **readline**：Windows 上需要 `pip install pyreadline3` 才能获得历史/补全。Unix/Mac 自带。
- **provider_name**：DeepSeek 复用 `AnthropicCompatibleModelClient` 但在 `_build_model_client()` 中覆盖 `provider_name = "deepseek"`，确保 `/status` 输出正确。
- **_print_turn_meta** 依赖 `agent.current_task_state` 和 `agent.last_prompt_metadata`——这两个在 agent loop 完成后已经填充，one-shot 和交互模式都能正确输出。
- 测试：121 passed，9 个预存失败均与 CLI 改动无关（evaluator fixtures、docs 路径缺失）。

## 验证方式

```bash
# 语法检查
python -c "import py_compile; py_compile.compile('page/cli.py', doraise=True)"

# 交互模式：进入后观察提示符、试 /status /sessions /help
python -m page

# one-shot + Ctrl-C
python -m page "list files" --max-steps 2
# 模型调用期间按 Ctrl-C，应显示 interrupted 提示并回到 REPL
```
