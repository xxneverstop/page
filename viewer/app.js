(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const nodes = {
    connection: $("connection"), refresh: $("refresh"), follow: $("follow"),
    runSearch: $("runSearch"), runStatus: $("runStatus"), runList: $("runList"), runCount: $("runCount"),
    runTitle: $("runTitle"), runBadge: $("runBadge"), runMeta: $("runMeta"), identityLine: $("identityLine"),
    captureBadge: $("captureBadge"), traceNote: $("traceNote"), metricGrid: $("metricGrid"),
    viewTabs: $("viewTabs"), viewRoot: $("viewRoot"), detailDrawer: $("detailDrawer"), detailTitle: $("detailTitle"),
    detailBody: $("detailBody"), closeDetail: $("closeDetail"),
  };

  const state = {
    runs: [], total: 0, loaded: false, runId: "", version: 0, inspection: null,
    view: "overview", follow: true, loading: false, error: "", fingerprint: "",
    detail: null, rawEvents: [], rawOffset: 0, rawMore: false, rawLoadedFor: "", rawFilter: "all", rawQuery: "",
    toolFilter: "all", toolQuery: "", contextA: "", contextB: "", copyPayloads: new Map(), copySequence: 0,
  };

  const STATUS = {
    running: "进行中", pending: "待开始", unknown: "未知", completed: "已完成", stopped: "已停止",
    failed: "失败", error: "失败", ok: "成功", rejected: "已拒绝", partial_success: "部分成功",
    incomplete: "未完成", final: "最终回答", tool: "工具调用", retry: "重试", tool_error: "工具失败",
  };
  const CATEGORY = { lifecycle: "生命周期", context: "上下文", model: "模型", decision: "操作判定", tools: "工具", recovery: "恢复", evaluation: "评测", other: "其他" };
  const EVENT_TITLES = {
    run_started: "收到用户请求", recovery_reconciled: "恢复对账", iteration_started: "开始执行轮次",
    prompt_built: "组装上下文", prompt_rendered: "生成实际 Prompt", finalization_requested: "进入收尾阶段",
    model_requested: "发起逻辑模型请求", model_http_request: "发送 HTTP 请求", model_http_response: "收到 HTTP 响应",
    model_http_error: "HTTP 请求异常", model_extracted: "提取模型响应", model_parsed: "解析操作判定",
    tool_requested: "模型请求工具", tool_stage: "工具安全阶段", tool_executed: "工具执行完成",
    iteration_finished: "结束执行轮次", checkpoint_created: "保存检查点", runtime_identity_mismatch: "运行身份不匹配",
    context_failed: "上下文构建失败", model_failed: "模型请求失败", run_finished: "运行结束",
  };
  const TOOL_STAGES = { validated: "参数已校验", approval_requested: "请求审批", approval_granted: "审批通过", approval_denied: "审批拒绝", executing: "执行中" };
  const importantEvents = new Set([
    "run_started", "iteration_started", "prompt_built", "model_requested", "model_parsed", "tool_requested",
    "tool_stage", "tool_executed", "iteration_finished", "checkpoint_created", "recovery_reconciled",
    "runtime_identity_mismatch", "finalization_requested", "context_failed", "model_failed", "run_finished",
  ]);

  const number = (value) => {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  };
  const text = (value) => value === null || value === undefined ? "" : String(value);
  const short = (value, limit = 140) => text(value).replace(/\s+/g, " ").trim().slice(0, limit);
  const escapeHtml = (value) => text(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
  const jsonText = (value) => {
    if (value === undefined) return "未知";
    if (typeof value === "string") return value;
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  };
  const jsonHtml = (value) => escapeHtml(jsonText(value));
  const clock = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString("zh-CN", { hour12: false });
  };
  const dateTime = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "未记录" : date.toLocaleString("zh-CN", { hour12: false });
  };
  const duration = (value) => {
    const ms = number(value);
    if (ms === null) return "未知";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    return `${Math.floor(ms / 60000)}分 ${Math.floor(ms % 60000 / 1000)}秒`;
  };
  const statusLabel = (value) => STATUS[text(value)] || text(value) || "未知";
  const eventCategory = (event) => event?.category || (text(event?.event).startsWith("tool_") ? "tools" : "other");
  const eventTitle = (event) => EVENT_TITLES[event?.event] || event?.event || "未知事件";
  const sourceLabel = (value) => value === "trace" ? "Trace 记录" : value === "viewer_inferred" ? "Viewer 推导" : "未知来源";
  const selectedRun = () => state.runs.find((run) => run.id === state.runId) || {};
  const inspection = () => state.inspection || {};
  const run = () => inspection().run || {};
  const stats = () => inspection().stats || {};
  const events = () => inspection().raw?.events || [];
  const safeArray = (value) => Array.isArray(value) ? value : [];
  const terminal = (value) => ["completed", "failed", "error", "stopped"].includes(value);

  function connection(message, isError = false) {
    nodes.connection.textContent = message;
    nodes.connection.classList.toggle("is-error", isError);
    nodes.connection.classList.toggle("is-ok", !isError);
    nodes.connection.title = isError ? message : `只读本地 Trace · ${state.follow ? "自动跟随最新运行" : "保持当前运行"}`;
  }

  function registerCopy(value) {
    const id = `copy-${++state.copySequence}`;
    state.copyPayloads.set(id, text(value));
    return id;
  }

  function copyButton(value) {
    return `<button type="button" class="filter-button" data-copy-id="${registerCopy(value)}">复制</button>`;
  }

  function metric(label, value, note, accent = false) {
    return `<div class="metric-card${accent ? " metric-accent" : ""}"><span class="metric-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></div>`;
  }

  function identityChip(label, value) {
    if (!value) return "";
    return `<span class="identity-chip"><b>${escapeHtml(label)}</b> ${escapeHtml(value)}</span>`;
  }

  function renderRuns() {
    const query = nodes.runSearch.value.trim().toLowerCase();
    const filter = nodes.runStatus.value;
    const visible = state.runs.filter((item) => {
      const matches = !query || [item.id, item.prompt, item.model, item.provider].some((value) => text(value).toLowerCase().includes(query));
      if (!matches) return false;
      if (!filter) return true;
      if (filter === "unfinished") return !terminal(item.status);
      return item.status === filter || filter === "failed" && item.status === "error";
    });
    nodes.runCount.textContent = `${visible.length} / ${state.total || state.runs.length}`;
    nodes.follow.textContent = state.follow ? "实时跟随" : "跟随已暂停";
    nodes.follow.classList.toggle("is-paused", !state.follow);
    nodes.follow.setAttribute("aria-pressed", String(state.follow));
    if (!visible.length) {
      nodes.runList.innerHTML = `<div class="empty-state"><strong>${state.loaded ? state.runs.length ? "没有匹配的运行" : "还没有运行记录" : "正在读取运行记录"}</strong><span>${state.runs.length ? "调整搜索词或状态筛选。" : "在 Page 中发送一个请求后，记录会自动出现在这里。"}</span></div>`;
      return;
    }
    nodes.runList.innerHTML = visible.map((item) => {
      const status = item.status || "unknown";
      const statusClass = status === "completed" ? "is-ok" : ["failed", "error"].includes(status) ? "is-error" : "is-warn";
      return `<button type="button" class="run-row${item.id === state.runId ? " is-selected" : ""}" data-run-id="${escapeHtml(item.id)}" aria-current="${item.id === state.runId ? "true" : "false"}">
        <span class="run-row-top"><span class="status-pill ${statusClass}">${escapeHtml(statusLabel(status))}</span><time class="run-time">${escapeHtml(clock(item.updated_at))}</time></span>
        <span class="run-prompt">${escapeHtml(item.prompt || "未记录用户请求")}</span>
        <span class="run-foot"><span>${escapeHtml(item.model || item.provider || "未知模型")}</span><span>工具 ${escapeHtml(item.tool_steps ?? "未知")} 次</span></span>
      </button>`;
    }).join("");
  }

  function renderHeader() {
    const current = run();
    const fallback = selectedRun();
    const currentStatus = current.status || fallback.status || "unknown";
    const statusClass = currentStatus === "completed" ? "is-ok" : ["failed", "error"].includes(currentStatus) ? "is-error" : currentStatus === "stopped" ? "is-warn" : "is-neutral";
    nodes.runTitle.textContent = current.user_request || fallback.prompt || (state.runId ? "运行详情" : "选择一条运行");
    nodes.runBadge.textContent = state.runId ? statusLabel(currentStatus) : "等待日志";
    nodes.runBadge.className = `status-pill ${statusClass}`;
    nodes.runMeta.textContent = state.runId ? [current.provider || fallback.provider || "未知 Provider", current.model || fallback.model || "未知模型", current.tool_protocol ? `${current.tool_protocol} 协议` : "", `${stats().event_count ?? events().length} 条事件`].filter(Boolean).join(" · ") : "数据来自当前工作区的 .page/runs";
    nodes.identityLine.innerHTML = state.runId ? [
      identityChip("Run", current.run_id || state.runId), identityChip("Task", current.task_id), identityChip("Session", current.session_id),
      identityChip("Stop", current.stop_reason), identityChip("证据", current.status_confidence === "recorded" ? "已记录" : "未知"),
    ].join("") : "";
    const detailed = !!current.detail_available;
    nodes.captureBadge.textContent = state.runId ? detailed ? "详细采集" : "基础采集" : "等待日志";
    nodes.captureBadge.className = `capture-badge ${detailed ? "is-ok" : state.runId ? "is-warn" : ""}`;
    nodes.traceNote.textContent = current.duration_source === "viewer_estimate" ? "耗时为 Viewer 根据已记录事件估算" : current.duration_source === "unknown" ? "结束时间未记录" : "";

    const usage = stats().usage || {};
    const context = stats().context || {};
    nodes.metricGrid.innerHTML = [
      metric("逻辑模型调用", state.runId ? stats().model_calls ?? "未知" : "—", stats().http_attempts_known ? `HTTP 尝试 ${stats().http_attempts}` : "HTTP 尝试未单独记录", true),
      metric("工具调用", state.runId ? stats().tool_calls ?? "未知" : "—", state.runId ? `成功 ${stats().tool_succeeded ?? 0} · 失败 ${stats().tool_failed ?? 0} · 拒绝 ${stats().tool_rejected ?? 0}` : "含拒绝与失败"),
      metric("Token 用量", usage.total_tokens === null || usage.total_tokens === undefined ? "未知" : usage.total_tokens.toLocaleString("zh-CN"), usage.known ? `输入 ${usage.input_tokens ?? "未知"} · 输出 ${usage.output_tokens ?? "未知"}` : "日志未记录实际 Token"),
      metric("上下文", context.used_chars === null || context.used_chars === undefined ? "未知" : `${context.used_chars.toLocaleString("zh-CN")} 字符`, context.budget_chars ? `预算 ${context.budget_chars.toLocaleString("zh-CN")} 字符` : "字符预算未记录"),
      metric("运行耗时", current.duration_ms === null || current.duration_ms === undefined ? "未知" : duration(current.duration_ms), current.duration_source === "trace" ? "run_finished 记录" : current.duration_source === "viewer_estimate" ? "Viewer 估算" : "未知", current.status === "completed"),
    ].join("");
  }

  function renderTabs() {
    for (const button of nodes.viewTabs.querySelectorAll("[data-view]")) button.setAttribute("aria-selected", String(button.dataset.view === state.view));
  }

  function eventSummary(event) {
    const name = event?.event || "";
    if (name === "run_started") return short(event.user_request || "用户请求未采集");
    if (name === "prompt_built") { const metadata = event.prompt_metadata || {}; return `${metadata.prompt_chars ?? "未知"} / ${metadata.prompt_budget_chars ?? "未知"} 字符 · 压缩 ${safeArray(metadata.budget_reductions).length} 次`; }
    if (name === "prompt_rendered") return `${event.tool_protocol || "未知"} 协议 · Provider 实际收到的文本已采集`;
    if (name === "model_requested") return `第 ${event.attempts ?? "未知"} 轮 · 已用工具 ${event.tool_steps ?? "未知"} 次`;
    if (name.startsWith("model_http_")) return name === "model_http_response" ? `HTTP ${event.status ?? "未知"} · 第 ${event.attempt ?? "未知"} 次发送` : name === "model_http_error" ? short(event.error || "HTTP 异常") : `第 ${event.attempt ?? "未知"} 次发送`;
    if (name === "model_extracted") return `${event.format || "未知"} 协议 · 解析前原始响应`;
    if (name === "model_parsed") return event.kind === "tool" ? `请求 ${event.tool_name || "未知工具"}` : event.kind === "final" ? "返回最终回答" : event.kind === "retry" ? "Harness 要求重试" : text(event.kind || "未记录类型");
    if (name === "tool_requested") return `${event.name || "未知工具"} · 进入工具执行器`;
    if (name === "tool_stage") return `${event.name || "未知工具"} · ${TOOL_STAGES[event.stage] || event.stage || "未知阶段"}`;
    if (name === "tool_executed") return `${event.name || "未知工具"} · ${statusLabel(event.tool_status)}${event.tool_error_code ? ` · ${event.tool_error_code}` : ""}`;
    if (name === "iteration_finished") return `${statusLabel(event.outcome)}${event.next_step ? ` · 下一步 ${event.next_step}` : ""}`;
    if (name === "recovery_reconciled") return [event.decision, event.resume_status, event.reason].filter(Boolean).join(" · ") || "恢复信息未记录";
    if (name === "checkpoint_created") return event.trigger || "保存检查点";
    if (name === "run_finished") return `${statusLabel(event.status)} · ${event.stop_reason || "停止原因未记录"}`;
    if (name === "context_failed" || name === "model_failed") return `${event.error_type || event.error_code || "错误"} · ${short(event.error || "")}`;
    return short(event.reason || event.error || event.status || "查看原始字段");
  }

  function eventRow(event, selected = false) {
    const category = eventCategory(event);
    return `<button type="button" class="event-row${selected ? " is-selected" : ""}" data-event-id="${escapeHtml(event.event_id || "")}"><time>${escapeHtml(clock(event.created_at))}</time><span class="event-marker ${escapeHtml(category)}"></span><span class="event-copy"><strong>${escapeHtml(eventTitle(event))}</strong><span>${escapeHtml(eventSummary(event))}</span></span><span class="event-duration">${escapeHtml(duration(event.duration_ms))}</span></button>`;
  }

  function milestoneList(items) {
    return `<div class="milestones">${items.map((event) => { const category = eventCategory(event); return `<button type="button" class="milestone clickable" data-event-id="${escapeHtml(event.event_id || "")}"><time>${escapeHtml(clock(event.created_at))}</time><span class="milestone-dot ${escapeHtml(category)}"></span><span class="milestone-main"><span class="milestone-title">${escapeHtml(eventTitle(event))}</span><span class="milestone-summary">${escapeHtml(eventSummary(event))}</span></span></button>`; }).join("")}</div>`;
  }

  function overviewView() {
    const current = run();
    const important = events().filter((event) => importantEvents.has(event.event));
    const recent = important.length > 12 ? important.slice(-12) : important;
    const finalAnswer = current.final_answer || "最终回答未记录";
    const evaluation = inspection().evaluation || {};
    const context = stats().context || {};
    const coverage = [
      ["模型原始响应", current.detail_available ? "已采集" : "未采集", current.detail_available],
      ["Context 预算", context.budget_chars !== null && context.budget_chars !== undefined ? "字符预算" : "未知", context.budget_chars !== null && context.budget_chars !== undefined],
      ["恢复证据", inspection().recovery?.events?.length ? `${inspection().recovery.events.length} 条` : "未记录", !!inspection().recovery?.events?.length],
      ["独立验收", evaluation.status === "recorded" ? "已记录" : "未知", evaluation.status === "recorded"],
    ];
    return `<div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>用户任务</h2><span class="tag">Run scope</span></div><div class="subpanel-body"><div class="request-block"><div class="block-label"><span>原始请求</span>${copyButton(current.user_request || "")}</div><div class="block-content">${escapeHtml(current.user_request || "未采集。详细正文取决于运行时采集开关。")}</div></div><div class="answer-block" style="margin-top:.55rem"><div class="block-label"><span>Agent 最终回答</span>${copyButton(finalAnswer)}</div><div class="block-content">${escapeHtml(finalAnswer)}</div></div></div></div><div class="subpanel"><div class="subpanel-heading"><h2>证据覆盖</h2><span class="tag">实际记录</span></div><div class="subpanel-body"><div class="section-grid">${coverage.map(([label, value, known]) => `<div class="section-card${known ? " is-protected" : ""}"><strong>${escapeHtml(label)}</strong><div class="section-stats"><span>${escapeHtml(value)}</span><span>${known ? "可核对" : "未知"}</span></div></div>`).join("")}</div><dl class="kv-list" style="margin-top:.75rem">${[["开始", dateTime(current.started_at)], ["结束", current.finished_at ? dateTime(current.finished_at) : "未记录"], ["停止原因", current.stop_reason || "未知"], ["Trace schema", current.trace_schema || "未知"]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div><div class="subpanel"><div class="subpanel-heading"><h2>关键里程碑</h2><span class="count-badge">${recent.length}</span></div><div class="subpanel-body">${recent.length ? milestoneList(recent) : `<div class="empty-state"><strong>暂无里程碑</strong><span>这份运行还没有可展示的关键事件。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>执行摘要</h2><span class="tag">Summary</span></div><div class="subpanel-body"><dl class="kv-list">${[["执行轮次", stats().iterations ?? "未知"], ["模型重试", stats().model_retries ?? "未知"], ["检查点", stats().checkpoints ?? "未知"], ["事件总数", stats().event_count ?? "未知"], ["Trace 截断", stats().trace_truncated ? "是" : "否"], ["独立 Verifier", evaluation.status === "recorded" ? "已记录" : "未知"]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div></div>`;
  }

  function flowHtml() {
    const available = state.inspection ? ["context", "model", "decision", "tools", "context"].map((category) => events().some((event) => eventCategory(event) === category)) : [];
    const steps = [["用户请求", true], ["Context", available[0]], ["Model", available[1]], ["Decision", available[2]], ["Tool / Result", available[3]], ["下一轮 Context", available[4]]];
    return `<div class="flow">${steps.map(([label, active], index) => `${index ? `<span class="flow-arrow">→</span>` : ""}<span class="flow-step${active ? " is-active" : ""}">${escapeHtml(label)}</span>`).join("")}</div>`;
  }

  function iterationTitle(iteration) {
    if (iteration.outcome === "final") return "模型返回最终回答";
    if (iteration.outcome === "retry") return "模型输出需要重试";
    if (iteration.tools?.length) return `执行 ${iteration.tools.map((tool) => tool.name).join("、")}`;
    const model = iteration.model;
    return model?.parsed?.kind === "tool" ? `请求 ${model.parsed.tool_name || "工具"}` : "模型决策进行中";
  }

  function executionView() {
    const list = safeArray(inspection().iterations);
    if (!list.length) return `<div class="empty-panel"><strong>无法建立轮次</strong><span>旧 Trace 缺少模型请求或轮次证据，原始事件仍可在 Raw Trace 查看。</span></div>`;
    return `${flowHtml()}<div class="toolbar" style="margin-top:.65rem"><span class="label">按 Agent Loop 轮次组织</span><span class="tag">${list.length} iterations</span><span class="source-note">缺少显式 ID 的旧日志会标记为 Viewer 推导</span></div><div class="iterations">${list.map((iteration, index) => { const open = state.detail?.type === "iteration" && state.detail.id === iteration.id || !state.detail && index === list.length - 1; const iterationEvents = safeArray(iteration.events); return `<details class="iteration-card" data-iteration-id="${escapeHtml(iteration.id)}"${open ? " open" : ""}><summary class="iteration-summary"><span class="iteration-number">I${escapeHtml(iteration.index)}</span><span class="iteration-title"><strong>${escapeHtml(iterationTitle(iteration))}</strong><span>${escapeHtml(iteration.source === "viewer_inferred" ? "Viewer 推导轮次" : "Trace 记录轮次")} · ${escapeHtml(iterationEvents.length)} 条事件</span></span><span class="iteration-meta"><span class="status-pill ${iteration.status === "failed" ? "is-error" : iteration.status === "completed" ? "is-ok" : "is-warn"}">${escapeHtml(statusLabel(iteration.outcome))}</span><span>${escapeHtml(duration(iteration.duration_ms))}</span></span></summary><div class="iteration-body"><div class="event-list">${iterationEvents.map((event) => eventRow(event, state.detail?.type === "event" && state.detail.id === event.event_id)).join("")}</div></div></details>`; }).join("")}</div>`;
  }

  function contextCard(context, selected) {
    const sections = context.sections || {};
    const order = context.section_order?.length ? context.section_order : Object.keys(sections);
    return `<button type="button" class="inspection-card clickable${selected ? " is-selected" : ""}" data-context-id="${escapeHtml(context.event_id || "")}" style="text-align:left;width:100%"><div class="card-top"><div><div class="card-title">${escapeHtml(context.iteration_id || "上下文快照")}</div><div class="card-subtitle">序号 ${escapeHtml(context.sequence ?? "未知")} · ${escapeHtml(context.detail_available ? "包含实际 Prompt" : "仅有元数据")}</div></div><div class="card-badges"><span class="tag">${escapeHtml(context.prompt_chars ?? "未知")} chars</span><span class="tag">${escapeHtml(context.token_estimate ?? "未知")} tokens 估算</span></div></div><div style="margin-top:.6rem"><div class="budget-track"><span class="budget-used" style="width:${context.prompt_budget_chars ? Math.min(100, (Number(context.prompt_chars || 0) / Number(context.prompt_budget_chars)) * 100) : 0}%"></span>${context.prompt_over_budget ? '<span class="budget-over" style="width:6%"></span>' : ""}</div><div class="budget-legend"><span>${escapeHtml(context.prompt_chars ?? "未知")} / ${escapeHtml(context.prompt_budget_chars ?? "未知")} 字符</span><span>${escapeHtml(safeArray(context.budget_reductions).length)} 次压缩</span></div></div><div class="section-stats" style="margin-top:.55rem">${order.slice(0, 6).map((name) => `<span>${escapeHtml(name)} ${escapeHtml(sections[name]?.rendered_chars ?? "未知")}</span>`).join("")}</div></button>`;
  }

  function contextDiffHtml(first, second) {
    if (!first || !second) return `<div class="empty-state"><strong>选择两个轮次</strong><span>上下文差异需要两个实际采集的快照。</span></div>`;
    const diff = second.diff || {};
    return `<div class="diff-box"><div class="card-subtitle">来源 ${escapeHtml(diff.source || "未知")} · ${diff.available ? "可比较" : "不可比较"}</div>${diff.sections?.length ? `<table class="data-table" style="margin-top:.45rem"><thead><tr><th>Section</th><th>变化</th><th>依据</th></tr></thead><tbody>${diff.sections.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.delta_rendered_chars > 0 ? `+${item.delta_rendered_chars}` : item.delta_rendered_chars)}</td><td>${escapeHtml(item.source)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-state"><span>结构化元数据没有记录可见变化。</span></div>`}${diff.text ? `<pre class="payload">${escapeHtml(diff.text)}</pre>` : ""}</div>`;
  }

  function contextView() {
    const contexts = safeArray(inspection().contexts);
    if (!contexts.length) return `<div class="empty-panel"><strong>上下文证据未采集</strong><span>这份运行只有基础事件，无法核对实际 Prompt。启动 Page 时使用 <span class="mono">--trace-detail</span> 可采集完整正文。</span></div>`;
    const first = contexts.find((item) => item.event_id === state.contextA) || contexts[contexts.length - 2] || contexts[0];
    const second = contexts.find((item) => item.event_id === state.contextB) || contexts[contexts.length - 1] || contexts[0];
    state.contextA = first.event_id || state.contextA;
    state.contextB = second.event_id || state.contextB;
    const sections = second.sections || {};
    const order = second.section_order?.length ? second.section_order : Object.keys(sections);
    return `<div class="toolbar"><span class="label">相邻轮次 Diff</span><select class="select-input" data-context-select="a" style="width:auto;margin-top:0">${contexts.map((item) => `<option value="${escapeHtml(item.event_id)}"${item.event_id === first.event_id ? " selected" : ""}>${escapeHtml(item.iteration_id || item.event_id)}</option>`).join("")}</select><span class="muted">→</span><select class="select-input" data-context-select="b" style="width:auto;margin-top:0">${contexts.map((item) => `<option value="${escapeHtml(item.event_id)}"${item.event_id === second.event_id ? " selected" : ""}>${escapeHtml(item.iteration_id || item.event_id)}</option>`).join("")}</select></div><div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>Context 组成</h2><span class="tag">${escapeHtml(second.source || "未知来源")}</span></div><div class="subpanel-body"><div class="budget-track"><span class="budget-used" style="width:${second.prompt_budget_chars ? Math.min(100, Number(second.prompt_chars || 0) / Number(second.prompt_budget_chars) * 100) : 0}%"></span></div><div class="budget-legend"><span>${escapeHtml(second.prompt_chars ?? "未知")} / ${escapeHtml(second.prompt_budget_chars ?? "未知")} 字符</span><span>Token 估算 ${escapeHtml(second.token_estimate ?? "未知")} · ${escapeHtml(second.token_estimate_method || "未知方法")}</span></div><table class="data-table" style="margin-top:.7rem"><thead><tr><th>Section</th><th>原始</th><th>保留</th><th>预算</th></tr></thead><tbody>${order.map((name) => { const item = sections[name] || {}; const trimmed = Number(item.raw_chars || 0) > Number(item.rendered_chars || 0); return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(item.raw_chars ?? "未知")}</td><td class="${trimmed ? "muted" : ""}">${escapeHtml(item.rendered_chars ?? "未知")}${trimmed ? " · 裁剪" : ""}</td><td>${escapeHtml(item.budget_chars ?? "保护/未知")}</td></tr>`; }).join("")}</tbody></table>${second.prompt ? `<details class="disclosure"><summary>实际发送 Prompt（${escapeHtml(second.prompt.length)} 字符）</summary><pre class="payload">${escapeHtml(second.prompt)}</pre></details>` : `<span class="source-note">实际 Prompt 正文未采集，当前只展示 Context 元数据。</span>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>Context Diff</h2><span class="tag">${escapeHtml(first.iteration_id || "")} → ${escapeHtml(second.iteration_id || "")}</span></div><div class="subpanel-body">${contextDiffHtml(first, second)}</div></div></div><div class="subpanel" style="margin-top:.65rem"><div class="subpanel-heading"><h2>快照列表</h2><span class="count-badge">${contexts.length}</span></div><div class="subpanel-body">${contexts.map((item) => contextCard(item, item.event_id === second.event_id)).join("")}</div></div>`;
  }

  function pipeline(request) {
    const steps = [["Context", !!request.prompt, request.prompt?.prompt ? "实际 Prompt" : "元数据"], ["Provider", !!request.requested, request.requested ? "已请求" : "未记录"], ["HTTP", !!request.http_attempts?.length, `${request.http_attempts?.length || 0} 次`], ["Adapter", !!request.extracted, request.extracted?.format || "未记录"], ["Decision", !!request.parsed, request.parsed?.kind || "未记录"]];
    return `<div class="pipeline">${steps.map(([label, done, note]) => `<div class="pipeline-step ${done ? "done" : ""}">${escapeHtml(label)}<small>${escapeHtml(note)}</small></div>`).join("")}</div>`;
  }

  function modelView() {
    const models = safeArray(inspection().models);
    if (!models.length) return `<div class="empty-panel"><strong>模型调用证据未记录</strong><span>当前 Trace 没有可关联的模型请求事件。</span></div>`;
    return `<div class="toolbar"><span class="label">按逻辑模型请求聚合</span><span class="tag">HTTP 重试不会被算作新轮次</span></div><div>${models.map((request) => `<button type="button" class="inspection-card clickable" data-model-id="${escapeHtml(request.id)}" style="display:block;width:100%;text-align:left"><div class="card-top"><div><div class="card-title">${escapeHtml(request.id)}</div><div class="card-subtitle">${escapeHtml(request.iteration_id || "未知轮次")} · ${escapeHtml(request.source === "viewer_inferred" ? "旧日志推导" : "Trace 关联")}</div></div><div class="card-badges"><span class="status-pill ${request.status === "failed" ? "is-error" : request.status === "final" ? "is-ok" : "is-warn"}">${escapeHtml(statusLabel(request.status))}</span><span class="tag">HTTP ${escapeHtml(request.http_attempts?.length || 0)}</span></div></div>${pipeline(request)}<div class="card-subtitle" style="margin-top:.55rem">${escapeHtml(request.parsed ? eventSummary(request.parsed) : request.request ? "等待模型响应" : "模型请求字段缺失")}</div></button>`).join("")}</div>`;
  }

  function toolView() {
    const tools = safeArray(inspection().tools);
    const filtered = tools.filter((tool) => (!state.toolQuery || `${tool.name} ${tool.id} ${jsonText(tool.request?.args || {})}`.toLowerCase().includes(state.toolQuery.toLowerCase())) && (state.toolFilter === "all" || tool.status === state.toolFilter));
    if (!tools.length) return `<div class="empty-panel"><strong>工具调用证据未记录</strong><span>基础 Trace 可能只保留工具计数，详细工具阶段需要 Trace detail。</span></div>`;
    return `<div class="toolbar"><input class="search-input" data-tool-search type="search" value="${escapeHtml(state.toolQuery)}" placeholder="搜工具、调用 ID 或参数"><button type="button" class="filter-button${state.toolFilter === "all" ? " is-active" : ""}" data-tool-filter="all">全部</button>${["ok", "error", "rejected", "partial_success", "unknown"].map((filter) => `<button type="button" class="filter-button${state.toolFilter === filter ? " is-active" : ""}" data-tool-filter="${filter}">${escapeHtml(statusLabel(filter))}</button>`).join("")}<span class="tag">${filtered.length} / ${tools.length}</span></div><div>${filtered.map((tool) => `<button type="button" class="inspection-card clickable" data-tool-id="${escapeHtml(tool.id)}" style="display:block;width:100%;text-align:left"><div class="card-top"><div><div class="card-title">${escapeHtml(tool.name)}</div><div class="card-subtitle">${escapeHtml(tool.id)} · ${escapeHtml(tool.iteration_id || "未知轮次")}</div></div><div class="card-badges"><span class="status-pill ${tool.status === "ok" ? "is-ok" : tool.status === "rejected" || tool.status === "error" ? "is-error" : "is-warn"}">${escapeHtml(statusLabel(tool.status))}</span>${tool.risk_level ? `<span class="tag">风险 ${escapeHtml(tool.risk_level)}</span>` : ""}</div></div><div class="section-stats" style="margin-top:.55rem"><span>${escapeHtml(tool.read_only === true ? "只读" : tool.read_only === false ? "有副作用" : "读写未知")}</span><span>${escapeHtml(tool.workspace_changed === true ? "工作区已变化" : tool.workspace_changed === false ? "工作区未变化" : "变化未知")}</span><span>${escapeHtml(tool.affected_paths?.length || 0)} 个受影响路径</span></div><div class="card-subtitle" style="margin-top:.5rem">${escapeHtml(tool.recovery_action || tool.action_phase || tool.approval || "执行阶段未记录")}</div></button>`).join("") || `<div class="empty-state"><strong>没有匹配的工具调用</strong><span>调整筛选条件。</span></div>`}</div>`;
  }

  function recoveryView() {
    const recovery = inspection().recovery || {};
    const recoveryEvents = safeArray(recovery.events);
    const decision = recovery.decision || {};
    return `<div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>恢复决策</h2><span class="tag">${escapeHtml(decision.mode || "未记录")}</span></div><div class="subpanel-body">${decision && Object.keys(decision).length ? `<dl class="kv-list">${[["决定", decision.decision], ["恢复状态", decision.resume_status], ["原因", decision.reason], ["已对账", decision.reconciled_actions], ["可重试", decision.retryable_actions], ["跳过", decision.skipped_actions], ["人工复核", decision.manual_review_actions]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(jsonText(value || "未记录"))}</dd>`).join("")}</dl>` : `<div class="empty-state"><strong>没有恢复决策</strong><span>这份运行没有记录恢复协调证据。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>Action Journal / Checkpoint</h2><span class="tag">只读证据</span></div><div class="subpanel-body"><dl class="kv-list"><dt>Checkpoint</dt><dd>${escapeHtml(recovery.checkpoint_id || "未记录")}</dd><dt>Journal</dt><dd>${escapeHtml(recovery.journal ? "已记录" : "未记录")}</dd></dl>${recovery.journal ? `<pre class="payload">${jsonHtml(recovery.journal)}</pre>` : ""}</div></div></div><div class="subpanel" style="margin-top:.65rem"><div class="subpanel-heading"><h2>恢复相关事件</h2><span class="count-badge">${recoveryEvents.length}</span></div><div class="subpanel-body">${recoveryEvents.length ? milestoneList(recoveryEvents) : `<div class="empty-state"><span>没有 Recovery / Checkpoint 事件。</span></div>`}</div></div>`;
  }

  function evaluationView() {
    const evaluation = inspection().evaluation || {};
    return `<div class="view-grid equal"><div class="subpanel"><div class="subpanel-heading"><h2>独立验收</h2><span class="status-pill ${evaluation.status === "recorded" ? "is-ok" : "is-warn"}">${escapeHtml(evaluation.status === "recorded" ? "已记录" : "未知")}</span></div><div class="subpanel-body">${evaluation.status === "recorded" ? `<div class="card-subtitle">来源 ${escapeHtml(evaluation.source)}</div><pre class="payload">${jsonHtml(evaluation.evidence)}</pre>` : `<div class="empty-state"><strong>独立 Verifier 结果未知</strong><span>Agent 的最终回答与独立验收状态分开处理。当前 report 没有 verifier 或 evaluation 字段。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>运行指标</h2><span class="tag">当前 Run</span></div><div class="subpanel-body"><dl class="kv-list">${[["成功状态", run().status || "未知"], ["模型调用", stats().model_calls], ["HTTP 尝试", stats().http_attempts_known ? stats().http_attempts : "未知"], ["工具调用", stats().tool_calls], ["Token", stats().usage?.known ? stats().usage.total_tokens : "未知"], ["耗时", duration(run().duration_ms)]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div></div><div class="subpanel" style="margin-top:.65rem"><div class="subpanel-heading"><h2>评测数据边界</h2><span class="tag">Roadmap S5</span></div><div class="subpanel-body"><p class="card-subtitle">Viewer 只识别已有 report 中的评测证据，不重写 Evaluator，也不会把 Agent 自报完成推断为独立通过。</p></div></div>`;
  }

  function rawView() {
    const source = state.rawEvents.length ? state.rawEvents : events();
    const filtered = source.filter((event) => (!state.rawQuery || jsonText(event).toLowerCase().includes(state.rawQuery.toLowerCase())) && (state.rawFilter === "all" || eventCategory(event) === state.rawFilter));
    const shown = filtered.slice(-350);
    return `<div class="toolbar"><input class="search-input" data-raw-search type="search" value="${escapeHtml(state.rawQuery)}" placeholder="搜索事件、字段或内容"><button type="button" class="filter-button${state.rawFilter === "all" ? " is-active" : ""}" data-raw-filter="all">全部</button>${["lifecycle", "context", "model", "decision", "tools", "recovery", "other"].map((filter) => `<button type="button" class="filter-button${state.rawFilter === filter ? " is-active" : ""}" data-raw-filter="${filter}">${escapeHtml(CATEGORY[filter])}</button>`).join("")}<span class="tag">${shown.length} / ${filtered.length}</span></div>${source.length > shown.length ? `<div class="source-note">长 Trace 只渲染最近 ${shown.length} 条，服务端仍保留增量读取位置。</div>` : ""}<div class="subpanel" style="margin-top:.6rem"><div class="subpanel-heading"><h2>完整原始事件</h2><span class="tag">JSONL 顺序</span></div><div class="subpanel-body"><div class="event-list">${shown.map((event) => eventRow(event, state.detail?.type === "event" && state.detail.id === event.event_id)).join("") || `<div class="empty-state"><strong>没有匹配事件</strong><span>调整搜索条件。</span></div>`}</div></div></div>`;
  }

  function renderView() {
    if (!state.runId || !state.inspection) { nodes.viewRoot.innerHTML = `<div class="empty-panel"><strong>${state.error ? "加载运行失败" : "选择一条运行"}</strong><span>${escapeHtml(state.error || "左侧运行列表会显示当前工作区的 Page 工件。")}</span></div>`; return; }
    const renderer = { overview: overviewView, execution: executionView, context: contextView, model: modelView, tools: toolView, recovery: recoveryView, evaluation: evaluationView, raw: rawView }[state.view];
    nodes.viewRoot.innerHTML = renderer ? renderer() : overviewView();
  }

  function detailSection(title, content) { return `<section class="detail-section"><h3>${escapeHtml(title)}</h3>${content}</section>`; }
  function kv(items) { return `<dl class="kv-list">${items.filter(([, value]) => value !== undefined && value !== null && value !== "").map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(typeof value === "string" ? value : jsonText(value))}</dd>`).join("")}</dl>`; }
  function payload(title, value, copy = true) { const rendered = jsonText(value); return `<div class="block-label"><span>${escapeHtml(title)}</span>${copy ? copyButton(rendered) : ""}</div><pre class="payload">${escapeHtml(rendered)}</pre>`; }

  function eventDetail(event) {
    const category = eventCategory(event);
    let body = detailSection("关联身份", kv([["事件", event.event], ["类别", CATEGORY[category] || category], ["时间", dateTime(event.created_at)], ["序号", event.event_seq], ["Iteration", event.iteration_id], ["Model request", event.model_request_id], ["Tool call", event.tool_call_id], ["来源", sourceLabel(event.iteration_source)]]));
    if (event.event === "run_started") body += detailSection("用户请求", payload("请求正文", event.user_request));
    if (event.event === "prompt_built") body += detailSection("Context 元数据", payload("prompt_metadata", event.prompt_metadata));
    if (event.event === "prompt_rendered") body += detailSection("实际 Provider 输入", payload("Prompt", event.prompt));
    if (["model_http_request", "model_http_response"].includes(event.event)) body += detailSection(event.event === "model_http_request" ? "实际 HTTP 请求体" : "原始 HTTP 响应", `${kv([["接口", event.url], ["HTTP 状态", event.status], ["发送次数", event.attempt]])}${payload("正文", event.body)}`);
    if (["model_http_error", "model_failed", "context_failed"].includes(event.event)) body += detailSection("错误", `${kv([["错误类型", event.error_type], ["错误代码", event.error_code], ["接口", event.url], ["发送次数", event.attempt]])}${payload("错误信息", event.error || "未记录")}`);
    if (event.event === "model_extracted") body += detailSection("Adapter 提取结果", `${payload("文本", event.text)}${event.tool_calls?.length ? payload("原生 Tool Calls", event.tool_calls) : ""}`);
    if (event.event === "model_parsed") body += detailSection("Harness 操作判定", `${kv([["判定类型", event.kind], ["工具", event.tool_name], ["耗时", duration(event.duration_ms)]])}${Object.hasOwn(event, "payload") ? payload("解析载荷", event.payload) : payload("回答预览", event.answer_preview || "未采集")}${event.completion_metadata ? payload("用量与缓存", event.completion_metadata) : ""}`);
    if (["tool_requested", "tool_stage", "tool_executed"].includes(event.event)) body += detailSection("工具生命周期", `${kv([["工具", event.name], ["阶段", TOOL_STAGES[event.stage] || event.stage], ["状态", statusLabel(event.tool_status)], ["审批", event.approval], ["风险", event.risk_level], ["只读", event.read_only], ["工作区变化", event.workspace_changed], ["错误代码", event.tool_error_code], ["Action ID", event.action_id], ["Action phase", event.action_phase]])}${event.args ? payload("参数", event.args) : ""}${Object.hasOwn(event, "result") ? payload(event.verbose ? "完整工具结果" : "工具结果预览", event.result) : ""}${event.affected_paths?.length ? payload("受影响路径", event.affected_paths) : ""}${event.diff_summary?.length ? payload("变更摘要", event.diff_summary) : ""}`);
    if (event.event === "recovery_reconciled") body += detailSection("恢复判定", payload("recovery_decision", event));
    if (event.event === "checkpoint_created") body += detailSection("检查点", kv([["Checkpoint ID", event.checkpoint_id], ["触发原因", event.trigger]]));
    if (event.event === "run_finished") body += detailSection("结束信息", `${kv([["状态", statusLabel(event.status)], ["停止原因", event.stop_reason], ["耗时", duration(event.run_duration_ms)]])}${payload("最终回答", event.final_answer || "未记录")}`);
    body += `<details class="disclosure"><summary>全部原始字段</summary>${payload("JSON", event, false)}</details>`;
    return body;
  }

  function modelDetail(request) {
    let body = detailSection("逻辑请求", kv([["请求 ID", request.id], ["Iteration", request.iteration_id], ["状态", statusLabel(request.status)], ["来源", sourceLabel(request.source)]]));
    body += detailSection("请求链路", pipeline(request));
    if (request.prompt) body += detailSection("Local Context / Provider 输入", request.prompt.prompt ? payload("实际 Prompt", request.prompt.prompt) : payload("Prompt 事件", request.prompt));
    if (request.requested) body += detailSection("请求参数", payload("model_requested", request.requested));
    if (request.http_attempts?.length) body += detailSection("HTTP 尝试", request.http_attempts.map((item) => `<div class="detail-section"><div class="card-title">${escapeHtml(item.direction)} · attempt ${escapeHtml(item.attempt ?? "未知")}</div>${payload("字段", item, false)}</div>`).join(""));
    if (request.extracted) body += detailSection("Adapter 提取", payload("model_extracted", request.extracted));
    if (request.parsed) body += detailSection("Harness 解析", payload("model_parsed", request.parsed));
    body += `<details class="disclosure"><summary>关联事件 ID</summary>${payload("event_ids", request.event_ids, false)}</details>`;
    return body;
  }

  function toolDetail(tool) {
    let body = detailSection("调用身份", kv([["工具", tool.name], ["调用 ID", tool.id], ["Iteration", tool.iteration_id], ["Model request", tool.model_request_id], ["来源", sourceLabel(tool.source)]]));
    body += detailSection("执行状态", kv([["状态", statusLabel(tool.status)], ["风险等级", tool.risk_level], ["审批策略", tool.approval], ["只读", tool.read_only], ["工作区变化", tool.workspace_changed], ["Action ID", tool.action_id], ["Action phase", tool.action_phase], ["恢复动作", tool.recovery_action]]));
    if (tool.request) body += detailSection("模型原始请求", payload("参数", tool.request.args || {}));
    if (tool.phases?.length) body += detailSection("安全与执行阶段", tool.phases.map((phase) => eventRow(phase, false)).join(""));
    if (tool.result) body += detailSection("执行结果", `${payload("结果", tool.result.result || "未记录")}${tool.affected_paths?.length ? payload("受影响路径", tool.affected_paths) : ""}${tool.diff_summary?.length ? payload("变更摘要", tool.diff_summary) : ""}`);
    body += `<details class="disclosure"><summary>关联事件 ID</summary>${payload("event_ids", tool.event_ids, false)}</details>`;
    return body;
  }

  function contextDetail(context) {
    return `${detailSection("上下文身份", kv([["Iteration", context.iteration_id], ["序号", context.sequence], ["来源", sourceLabel(context.source)], ["详情", context.detail_available ? "实际 Prompt 已采集" : "只有元数据"]]))}${detailSection("预算", kv([["Prompt 字符", context.prompt_chars], ["字符预算", context.prompt_budget_chars], ["Token 估算", context.token_estimate], ["估算方法", context.token_estimate_method], ["超预算", context.prompt_over_budget ? "是" : "否"], ["压缩次数", context.budget_reductions?.length || 0]]))}${context.prompt ? detailSection("实际发送 Prompt", payload("Prompt", context.prompt)) : ""}${detailSection("结构化 Sections", payload("sections", context.sections))}`;
  }

  function renderDetail() {
    const target = state.detail;
    if (!target) { nodes.detailDrawer.classList.remove("is-open"); nodes.detailTitle.textContent = "等待选择证据"; nodes.detailBody.innerHTML = `<div class="empty-panel compact"><strong>选择一个步骤</strong><span>这里会展示实际采集的输入、判断、结果和原始字段。</span></div>`; return; }
    let body = "";
    if (target.type === "event") {
      const event = events().find((item) => item.event_id === target.id) || state.rawEvents.find((item) => item.event_id === target.id);
      if (!event) return;
      nodes.detailTitle.textContent = eventTitle(event); body = eventDetail(event);
    } else if (target.type === "model") {
      const request = safeArray(inspection().models).find((item) => item.id === target.id);
      if (!request) return;
      nodes.detailTitle.textContent = "逻辑模型请求"; body = modelDetail(request);
    } else if (target.type === "tool") {
      const tool = safeArray(inspection().tools).find((item) => item.id === target.id);
      if (!tool) return;
      nodes.detailTitle.textContent = `工具 · ${tool.name}`; body = toolDetail(tool);
    } else if (target.type === "context") {
      const context = safeArray(inspection().contexts).find((item) => item.event_id === target.id);
      if (!context) return;
      nodes.detailTitle.textContent = "Context 快照"; body = contextDetail(context);
    } else if (target.type === "iteration") {
      const iteration = safeArray(inspection().iterations).find((item) => item.id === target.id);
      if (!iteration) return;
      nodes.detailTitle.textContent = `Iteration ${iteration.index}`; body = detailSection("轮次摘要", kv([["状态", statusLabel(iteration.outcome)], ["来源", sourceLabel(iteration.source)], ["事件数", iteration.events?.length], ["耗时", duration(iteration.duration_ms)], ["模型请求", iteration.model_request_ids], ["工具调用", iteration.tool_call_ids]]));
    }
    nodes.detailBody.innerHTML = body; nodes.detailDrawer.classList.add("is-open");
  }

  function renderAll() { renderRuns(); renderHeader(); renderTabs(); renderView(); renderDetail(); }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(`本地接口 HTTP ${response.status}`);
    return response.json();
  }

  function chooseRun(id, keepFollow = false) {
    if (!id || state.runId === id && state.inspection) return;
    state.runId = id; state.version += 1; state.inspection = null; state.error = ""; state.detail = null;
    state.rawEvents = []; state.rawOffset = 0; state.rawMore = false; state.rawLoadedFor = "";
    if (!keepFollow) state.follow = false;
    renderAll();
  }

  async function loadRawEvents(id, version) {
    if (state.rawLoadedFor === id && !state.rawMore) return;
    let more = state.rawLoadedFor === id ? state.rawMore : true;
    while (more && state.version === version && state.rawEvents.length < 12000) {
      const page = await getJson(`/api/runs/${encodeURIComponent(id)}/events?offset=${state.rawOffset}`);
      if (state.version !== version) return;
      if (page.reset) { state.rawEvents = []; state.rawOffset = 0; }
      const incoming = safeArray(page.events).filter((event) => event && typeof event === "object");
      state.rawEvents.push(...incoming);
      const next = number(page.next_offset);
      if (next === null || next < state.rawOffset || page.has_more && next === state.rawOffset && !page.reset) throw new Error("日志读取未取得进展");
      state.rawOffset = next; more = Boolean(page.has_more); state.rawMore = more;
      if (!incoming.length && more) break;
    }
    state.rawLoadedFor = id;
  }

  async function loadSelected() {
    if (!state.runId || state.loading) return;
    const id = state.runId; const version = state.version; state.loading = true;
    try {
      const data = await getJson(`/api/runs/${encodeURIComponent(id)}/inspection`);
      if (state.version !== version) return;
      state.inspection = data; state.error = "";
      const raw = data.raw?.events || []; const last = raw[raw.length - 1];
      const fingerprint = `${data.stats?.event_count || raw.length}|${last?.event_id || last?.created_at || ""}|${data.run?.status || ""}|${data.run?.final_answer || ""}`;
      const changed = fingerprint !== state.fingerprint; state.fingerprint = fingerprint;
      if (state.view === "raw" && (changed || state.rawLoadedFor !== id)) await loadRawEvents(id, version);
      renderHeader(); renderRuns(); renderTabs(); if (changed || state.view === "raw") renderView(); renderDetail();
      connection(state.follow ? "实时跟随中" : "保持当前运行");
    } catch (error) {
      if (state.version !== version) return;
      state.error = error.message || "无法读取运行检查数据"; connection(`${state.error} · 将自动重试`, true); if (!state.inspection) renderAll();
    } finally { if (state.version === version) state.loading = false; }
  }

  let syncing = null;
  function synchronize() {
    if (syncing) return syncing;
    syncing = (async () => {
      try {
        const data = await getJson("/api/runs"); const runs = safeArray(data.runs).filter((item) => item && typeof item.id === "string");
        const previous = state.runId; const listChanged = JSON.stringify(runs) !== JSON.stringify(state.runs) || data.total !== state.total || !state.loaded;
        state.runs = runs; state.total = number(data.total) ?? runs.length; state.loaded = true;
        if ((!state.runId || state.follow) && runs.length) chooseRun(runs[0].id, true);
        if (listChanged || previous !== state.runId) renderRuns();
        if (state.runId) await loadSelected(); else connection("已连接 · 等待运行");
      } catch (error) { state.loaded = false; state.error = error.message || "无法读取运行列表"; connection(`${state.error} · 将自动重试`, true); if (!state.runs.length) renderRuns(); }
    })().finally(() => { syncing = null; });
    return syncing;
  }

  document.addEventListener("click", (event) => {
    const view = event.target.closest("[data-view]");
    if (view) { state.view = view.dataset.view; if (state.view === "raw" && state.runId) void loadSelected(); renderTabs(); renderView(); return; }
    const runButton = event.target.closest("[data-run-id]");
    if (runButton) { chooseRun(runButton.dataset.runId); renderAll(); void loadSelected(); return; }
    const eventButton = event.target.closest("[data-event-id]");
    if (eventButton) { state.detail = { type: "event", id: eventButton.dataset.eventId }; renderView(); renderDetail(); return; }
    const modelButton = event.target.closest("[data-model-id]");
    if (modelButton) { state.detail = { type: "model", id: modelButton.dataset.modelId }; renderView(); renderDetail(); return; }
    const toolButton = event.target.closest("[data-tool-id]");
    if (toolButton) { state.detail = { type: "tool", id: toolButton.dataset.toolId }; renderView(); renderDetail(); return; }
    const contextButton = event.target.closest("[data-context-id]");
    if (contextButton) { state.detail = { type: "context", id: contextButton.dataset.contextId }; renderView(); renderDetail(); return; }
    const filterButton = event.target.closest("[data-tool-filter]");
    if (filterButton) { state.toolFilter = filterButton.dataset.toolFilter; renderView(); return; }
    const rawFilter = event.target.closest("[data-raw-filter]");
    if (rawFilter) { state.rawFilter = rawFilter.dataset.rawFilter; renderView(); return; }
    const copy = event.target.closest("[data-copy-id]");
    if (copy) { const value = state.copyPayloads.get(copy.dataset.copyId); if (value !== undefined && navigator.clipboard) navigator.clipboard.writeText(value).then(() => { copy.textContent = "已复制"; setTimeout(() => { copy.textContent = "复制"; }, 900); }); return; }
    if (event.target.closest("#closeDetail")) { state.detail = null; renderView(); renderDetail(); }
  });

  document.addEventListener("change", (event) => {
    const contextSelect = event.target.closest("[data-context-select]");
    if (contextSelect) { if (contextSelect.dataset.contextSelect === "a") state.contextA = contextSelect.value; else state.contextB = contextSelect.value; renderView(); }
  });
  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-tool-search]")) { state.toolQuery = event.target.value; renderView(); }
    if (event.target.matches("[data-raw-search]")) { state.rawQuery = event.target.value; renderView(); }
  });
  nodes.runSearch.addEventListener("input", renderRuns);
  nodes.runStatus.addEventListener("change", renderRuns);
  nodes.refresh.addEventListener("click", () => { void synchronize(); });
  nodes.follow.addEventListener("click", () => { state.follow = !state.follow; renderRuns(); connection(state.follow ? "实时跟随中" : "保持当前运行"); if (state.follow) void synchronize(); });

  renderAll();
  void synchronize();
  setInterval(() => { void synchronize(); }, 1400);
})();
