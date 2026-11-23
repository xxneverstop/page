# AGENTS.md

## 项目实施原则

- **简洁、稳定、可靠。** 所有具体实施方案都遵循这项原则，避免过度设计。优先复用项目已有实现，选择能完整满足需求的最小方案，保留必要的校验和错误处理。
- **主动使用 Context7。** 涉及库或 API 文档、代码生成、安装设置或配置步骤时，始终主动使用 Context7 查询相关文档。项目指定版本时，按对应版本查询。
- **代码遵循 Ponytail。** 优先复用现有代码和标准库，避免不必要的抽象、依赖和预留功能。新增或修改的所有关键代码都要添加简洁易懂的注释，说明设计意图、边界条件或容易误解的地方，避免复述代码。

<!-- codebase-memory-mcp:start -->
# Codebase Knowledge Graph (codebase-memory-mcp)

This project uses codebase-memory-mcp to maintain a knowledge graph of the codebase.
ALWAYS prefer MCP graph tools over grep/glob/file-search for code discovery.

## Priority Order
1. `search_graph` — find functions, classes, routes, variables by pattern
2. `trace_path` — trace who calls a function or what it calls
3. `get_code_snippet` — read specific function/class source code
4. `query_graph` — run Cypher queries for complex patterns
5. `get_architecture` — high-level project summary

## When to fall back to grep/glob
- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- When MCP tools return insufficient results

## Examples
- Find a handler: `search_graph(name_pattern=".*OrderHandler.*")`
- Who calls it: `trace_path(function_name="OrderHandler", direction="inbound")`
- Read source: `get_code_snippet(qualified_name="pkg/orders.OrderHandler")`
<!-- codebase-memory-mcp:end -->
