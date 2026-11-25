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
    runs: [], total: 0, loaded: false, runId: "", version: 0, inspection: null, eventById: new Map(),
    view: "overview", follow: true, error: "", fingerprint: "", inflight: null,
    detail: null, detailKey: "",
    rawFilter: "all", rawQuery: "", toolFilter: "all", toolQuery: "",
    contextA: "", contextB: "",
    openIterations: new Set(), iterationTouched: false,
    copyPayloads: new Map(), copySequence: 0,
  };

  const STATUS = {
    running: "进行中", pending: "待开始", unknown: "未知", completed: "已完成", stopped: "已停止",
    failed: "失败", error: "失败", ok: "成功", rejected: "已拒绝", skipped: "已跳过", partial_success: "部分成功",
    incomplete: "未完成", final: "最终回答", tool: "工具调用", retry: "重试", tool_error: "工具失败",
    tool_rejected: "工具被拒绝", model_failed: "模型失败", context_failed: "上下文失败",
    finalization_tool_rejected: "收尾阶段拒绝工具", responded: "已响应", sent: "已发送", requested: "已发起",
  };
  const CATEGORY = { lifecycle: "生命周期", context: "上下文", model: "模型", decision: "操作判定", tools: "工具", recovery: "恢复", evaluation: "评测", other: "其他" };
  const EVENT_TITLES = {
    run_started: "收到用户请求", recovery_reconciled: "恢复对账", iteration_started: "开始执行轮次",
    prompt_built: "组装上下文", prompt_rendered: "生成本地 Prompt", finalization_requested: "进入收尾阶段",
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
  const eventCategory = (event) => event?.category || "other";
  const eventTitle = (event) => EVENT_TITLES[event?.event] || event?.event || "未知事件";
  const sourceLabel = (value) => value === "trace" ? "Trace 记录" : value === "viewer_inferred" ? "Viewer 推导" : "未知来源";
  const selectedRun = () => state.runs.find((run) => run.id === state.runId) || {};
  const inspection = () => state.inspection || {};
  const run = () => inspection().run || {};
  const stats = () => inspection().stats || {};
  const events = () => inspection().raw?.events || [];
  const safeArray = (value) => Array.isArray(value) ? value : [];
  const terminal = (value) => ["completed", "failed", "error", "stopped"].includes(value);
  const lookupEvent = (id) => id ? state.eventById.get(id) || null : null;
  const eventsOf = (ids) => safeArray(ids).map(lookupEvent).filter(Boolean);

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

  // 旧渲染产生的复制载荷不再对应任何按钮，及时释放，避免长期运行时无限增长。
  function pruneCopyPayloads() {
    const present = new Set([...document.querySelectorAll("[data-copy-id]")].map((node) => node.dataset.copyId));
    for (const key of state.copyPayloads.keys()) if (!present.has(key)) state.copyPayloads.delete(key);
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

  function noticeBanner(message) {
    return message ? `<div class="notice-banner">${escapeHtml(message)}</div>` : "";
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

  function usageNote(usage) {
    if (!usage || usage.status === "unknown") return "日志未记录实际 Token";
    const parts = [`输入 ${usage.input_tokens ?? "未知"} · 输出 ${usage.output_tokens ?? "未知"}`];
    if (usage.status === "partial") parts.push(usage.scope === "last_request" ? "仅最后请求" : `仅 ${usage.calls_with_usage}/${usage.calls_total} 次调用`);
    return parts.join(" · ");
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
    nodes.traceNote.textContent = stats().trace_truncated
      ? "Trace 超出读取上限，仅展示前段记录"
      : current.duration_source === "viewer_estimate" ? "耗时为 Viewer 根据已记录事件估算"
        : current.duration_source === "unknown" ? "结束时间未记录" : "";

    const usage = stats().usage || {};
    const context = stats().context || {};
    const toolNote = stats().tool_requests_recorded
      ? `成功 ${stats().tool_succeeded ?? 0} · 失败 ${stats().tool_failed ?? 0} · 拒绝 ${stats().tool_rejected ?? 0} · 跳过 ${stats().tool_skipped ?? 0}`
      : `成功 ${stats().tool_succeeded ?? 0} · 失败 ${stats().tool_failed ?? 0} · 请求事件未单独记录`;
    nodes.metricGrid.innerHTML = [
      metric("逻辑模型调用", state.runId ? stats().model_calls ?? "未知" : "—", stats().http_attempts_known ? `HTTP 实际发送 ${stats().http_attempts}` : "HTTP 发送未单独记录", true),
      metric("工具调用", state.runId ? stats().tool_calls ?? "未知" : "—", state.runId ? toolNote : "含拒绝、跳过与失败"),
      metric("Token 用量", usage.total_tokens === null || usage.total_tokens === undefined ? "未知" : usage.total_tokens.toLocaleString("zh-CN"), usage.status === "complete" ? usageNote(usage) : usage.status === "partial" ? `部分记录 · ${usageNote(usage)}` : "日志未记录实际 Token"),
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
    if (name === "prompt_built") { const metadata = event.prompt_metadata || {}; return `${metadata.prompt_chars ?? "未知"} / ${metadata.prompt_budget_chars ?? "未知"} 字符 · 压缩 ${safeArray(metadata.budget_reductions).length} 次 · 工具反馈 ${metadata.history_tool_results ?? "未知"} 条在 History`; }
    if (name === "prompt_rendered") return `${event.tool_protocol || "未知"} 协议 · 本地渲染 Prompt（Provider 实际入参见 HTTP 请求体）`;
    if (name === "model_requested") return `第 ${event.attempts ?? "未知"} 轮 · 已用工具 ${event.tool_steps ?? "未知"} 次`;
    if (name.startsWith("model_http_")) return name === "model_http_response" ? `HTTP ${event.status ?? "未知"} · 第 ${event.attempt ?? "未知"} 次发送` : name === "model_http_error" ? short(event.error || "HTTP 异常") : `第 ${event.attempt ?? "未知"} 次发送`;
    if (name === "model_extracted") return `${event.format || "未知"} 协议 · 解析前原始响应`;
    if (name === "model_parsed") return event.kind === "tool" ? `请求 ${event.tool_name || "未知工具"}` : event.kind === "final" ? "返回最终回答" : event.kind === "retry" ? "Harness 要求重试" : text(event.kind || "未记录类型");
    if (name === "tool_requested") return `${event.name || "未知工具"} · 模型请求工具`;
    if (name === "tool_stage") return `${event.name || "未知工具"} · ${TOOL_STAGES[event.stage] || event.stage || "未知阶段"}`;
    if (name === "tool_executed") return `${event.name || "未知工具"} · ${statusLabel(event.tool_status)}${event.tool_error_code ? ` · ${event.tool_error_code}` : ""}${event.recovery_action ? ` · ${event.recovery_action}` : ""}`;
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
    return `${noticeBanner(stats().trace_truncated ? "Trace 超过 12,000 条或 32 MiB 读取上限，仅展示已读取的前段记录。" : "")}<div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>用户任务</h2><span class="tag">Run scope</span></div><div class="subpanel-body"><div class="request-block"><div class="block-label"><span>原始请求</span>${copyButton(current.user_request || "")}</div><div class="block-content">${escapeHtml(current.user_request || "未采集。详细正文取决于运行时采集开关。")}</div></div><div class="answer-block mt-55"><div class="block-label"><span>Agent 最终回答 · 不等于独立验收</span>${copyButton(finalAnswer)}</div><div class="block-content">${escapeHtml(finalAnswer)}</div></div></div></div><div class="subpanel"><div class="subpanel-heading"><h2>证据覆盖</h2><span class="tag">实际记录</span></div><div class="subpanel-body"><div class="section-grid">${coverage.map(([label, value, known]) => `<div class="section-card${known ? " is-protected" : ""}"><strong>${escapeHtml(label)}</strong><div class="section-stats"><span>${escapeHtml(value)}</span><span>${known ? "可核对" : "未知"}</span></div></div>`).join("")}</div><dl class="kv-list mt-75">${[["开始", dateTime(current.started_at)], ["结束", current.finished_at ? dateTime(current.finished_at) : "未记录"], ["停止原因", current.stop_reason || "未知"], ["Trace schema", current.trace_schema || "未知"]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div><div class="subpanel"><div class="subpanel-heading"><h2>关键里程碑</h2><span class="count-badge">${recent.length}</span></div><div class="subpanel-body">${recent.length ? milestoneList(recent) : `<div class="empty-state"><strong>暂无里程碑</strong><span>这份运行还没有可展示的关键事件。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>执行摘要</h2><span class="tag">Summary</span></div><div class="subpanel-body"><dl class="kv-list">${[["执行轮次", stats().iterations ?? "未知"], ["模型重试", stats().model_retries ?? "未知"], ["检查点", stats().checkpoints ?? "未知"], ["事件总数", stats().event_count ?? "未知"], ["Trace 截断", stats().trace_truncated ? "是" : "否"], ["独立 Verifier", evaluation.status === "recorded" ? "已记录" : "未知"]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div></div>`;
  }

  function flowHtml() {
    const available = state.inspection ? ["context", "model", "decision", "tools", "context"].map((category) => events().some((event) => eventCategory(event) === category)) : [];
    const steps = [["用户请求", true], ["Context", available[0]], ["Model", available[1]], ["Decision", available[2]], ["Tool / Result", available[3]], ["下一轮 Context", available[4]]];
    return `<div class="flow">${steps.map(([label, active], index) => `${index ? `<span class="flow-arrow">→</span>` : ""}<span class="flow-step${active ? " is-active" : ""}">${escapeHtml(label)}</span>`).join("")}</div>`;
  }

  function iterationTitle(iteration) {
    if (iteration.outcome === "final") return "模型返回最终回答";
    if (iteration.outcome === "retry") return "模型输出需要重试";
    if (iteration.outcome === "model_failed") return "模型请求失败";
    if (iteration.outcome === "context_failed") return "上下文构建失败";
    if (iteration.outcome === "tool_error") return "工具执行失败";
    if (iteration.outcome === "tool_rejected") return "工具请求被拒绝";
    if (iteration.outcome === "stopped") return "达到停止条件";
    if (iteration.tool_names?.length) return `执行 ${iteration.tool_names.join("、")}`;
    return iteration.model_kind === "tool" ? "请求工具" : "模型决策进行中";
  }

  // 自动刷新会重建 DOM，这里在重建前记录用户的展开状态、滚动位置和输入焦点。
  function captureViewState() {
    const active = document.activeElement;
    let focusKey = "";
    if (active && nodes.viewRoot.contains(active)) {
      if (active.hasAttribute("data-tool-search")) focusKey = "tool-search";
      else if (active.hasAttribute("data-raw-search")) focusKey = "raw-search";
      else if (active.hasAttribute("data-context-select")) focusKey = `context-select-${active.dataset.contextSelect}`;
    }
    const detailNodes = [...nodes.viewRoot.querySelectorAll("details[data-iteration-id]")];
    const open = detailNodes.filter((item) => item.open).map((item) => item.dataset.iterationId);
    // 已有轮次 DOM 时以它为准同步展开集合，用户收起后不会被自动刷新重新打开。
    if (detailNodes.length) state.openIterations = new Set(open);
    return {
      view: state.view, scroll: nodes.viewRoot.scrollTop, windowScroll: window.scrollY, focusKey,
      start: active?.selectionStart ?? null, end: active?.selectionEnd ?? null,
    };
  }

  function restoreViewState(saved) {
    if (saved.view === state.view && saved.scroll) nodes.viewRoot.scrollTop = saved.scroll;
    if (saved.view === state.view && saved.windowScroll) window.scrollTo(0, saved.windowScroll);
    if (!saved.focusKey) return;
    const selector = saved.focusKey === "tool-search" ? "[data-tool-search]"
      : saved.focusKey === "raw-search" ? "[data-raw-search]"
        : `[data-context-select="${saved.focusKey.split("-").pop()}"]`;
    const element = nodes.viewRoot.querySelector(selector);
    if (!element) return;
    element.focus({ preventScroll: true });
    if (saved.start !== null && typeof element.setSelectionRange === "function") {
      try { element.setSelectionRange(saved.start, saved.end); } catch { /* select 元素没有文本选区 */ }
    }
  }

  function executionView() {
    const list = safeArray(inspection().iterations);
    if (!list.length) return `<div class="empty-panel"><strong>无法建立轮次</strong><span>旧 Trace 缺少模型请求或轮次证据，原始事件仍可在 Raw Trace 查看。</span></div>`;
    return `${flowHtml()}<div class="toolbar mt-65"><span class="label">按 Agent Loop 轮次组织</span><span class="tag">${list.length} iterations</span><span class="source-note">缺少显式 ID 的旧日志会标记为 Viewer 推导</span></div><div class="iterations">${list.map((iteration, index) => {
      const iterationEvents = eventsOf(iteration.event_ids);
      const open = state.openIterations.has(iteration.id) || (!state.iterationTouched && !state.detail && index === list.length - 1);
      const statusClass = iteration.status === "failed" ? "is-error" : iteration.status === "completed" ? (iteration.tools_rejected ? "is-warn" : "is-ok") : "is-warn";
      return `<details class="iteration-card" data-iteration-id="${escapeHtml(iteration.id)}"${open ? " open" : ""}><summary class="iteration-summary"><span class="iteration-number">I${escapeHtml(iteration.index)}</span><span class="iteration-title"><strong>${escapeHtml(iterationTitle(iteration))}</strong><span>${escapeHtml(iteration.source === "viewer_inferred" ? "Viewer 推导轮次" : "Trace 记录轮次")} · ${escapeHtml(iterationEvents.length)} 条事件</span></span><span class="iteration-meta"><span class="status-pill ${statusClass}">${escapeHtml(statusLabel(iteration.outcome))}</span><span>${escapeHtml(duration(iteration.duration_ms))}</span></span></summary><div class="iteration-body"><div class="event-list">${iterationEvents.map((event) => eventRow(event, state.detail?.type === "event" && state.detail.id === event.event_id)).join("")}</div></div></details>`;
    }).join("")}</div>`;
  }

  function budgetMeter(used, budget, over) {
    const percent = budget ? Math.min(100, Number(used || 0) / Number(budget) * 100) : 0;
    return `<progress class="budget-meter${over ? " is-over" : ""}" max="100" value="${percent.toFixed(1)}" aria-label="上下文预算使用比例"></progress>`;
  }

  function contextCard(context, selected) {
    const sections = context.sections || {};
    const order = context.section_order?.length ? context.section_order : Object.keys(sections);
    return `<button type="button" class="inspection-card clickable card-button${selected ? " is-selected" : ""}" data-context-id="${escapeHtml(context.event_id || "")}"><div class="card-top"><div><div class="card-title">${escapeHtml(context.iteration_id || "上下文快照")}</div><div class="card-subtitle">序号 ${escapeHtml(context.sequence ?? "未知")} · ${escapeHtml(context.detail_available ? "含本地渲染 Prompt" : "仅有元数据")}</div></div><div class="card-badges"><span class="tag">${escapeHtml(context.prompt_chars ?? "未知")} chars</span><span class="tag">${escapeHtml(context.token_estimate ?? "未知")} tokens 估算</span></div></div><div class="mt-60">${budgetMeter(context.prompt_chars, context.prompt_budget_chars, context.prompt_over_budget)}<div class="budget-legend"><span>${escapeHtml(context.prompt_chars ?? "未知")} / ${escapeHtml(context.prompt_budget_chars ?? "未知")} 字符</span><span>${escapeHtml(safeArray(context.budget_reductions).length)} 次压缩</span></div></div><div class="section-stats mt-55">${order.slice(0, 6).map((name) => `<span>${escapeHtml(name)} ${escapeHtml(sections[name]?.rendered_chars ?? "未知")}</span>`).join("")}</div></button>`;
  }

  function promptOf(context) {
    return text(lookupEvent(context?.prompt_event_id)?.prompt);
  }

  function lineDiff(before, after) {
    if (before === after) return { text: "", skipped: false, truncated: false };
    const a = before.split("\n");
    const b = after.split("\n");
    // 文本差异是 Viewer 的计算结果；超长时明确跳过，避免阻塞界面。
    if (a.length + b.length > 4000) return { text: "", skipped: true, truncated: false };
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
    let aEnd = a.length;
    let bEnd = b.length;
    while (aEnd > start && bEnd > start && a[aEnd - 1] === b[bEnd - 1]) { aEnd -= 1; bEnd -= 1; }
    const midA = a.slice(start, aEnd);
    const midB = b.slice(start, bEnd);
    if (midA.length * midB.length > 360000) return { text: "", skipped: true, truncated: false };
    const table = Array.from({ length: midA.length + 1 }, () => new Uint16Array(midB.length + 1));
    for (let i = midA.length - 1; i >= 0; i -= 1) {
      for (let j = midB.length - 1; j >= 0; j -= 1) {
        table[i][j] = midA[i] === midB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    const output = a.slice(Math.max(0, start - 2), start).map((line) => `  ${line}`);
    let i = 0;
    let j = 0;
    while (i < midA.length && j < midB.length) {
      if (midA[i] === midB[j]) { output.push(`  ${midA[i]}`); i += 1; j += 1; }
      else if (table[i + 1][j] >= table[i][j + 1]) { output.push(`- ${midA[i]}`); i += 1; }
      else { output.push(`+ ${midB[j]}`); j += 1; }
    }
    while (i < midA.length) output.push(`- ${midA[i++]}`);
    while (j < midB.length) output.push(`+ ${midB[j++]}`);
    output.push(...a.slice(aEnd, Math.min(a.length, aEnd + 2)).map((line) => `  ${line}`));
    const truncated = output.length > 240;
    return { text: output.slice(0, 240).join("\n"), skipped: false, truncated };
  }

  function contextDiff(first, second) {
    const beforeSections = first.sections || {};
    const afterSections = second.sections || {};
    const names = [...new Set([...(first.section_order || []), ...(second.section_order || []), ...Object.keys(beforeSections), ...Object.keys(afterSections)])];
    const sections = [];
    for (const name of names) {
      const before = beforeSections[name] || {};
      const after = afterSections[name] || {};
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        sections.push({ name, before, after, delta: (number(after.rendered_chars) || 0) - (number(before.rendered_chars) || 0) });
      }
    }
    const recoveryChanged = JSON.stringify(first.recovery_decision || {}) !== JSON.stringify(second.recovery_decision || {});
    const textDiff = lineDiff(promptOf(first), promptOf(second));
    const sources = [];
    if (sections.length || recoveryChanged) sources.push("metadata");
    if (textDiff.text || textDiff.skipped) sources.push("text");
    return { sections, recoveryChanged, textDiff, sources };
  }

  function contextDiffHtml(first, second) {
    if (!first || !second) return `<div class="empty-state"><strong>选择两个轮次</strong><span>上下文差异需要两个实际采集的快照。</span></div>`;
    const diff = contextDiff(first, second);
    const rows = diff.sections.length
      ? `<table class="data-table mt-45"><thead><tr><th>Section</th><th>保留字符变化</th><th>依据</th></tr></thead><tbody>${diff.sections.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.delta > 0 ? `+${item.delta}` : item.delta)}</td><td>metadata</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty-state"><span>结构化元数据没有记录可见变化。</span></div>`;
    const recovery = diff.recoveryChanged
      ? `<div class="block-label mt-55"><span>Recovery 对账变化（Harness 记录）</span></div><pre class="payload">${jsonHtml({ before: first.recovery_decision || {}, after: second.recovery_decision || {} })}</pre>`
      : "";
    const textBlock = diff.textDiff.skipped
      ? `<div class="source-note mt-50">Prompt 行数过多，Viewer 跳过文本 Diff；结构化元数据仍可比较。</div>`
      : diff.textDiff.text
        ? `<pre class="payload">${escapeHtml(diff.textDiff.text)}</pre>${diff.textDiff.truncated ? `<div class="source-note">文本 Diff 已截断到 240 行。</div>` : ""}`
        : `<div class="source-note mt-50">两个快照的 Prompt 文本相同或未采集正文。</div>`;
    return `<div class="diff-box"><div class="card-subtitle">Viewer 计算的差异 · 来源 ${escapeHtml(diff.sources.join("+") || "none")}</div>${rows}${recovery}<div class="block-label mt-55"><span>Prompt 文本 Diff（Viewer 计算）</span></div>${textBlock}</div>`;
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
    const prompt = promptOf(second);
    return `${noticeBanner(stats().trace_truncated ? "Trace 被截断，快照可能不完整。" : "")}<div class="toolbar"><span class="label">选择任意两个快照比较</span><select class="select-input select-inline" data-context-select="a" aria-label="比较起点快照">${contexts.map((item) => `<option value="${escapeHtml(item.event_id)}"${item.event_id === first.event_id ? " selected" : ""}>${escapeHtml(item.iteration_id || item.event_id)}</option>`).join("")}</select><span class="muted">→</span><select class="select-input select-inline" data-context-select="b" aria-label="比较终点快照">${contexts.map((item) => `<option value="${escapeHtml(item.event_id)}"${item.event_id === second.event_id ? " selected" : ""}>${escapeHtml(item.iteration_id || item.event_id)}</option>`).join("")}</select></div><div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>Context 组成</h2><span class="tag">${escapeHtml(second.source || "未知来源")}</span></div><div class="subpanel-body">${budgetMeter(second.prompt_chars, second.prompt_budget_chars, second.prompt_over_budget)}<div class="budget-legend"><span>${escapeHtml(second.prompt_chars ?? "未知")} / ${escapeHtml(second.prompt_budget_chars ?? "未知")} 字符</span><span>Token 估算 ${escapeHtml(second.token_estimate ?? "未知")} · ${escapeHtml(second.token_estimate_method || "未知方法")}</span></div><table class="data-table mt-70"><thead><tr><th>Section</th><th>原始</th><th>保留</th><th>预算</th></tr></thead><tbody>${order.map((name) => { const item = sections[name] || {}; const trimmed = Number(item.raw_chars || 0) > Number(item.rendered_chars || 0); return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(item.raw_chars ?? "未知")}</td><td class="${trimmed ? "muted" : ""}">${escapeHtml(item.rendered_chars ?? "未知")}${trimmed ? " · 裁剪" : ""}</td><td>${escapeHtml(item.budget_chars ?? "保护/未知")}</td></tr>`; }).join("")}</tbody></table>${prompt ? `<details class="disclosure"><summary>本地渲染 Prompt（${escapeHtml(prompt.length)} 字符）</summary><pre class="payload">${escapeHtml(prompt)}</pre></details>` : `<span class="source-note">Prompt 正文未采集，当前只展示 Context 元数据。</span>`}<div class="source-note mt-50">本地渲染 Prompt 可能不是 Provider 实际入参；原生工具续接时请核对模型视图的 HTTP 请求体。</div></div></div><div class="subpanel"><div class="subpanel-heading"><h2>Context Diff</h2><span class="tag">${escapeHtml(first.iteration_id || "")} → ${escapeHtml(second.iteration_id || "")}</span></div><div class="subpanel-body">${contextDiffHtml(first, second)}</div></div></div><div class="subpanel mt-65"><div class="subpanel-heading"><h2>快照列表</h2><span class="count-badge">${contexts.length}</span></div><div class="subpanel-body">${contexts.map((item) => contextCard(item, item.event_id === second.event_id)).join("")}</div></div>`;
  }

  function pipeline(request) {
    const prompt = lookupEvent(request.prompt_event_id);
    const extracted = lookupEvent(request.extracted_event_id);
    const parsed = lookupEvent(request.parsed_event_id);
    const requested = lookupEvent(request.requested_event_id);
    const steps = [
      ["Context", !!prompt, prompt?.prompt ? "本地渲染 Prompt" : "元数据"],
      ["Provider", !!requested, requested ? "已请求" : "未记录"],
      ["HTTP", (request.http?.length || 0) > 0, `${request.http_sends || 0} 次发送`],
      ["Adapter", !!extracted, extracted?.format || "未记录"],
      ["Decision", !!parsed, parsed?.kind || "未记录"],
    ];
    return `<div class="pipeline">${steps.map(([label, done, note]) => `<div class="pipeline-step ${done ? "done" : ""}">${escapeHtml(label)}<small>${escapeHtml(note)}</small></div>`).join("")}</div>`;
  }

  function modelView() {
    const models = safeArray(inspection().models);
    if (!models.length) return `<div class="empty-panel"><strong>模型调用证据未记录</strong><span>当前 Trace 没有可关联的模型请求事件。</span></div>`;
    return `<div class="toolbar"><span class="label">按逻辑模型请求聚合</span><span class="tag">HTTP 重试不会被算作新轮次</span></div><div>${models.map((request) => {
      const parsed = lookupEvent(request.parsed_event_id);
      const requested = lookupEvent(request.requested_event_id);
      const statusClass = request.status === "failed" ? "is-error" : request.status === "final" ? "is-ok" : "is-warn";
      return `<button type="button" class="inspection-card clickable card-button" data-model-id="${escapeHtml(request.id)}"><div class="card-top"><div><div class="card-title">${escapeHtml(request.id)}</div><div class="card-subtitle">${escapeHtml(request.iteration_id || "未知轮次")} · ${escapeHtml(request.source === "viewer_inferred" ? "旧日志推导" : "Trace 关联")}</div></div><div class="card-badges"><span class="status-pill ${statusClass}">${escapeHtml(statusLabel(request.status))}</span><span class="tag">HTTP 发送 ${escapeHtml(request.http_sends || 0)}</span></div></div>${pipeline(request)}<div class="card-subtitle mt-55">${escapeHtml(parsed ? eventSummary(parsed) : requested ? "等待模型响应" : "模型请求字段缺失")}</div></button>`;
    }).join("")}</div>`;
  }

  function toolView() {
    const tools = safeArray(inspection().tools);
    const filtered = tools.filter((tool) => (!state.toolQuery || `${tool.name} ${tool.id} ${tool.args_preview}`.toLowerCase().includes(state.toolQuery.toLowerCase())) && (state.toolFilter === "all" || tool.status === state.toolFilter));
    if (!tools.length) return `<div class="empty-panel"><strong>工具调用证据未记录</strong><span>基础 Trace 可能只保留工具计数，详细工具阶段需要 Trace detail。</span></div>`;
    return `<div class="toolbar"><input class="search-input" data-tool-search type="search" value="${escapeHtml(state.toolQuery)}" name="tool-search" aria-label="搜索工具" placeholder="搜工具、调用 ID 或参数"><button type="button" class="filter-button${state.toolFilter === "all" ? " is-active" : ""}" data-tool-filter="all">全部</button>${["ok", "error", "rejected", "skipped", "partial_success", "unknown"].map((filter) => `<button type="button" class="filter-button${state.toolFilter === filter ? " is-active" : ""}" data-tool-filter="${filter}">${escapeHtml(statusLabel(filter))}</button>`).join("")}<span class="tag">${filtered.length} / ${tools.length}</span></div><div>${filtered.map((tool) => `<button type="button" class="inspection-card clickable card-button" data-tool-id="${escapeHtml(tool.id)}"><div class="card-top"><div><div class="card-title">${escapeHtml(tool.name)}</div><div class="card-subtitle">${escapeHtml(tool.id)} · ${escapeHtml(tool.iteration_id || "未知轮次")}</div></div><div class="card-badges"><span class="status-pill ${tool.status === "ok" ? "is-ok" : tool.status === "rejected" || tool.status === "error" || tool.status === "skipped" ? "is-error" : "is-warn"}">${escapeHtml(statusLabel(tool.status))}</span>${tool.risk_level ? `<span class="tag">风险 ${escapeHtml(tool.risk_level)}</span>` : ""}</div></div><div class="section-stats mt-55"><span>${escapeHtml(tool.execution === "executed" ? "已执行" : tool.execution === "rejected" ? "已拒绝" : tool.execution === "skipped" ? "恢复跳过" : "仅请求")}</span><span>${escapeHtml(tool.read_only === true ? "只读" : tool.read_only === false ? "有副作用" : "读写未知")}</span><span>${escapeHtml(tool.workspace_changed === true ? "工作区已变化" : tool.workspace_changed === false ? "工作区未变化" : "变化未知")}</span><span>${escapeHtml(tool.affected_paths?.length || 0)} 个受影响路径</span></div><div class="card-subtitle mt-50">${escapeHtml(tool.recovery_action || tool.action_phase || tool.tool_error_code || "执行阶段未记录")}</div></button>`).join("") || `<div class="empty-state"><strong>没有匹配的工具调用</strong><span>调整筛选条件。</span></div>`}</div>`;
  }

  function recoveryView() {
    const recovery = inspection().recovery || {};
    const recoveryEvents = safeArray(recovery.events);
    const decision = recovery.decision || {};
    return `<div class="view-grid"><div class="subpanel"><div class="subpanel-heading"><h2>恢复决策</h2><span class="tag">${escapeHtml(decision.mode || "未记录")}</span></div><div class="subpanel-body">${decision && Object.keys(decision).length ? `<dl class="kv-list">${[["决定", decision.decision], ["恢复状态", decision.resume_status], ["原因", decision.reason], ["已对账", decision.reconciled_actions], ["可重试", decision.retryable_actions], ["跳过", decision.skipped_actions], ["人工复核", decision.manual_review_actions]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(jsonText(value || "未记录"))}</dd>`).join("")}</dl>` : `<div class="empty-state"><strong>没有恢复决策</strong><span>这份运行没有记录恢复协调证据。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>Action Journal / Checkpoint</h2><span class="tag">只读证据</span></div><div class="subpanel-body"><dl class="kv-list"><dt>Checkpoint</dt><dd>${escapeHtml(recovery.checkpoint_id || "未记录")}</dd><dt>Journal</dt><dd>${escapeHtml(recovery.journal ? "已记录" : "未记录")}</dd></dl>${recovery.journal ? `<pre class="payload">${jsonHtml(recovery.journal)}</pre>` : ""}</div></div></div><div class="subpanel mt-65"><div class="subpanel-heading"><h2>恢复相关事件</h2><span class="count-badge">${recoveryEvents.length}</span></div><div class="subpanel-body">${recoveryEvents.length ? milestoneList(recoveryEvents) : `<div class="empty-state"><span>没有 Recovery / Checkpoint 事件。</span></div>`}</div></div>`;
  }

  function evaluationView() {
    const evaluation = inspection().evaluation || {};
    const usage = stats().usage || {};
    return `<div class="view-grid equal"><div class="subpanel"><div class="subpanel-heading"><h2>独立验收</h2><span class="status-pill ${evaluation.status === "recorded" ? "is-ok" : "is-warn"}">${escapeHtml(evaluation.status === "recorded" ? "已记录" : "未知")}</span></div><div class="subpanel-body">${evaluation.status === "recorded" ? `<div class="card-subtitle">来源 ${escapeHtml(evaluation.source)}</div><pre class="payload">${jsonHtml(evaluation.evidence)}</pre>` : `<div class="empty-state"><strong>独立 Verifier 结果未知</strong><span>Agent 的最终回答与独立验收状态分开处理。当前 report 没有 verifier 或 evaluation 字段。</span></div>`}</div></div><div class="subpanel"><div class="subpanel-heading"><h2>运行指标</h2><span class="tag">当前 Run</span></div><div class="subpanel-body"><dl class="kv-list">${[["成功状态", statusLabel(run().status || "unknown")], ["模型调用", stats().model_calls], ["HTTP 发送", stats().http_attempts_known ? stats().http_attempts : "未知"], ["工具调用", stats().tool_calls], ["Token", usage.status === "unknown" ? "未知" : `${usage.total_tokens ?? "未知"}（${usage.status === "complete" ? "完整" : "部分"}）`], ["耗时", duration(run().duration_ms)]].map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></div></div></div><div class="subpanel mt-65"><div class="subpanel-heading"><h2>评测数据边界</h2><span class="tag">Roadmap S5</span></div><div class="subpanel-body"><p class="card-subtitle">Viewer 只识别已有 report 中的评测证据，不重写 Evaluator，也不会把 Agent 自报完成推断为独立通过。缺失字段显示为未知。</p></div></div>`;
  }

  function rawView() {
    const source = events();
    const filtered = source.filter((event) => (!state.rawQuery || jsonText(event).toLowerCase().includes(state.rawQuery.toLowerCase())) && (state.rawFilter === "all" || eventCategory(event) === state.rawFilter));
    const shown = filtered.slice(-350);
    const truncated = stats().trace_truncated;
    return `${noticeBanner(truncated ? `Trace 超过读取上限（12,000 条 / 32 MiB），当前仅展示已读取的事件；被跳过的损坏记录：${stats().invalid_events_skipped ?? 0} 条。` : "")}<div class="toolbar"><input class="search-input" data-raw-search type="search" value="${escapeHtml(state.rawQuery)}" name="raw-search" aria-label="搜索原始事件" placeholder="搜索事件、字段或内容"><button type="button" class="filter-button${state.rawFilter === "all" ? " is-active" : ""}" data-raw-filter="all">全部</button>${["lifecycle", "context", "model", "decision", "tools", "recovery", "evaluation", "other"].map((filter) => `<button type="button" class="filter-button${state.rawFilter === filter ? " is-active" : ""}" data-raw-filter="${filter}">${escapeHtml(CATEGORY[filter])}</button>`).join("")}<span class="tag">${shown.length} / ${filtered.length}</span></div>${source.length > shown.length ? `<div class="source-note">当前视图只渲染最近 ${shown.length} 条；筛选作用于全部已读取事件。</div>` : ""}<div class="subpanel mt-60"><div class="subpanel-heading"><h2>完整原始事件</h2><span class="tag">JSONL 顺序 · 已含 Viewer 推导 ID</span></div><div class="subpanel-body"><div class="event-list">${shown.map((event) => eventRow(event, state.detail?.type === "event" && state.detail.id === event.event_id)).join("") || `<div class="empty-state"><strong>没有匹配事件</strong><span>调整搜索条件。</span></div>`}</div></div></div>`;
  }

  function renderView() {
    const saved = captureViewState();
    if (!state.runId || !state.inspection) {
      nodes.viewRoot.innerHTML = `<div class="empty-panel"><strong>${state.error ? "加载运行失败" : "选择一条运行"}</strong><span>${escapeHtml(state.error || "左侧运行列表会显示当前工作区的 Page 工件。")}</span></div>`;
    } else {
      const renderer = { overview: overviewView, execution: executionView, context: contextView, model: modelView, tools: toolView, recovery: recoveryView, evaluation: evaluationView, raw: rawView }[state.view];
      nodes.viewRoot.innerHTML = renderer ? renderer() : overviewView();
    }
    restoreViewState(saved);
    pruneCopyPayloads();
  }

  function detailSection(title, content) { return `<section class="detail-section"><h3>${escapeHtml(title)}</h3>${content}</section>`; }
  function kv(items) { return `<dl class="kv-list">${items.filter(([, value]) => value !== undefined && value !== null && value !== "").map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(typeof value === "string" ? value : jsonText(value))}</dd>`).join("")}</dl>`; }
  function payload(title, value, copy = true) { const rendered = jsonText(value); return `<div class="block-label"><span>${escapeHtml(title)}</span>${copy ? copyButton(rendered) : ""}</div><pre class="payload">${escapeHtml(rendered)}</pre>`; }

  function eventDetail(event) {
    const category = eventCategory(event);
    let body = detailSection("关联身份", kv([["事件", event.event], ["类别", CATEGORY[category] || category], ["时间", dateTime(event.created_at)], ["序号", event.event_seq], ["Iteration", event.iteration_id], ["Model request", event.model_request_id], ["Tool call", event.tool_call_id], ["来源", sourceLabel(event.iteration_source)]]));
    if (event.event === "run_started") body += detailSection("用户请求", payload("请求正文", event.user_request));
    if (event.event === "prompt_built") body += detailSection("Context 元数据", `${payload("prompt_metadata", event.prompt_metadata)}${event.prompt_metadata?.history_tool_call_ids?.length ? payload("进入本轮的 History 工具调用", event.prompt_metadata.history_tool_call_ids, false) : ""}`);
    if (event.event === "prompt_rendered") body += detailSection("本地渲染 Prompt", `${payload("Prompt", event.prompt)}<div class="source-note">这是本地拼接文本。原生工具续接时，Provider 实际入参可能只包含工具结果，请以 HTTP 请求体为准。</div>`);
    if (["model_http_request", "model_http_response"].includes(event.event)) body += detailSection(event.event === "model_http_request" ? "实际 HTTP 请求体（Provider 入参）" : "原始 HTTP 响应", `${kv([["接口", event.url], ["HTTP 状态", event.status], ["发送次数", event.attempt]])}${payload("正文", event.body)}`);
    if (["model_http_error", "model_failed", "context_failed"].includes(event.event)) body += detailSection("错误", `${kv([["错误类型", event.error_type], ["错误代码", event.error_code], ["接口", event.url], ["发送次数", event.attempt]])}${payload("错误信息", event.error || "未记录")}`);
    if (event.event === "model_extracted") body += detailSection("Adapter 提取结果", `${payload("文本", event.text)}${event.tool_calls?.length ? payload("原生 Tool Calls", event.tool_calls) : ""}`);
    if (event.event === "model_parsed") body += detailSection("Harness 操作判定", `${kv([["判定类型", event.kind], ["工具", event.tool_name], ["耗时", duration(event.duration_ms)]])}${Object.hasOwn(event, "payload") ? payload("解析载荷", event.payload) : payload("回答预览", event.answer_preview || "未采集")}${event.completion_metadata ? payload("用量与缓存", event.completion_metadata) : ""}`);
    if (["tool_requested", "tool_stage", "tool_executed"].includes(event.event)) body += detailSection("工具生命周期", `${kv([["工具", event.name], ["阶段", TOOL_STAGES[event.stage] || event.stage], ["状态", statusLabel(event.tool_status)], ["审批", event.approval], ["风险", event.risk_level], ["只读", event.read_only], ["工作区变化", event.workspace_changed], ["错误代码", event.tool_error_code], ["恢复动作", event.recovery_action], ["Action ID", event.action_id], ["Action phase", event.action_phase]])}${event.args ? payload("参数", event.args) : ""}${Object.hasOwn(event, "result") ? payload(event.verbose ? "完整工具结果" : "工具结果预览", event.result) : ""}${event.affected_paths?.length ? payload("受影响路径", event.affected_paths) : ""}${event.diff_summary?.length ? payload("变更摘要", event.diff_summary) : ""}`);
    if (event.event === "recovery_reconciled") body += detailSection("恢复判定（Harness 记录）", payload("recovery_decision", event));
    if (event.event === "checkpoint_created") body += detailSection("检查点", kv([["Checkpoint ID", event.checkpoint_id], ["触发原因", event.trigger]]));
    if (event.event === "run_finished") body += detailSection("结束信息", `${kv([["状态", statusLabel(event.status)], ["停止原因", event.stop_reason], ["耗时", duration(event.run_duration_ms)]])}${payload("最终回答", event.final_answer || "未记录")}`);
    body += `<details class="disclosure"><summary>全部原始字段</summary>${payload("JSON", event, false)}</details>`;
    return body;
  }

  function modelDetail(request) {
    const requested = lookupEvent(request.requested_event_id);
    const prompt = lookupEvent(request.prompt_event_id);
    const extracted = lookupEvent(request.extracted_event_id);
    const parsed = lookupEvent(request.parsed_event_id);
    const failed = lookupEvent(request.failed_event_id);
    let body = detailSection("逻辑请求", kv([["请求 ID", request.id], ["Iteration", request.iteration_id], ["状态", statusLabel(request.status)], ["来源", sourceLabel(request.source)]]));
    body += detailSection("请求链路", pipeline(request));
    if (prompt) body += detailSection("本地渲染 Prompt", `${prompt.prompt ? payload("Prompt", prompt.prompt) : payload("Prompt 事件", prompt)}<div class="source-note">Provider 实际入参见下方 HTTP 请求体。</div>`);
    if (requested) body += detailSection("请求参数", payload("model_requested", requested));
    if (request.http?.length) body += detailSection("HTTP 发送（请求 / 响应 / 错误同一生命周期）", request.http.map((item) => {
      const requestEvent = lookupEvent(item.request_event_id);
      const responseEvent = lookupEvent(item.response_event_id);
      const errorEvent = lookupEvent(item.error_event_id);
      return `<div class="detail-section"><div class="card-title">attempt ${escapeHtml(item.attempt ?? "未知")}${item.status !== null && item.status !== undefined ? ` · HTTP ${escapeHtml(item.status)}` : ""}</div>${kv([["接口", item.url], ["实际发送", requestEvent ? "已记录" : "未记录"], ["响应", responseEvent ? "已记录" : "未记录"], ["错误", errorEvent ? errorEvent.error : ""]])}${requestEvent ? payload("请求体", requestEvent.body, false) : ""}${responseEvent ? payload("响应体", responseEvent.body, false) : ""}${errorEvent ? payload("错误", errorEvent.error || errorEvent, false) : ""}</div>`;
    }).join(""));
    if (extracted) body += detailSection("Adapter 提取", payload("model_extracted", extracted));
    if (parsed) body += detailSection("Harness 解析", payload("model_parsed", parsed));
    if (failed) body += detailSection("失败证据", payload("model_failed", failed));
    body += `<details class="disclosure"><summary>关联事件 ID</summary>${payload("event_ids", request.event_ids, false)}</details>`;
    return body;
  }

  function toolDetail(tool) {
    const request = lookupEvent(tool.request_event_id);
    const result = lookupEvent(tool.result_event_id);
    let body = detailSection("调用身份", kv([["工具", tool.name], ["调用 ID", tool.id], ["Iteration", tool.iteration_id], ["Model request", tool.model_request_id], ["来源", sourceLabel(tool.source)]]));
    body += detailSection("执行状态", kv([["状态", statusLabel(tool.status)], ["执行语义", tool.execution], ["风险等级", tool.risk_level], ["审批策略", tool.approval], ["只读", tool.read_only], ["工作区变化", tool.workspace_changed], ["错误代码", tool.tool_error_code], ["Action ID", tool.action_id], ["Action phase", tool.action_phase], ["恢复动作", tool.recovery_action]]));
    if (request) body += detailSection("模型原始请求", payload("参数", request.args || {}));
    if (tool.phase_event_ids?.length) body += detailSection("安全与执行阶段（Trace 记录）", eventsOf(tool.phase_event_ids).map((phase) => eventRow(phase, false)).join(""));
    if (result) body += detailSection("执行结果", `${payload("结果", result.result || "未记录")}${tool.affected_paths?.length ? payload("受影响路径", tool.affected_paths) : ""}${tool.diff_summary?.length ? payload("变更摘要", tool.diff_summary) : ""}`);
    body += `<details class="disclosure"><summary>关联事件 ID</summary>${payload("event_ids", tool.event_ids, false)}</details>`;
    return body;
  }

  function contextDetail(context) {
    const prompt = promptOf(context);
    return `${detailSection("上下文身份", kv([["Iteration", context.iteration_id], ["序号", context.sequence], ["来源", sourceLabel(context.source)], ["详情", context.detail_available ? "本地渲染 Prompt 已采集" : "只有元数据"]]))}${detailSection("预算", kv([["Prompt 字符", context.prompt_chars], ["字符预算", context.prompt_budget_chars], ["Token 估算", context.token_estimate], ["估算方法", context.token_estimate_method], ["超预算", context.prompt_over_budget ? "是" : "否"], ["压缩次数", context.budget_reductions?.length || 0]]))}${context.history_tool_call_ids?.length ? detailSection("本轮 History 中的工具反馈", payload("tool_call_ids", context.history_tool_call_ids, false)) : ""}${context.recovery_decision && Object.keys(context.recovery_decision).length ? detailSection("本轮 Recovery 对账（Harness 记录）", payload("recovery_decision", context.recovery_decision)) : ""}${prompt ? detailSection("本地渲染 Prompt", payload("Prompt", prompt)) : ""}${detailSection("结构化 Sections", payload("sections", context.sections))}`;
  }

  function renderDetail() {
    const target = state.detail;
    if (!target) {
      if (state.detailKey === "closed") return;
      state.detailKey = "closed";
      nodes.detailDrawer.classList.remove("is-open");
      nodes.detailTitle.textContent = "等待选择证据";
      nodes.detailBody.innerHTML = `<div class="empty-panel compact"><strong>选择一个步骤</strong><span>这里会展示实际采集的输入、判断、结果和原始字段。</span></div>`;
      return;
    }
    let body = "";
    let title = "";
    if (target.type === "event") {
      const event = lookupEvent(target.id);
      if (!event) return;
      title = eventTitle(event); body = eventDetail(event);
    } else if (target.type === "model") {
      const request = safeArray(inspection().models).find((item) => item.id === target.id);
      if (!request) return;
      title = "逻辑模型请求"; body = modelDetail(request);
    } else if (target.type === "tool") {
      const tool = safeArray(inspection().tools).find((item) => item.id === target.id);
      if (!tool) return;
      title = `工具 · ${tool.name}`; body = toolDetail(tool);
    } else if (target.type === "context") {
      const context = safeArray(inspection().contexts).find((item) => item.event_id === target.id);
      if (!context) return;
      title = "Context 快照"; body = contextDetail(context);
    } else if (target.type === "iteration") {
      const iteration = safeArray(inspection().iterations).find((item) => item.id === target.id);
      if (!iteration) return;
      title = `Iteration ${iteration.index}`; body = detailSection("轮次摘要", kv([["状态", statusLabel(iteration.outcome)], ["状态语义", iteration.status], ["来源", sourceLabel(iteration.source)], ["事件数", iteration.event_count], ["耗时", duration(iteration.duration_ms)], ["模型请求", iteration.model_request_ids], ["工具调用", iteration.tool_call_ids]]));
    }
    // 内容未变化时跳过 DOM 重建，避免滚动和复制按钮闪烁。
    const key = `${target.type}:${target.id}:${state.fingerprint}`;
    if (key === state.detailKey) return;
    state.detailKey = key;
    nodes.detailTitle.textContent = title;
    nodes.detailBody.innerHTML = body;
    nodes.detailDrawer.classList.add("is-open");
    pruneCopyPayloads();
  }

  function renderAll() { renderRuns(); renderHeader(); renderTabs(); renderView(); renderDetail(); }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(`本地接口 HTTP ${response.status}`);
    return response.json();
  }

  function resetRunState() {
    state.inspection = null; state.eventById = new Map(); state.error = ""; state.detail = null; state.detailKey = "";
    state.fingerprint = ""; state.contextA = ""; state.contextB = "";
    state.openIterations = new Set(); state.iterationTouched = false;
    state.rawFilter = "all"; state.rawQuery = ""; state.toolFilter = "all"; state.toolQuery = "";
  }

  function chooseRun(id, keepFollow = false) {
    if (!id) return;
    if (state.runId === id) {
      // 自动刷新不应该重建同一份页面，否则 uids、滚动和输入焦点都会抖动。
      if (!keepFollow) state.follow = false;
      return;
    }
    resetRunState();
    state.runId = id;
    state.version += 1;
    // 旧版本的请求由 loadSelected 的 version 检查丢弃，这里不阻塞新请求。
    state.inflight = null;
    if (!keepFollow) state.follow = false;
    renderAll();
  }

  async function loadSelected() {
    const id = state.runId;
    const version = state.version;
    if (!id) return null;
    if (state.inflight && state.inflight.version === version) return state.inflight.promise;
    const promise = (async () => {
      try {
        const data = await getJson(`/api/runs/${encodeURIComponent(id)}/inspection`);
        if (state.version !== version) return;
        state.inspection = data;
        state.eventById = new Map(safeArray(data.raw?.events).map((event) => [event.event_id, event]));
        state.error = "";
        const raw = data.raw?.events || [];
        const last = raw[raw.length - 1];
        const fingerprint = `${data.stats?.event_count || raw.length}|${last?.event_id || last?.created_at || ""}|${data.run?.status || ""}|${data.run?.final_answer || ""}|${data.raw?.truncated ? "t" : ""}`;
        const changed = fingerprint !== state.fingerprint;
        state.fingerprint = fingerprint;
        if (changed) {
          renderHeader(); renderRuns(); renderView(); renderDetail();
        }
        connection(state.follow ? "实时跟随中" : "保持当前运行");
      } catch (error) {
        if (state.version !== version) return;
        state.error = error.message || "无法读取运行检查数据";
        connection(`${state.error} · 将自动重试`, true);
        if (!state.inspection) renderAll();
      }
    })().finally(() => {
      if (state.inflight && state.inflight.promise === promise) state.inflight = null;
    });
    state.inflight = { version, promise };
    return promise;
  }

  let syncing = null;
  function synchronize() {
    if (syncing) return syncing;
    syncing = (async () => {
      try {
        const data = await getJson("/api/runs");
        const runs = safeArray(data.runs).filter((item) => item && typeof item.id === "string");
        const previous = state.runId;
        const listChanged = JSON.stringify(runs) !== JSON.stringify(state.runs) || data.total !== state.total || !state.loaded;
        state.runs = runs;
        state.total = number(data.total) ?? runs.length;
        state.loaded = true;
        if ((!state.runId || state.follow) && runs.length && state.runId !== runs[0].id) chooseRun(runs[0].id, true);
        if (listChanged || previous !== state.runId) renderRuns();
        if (state.runId) await loadSelected();
        else connection("已连接 · 等待运行");
      } catch (error) {
        state.loaded = false;
        state.error = error.message || "无法读取运行列表";
        connection(`${state.error} · 将自动重试`, true);
        if (!state.runs.length) renderRuns();
      }
    })().finally(() => { syncing = null; });
    return syncing;
  }

  document.addEventListener("click", (event) => {
    const view = event.target.closest("[data-view]");
    if (view) {
      const sameView = state.view === view.dataset.view;
      state.view = view.dataset.view;
      if (!sameView) { nodes.viewRoot.scrollTop = 0; window.scrollTo(0, 0); }
      renderTabs(); renderView();
      return;
    }
    const runButton = event.target.closest("[data-run-id]");
    if (runButton) { chooseRun(runButton.dataset.runId); void loadSelected(); return; }
    const eventButton = event.target.closest("[data-event-id]");
    if (eventButton) { state.detail = { type: "event", id: eventButton.dataset.eventId }; selectDetail(); return; }
    const modelButton = event.target.closest("[data-model-id]");
    if (modelButton) { state.detail = { type: "model", id: modelButton.dataset.modelId }; selectDetail(); return; }
    const toolButton = event.target.closest("[data-tool-id]");
    if (toolButton) { state.detail = { type: "tool", id: toolButton.dataset.toolId }; selectDetail(); return; }
    const contextButton = event.target.closest("[data-context-id]");
    if (contextButton) { state.detail = { type: "context", id: contextButton.dataset.contextId }; selectDetail(); return; }
    const filterButton = event.target.closest("[data-tool-filter]");
    if (filterButton) { state.toolFilter = filterButton.dataset.toolFilter; renderView(); return; }
    const rawFilter = event.target.closest("[data-raw-filter]");
    if (rawFilter) { state.rawFilter = rawFilter.dataset.rawFilter; renderView(); return; }
    const copy = event.target.closest("[data-copy-id]");
    if (copy) {
      const value = state.copyPayloads.get(copy.dataset.copyId);
      if (value !== undefined && navigator.clipboard) {
        navigator.clipboard.writeText(value).then(() => { copy.textContent = "已复制"; setTimeout(() => { copy.textContent = "复制"; }, 900); });
      }
      return;
    }
    if (event.target.closest("#closeDetail")) { state.detail = null; state.detailKey = ""; renderView(); renderDetail(); }
  });

  // 选中证据时只更新详情和选中样式，保留展开状态与滚动位置。
  function selectDetail() {
    renderView();
    renderDetail();
  }

  document.addEventListener("change", (event) => {
    const contextSelect = event.target.closest("[data-context-select]");
    if (contextSelect) {
      if (contextSelect.dataset.contextSelect === "a") state.contextA = contextSelect.value;
      else state.contextB = contextSelect.value;
      renderView();
    }
  });
  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-tool-search]")) { state.toolQuery = event.target.value; renderView(); }
    if (event.target.matches("[data-raw-search]")) { state.rawQuery = event.target.value; renderView(); }
  });
  // 只记录用户手动展开/收起；自动打开由首次渲染负责。
  nodes.viewRoot.addEventListener("toggle", (event) => {
    const details = event.target.closest("details[data-iteration-id]");
    if (!details) return;
    state.iterationTouched = true;
    if (details.open) state.openIterations.add(details.dataset.iterationId);
    else state.openIterations.delete(details.dataset.iterationId);
  }, true);
  nodes.runSearch.addEventListener("input", renderRuns);
  nodes.runStatus.addEventListener("change", renderRuns);
  nodes.refresh.addEventListener("click", () => { void synchronize(); });
  nodes.follow.addEventListener("click", () => { state.follow = !state.follow; renderRuns(); connection(state.follow ? "实时跟随中" : "保持当前运行"); if (state.follow) void synchronize(); });

  renderAll();
  void synchronize();
  setInterval(() => { void synchronize(); }, 1400);
})();
