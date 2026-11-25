(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const nodes = Object.fromEntries([
    "connection", "refresh", "follow", "runSearch", "runStatus", "runList", "runCount",
    "runTitle", "runId", "runBadge", "runMeta", "captureBadge", "statCalls", "statHttpDetail", "statTools",
    "statTokens", "statTokenDetail", "statDuration", "stages", "eventFilters", "eventList",
    "eventCount", "detailTabs", "detailTitle", "detailTag", "detailBody",
  ].map((id) => [id, $(id)]));
  const state = {
    runs: [], total: 0, loaded: false, runId: null, version: 0, events: [], offset: 0,
    report: null, selected: -1, filter: "focus", inspector: "event", follow: true,
    pinned: false, loading: false, loadingVersion: null, error: "", skipped: 0,
  };
  const statuses = {
    running: "进行中", pending: "待开始", unknown: "未结束", completed: "已完成", stopped: "已停止",
    failed: "失败", error: "失败", ok: "成功", rejected: "已拒绝", partial_success: "部分成功",
  };
  const stageNames = [
    ["context", "上下文"], ["model", "模型"], ["decision", "操作判定"],
    ["tool", "工具"], ["recovery", "恢复"], ["lifecycle", "结束"],
  ];
  const sectionNames = {
    prefix: "角色、工作区与工具规则", recovery_context: "恢复信息", memory: "工作记忆",
    relevant_memory: "相关记忆", history: "对话与工具历史", current_request: "本轮请求",
  };
  const toolStages = {
    validated: "参数校验通过", approval_requested: "检查审批策略", approval_granted: "审批通过",
    approval_denied: "审批拒绝", executing: "开始执行",
  };
  const important = new Set([
    "run_started", "prompt_built", "model_requested", "model_parsed", "tool_requested", "tool_stage",
    "tool_executed", "checkpoint_created", "recovery_reconciled", "runtime_identity_mismatch",
    "finalization_requested", "context_failed", "model_failed", "model_http_error", "run_finished",
  ]);
  const number = (value) => Number.isFinite(Number(value)) && value !== null && value !== "" ? Number(value) : null;
  const short = (value, limit = 110) => String(value ?? "").replace(/\s+/g, " ").slice(0, limit);
  const json = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "—";
  const clock = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString("zh-CN", { hour12: false });
  };
  const duration = (value) => {
    const ms = number(value);
    if (ms === null) return "—";
    return ms < 1000 ? `${Math.round(ms)} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)}分 ${Math.floor(ms % 60000 / 1000)}秒`;
  };
  const node = (tag, className = "", text) => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    // 日志属于外部文本，始终作为文本节点呈现，不能解释为网页代码。
    if (text !== undefined) result.textContent = String(text);
    return result;
  };
  const selectedRun = () => state.runs.find((run) => run.id === state.runId) || {};
  const terminal = (status) => ["completed", "failed", "error", "stopped"].includes(status);
  const runStatus = () => state.report?.status || [...state.events].reverse().find((event) => event.event === "run_finished")?.status || selectedRun().status || "running";

  function category(event) {
    const name = event.event || "";
    if (name === "model_parsed" || name === "finalization_requested") return "decision";
    if (/^(prompt_|context_)/.test(name)) return "context";
    if (/^(model_|http_)/.test(name)) return "model";
    if (/^tool_/.test(name)) return "tool";
    if (/(recovery|checkpoint|resume|journal|action_|identity_mismatch|stale)/.test(name)) return "recovery";
    return "lifecycle";
  }

  function describe(event) {
    const info = { title: event.event || "未知事件", summary: "保留日志中的原始字段", why: "此事件尚未定义专门的说明，可查看下方原始数据。", tone: "" };
    const metadata = event.prompt_metadata || {};
    switch (event.event) {
      case "run_started":
        Object.assign(info, { title: "收到用户请求", summary: short(event.user_request), why: "Page 为这次提问创建了独立运行；后续模型、工具和恢复记录都属于这次运行。" });
        break;
      case "prompt_built": {
        const reductions = metadata.budget_reductions || [];
        Object.assign(info, { title: "组装上下文", summary: `${metadata.prompt_chars ?? "?"} / ${metadata.prompt_budget_chars ?? "?"} 字符 · 压缩 ${reductions.length} 次`, why: reductions.length ? "运行框架为满足上下文预算压缩了部分内容；下方可以检查压缩顺序和每个段落的保留情况。" : "运行框架将规则、恢复信息、记忆、历史与本轮请求按顺序组装，准备交给模型。", tone: metadata.prompt_over_budget ? "warn" : "" });
        break;
      }
      case "prompt_rendered":
        Object.assign(info, { title: "查看完整提示词", summary: `第 ${event.attempts ?? "?"} 次 · ${event.tool_protocol || "text"} 协议`, why: "这是本地组装后交给适配器的提示词。原生工具协议实际发送的消息结构以 HTTP 请求体为准。" });
        break;
      case "model_requested":
        Object.assign(info, { title: "请求模型", summary: `第 ${event.attempts ?? "?"} 次 · 已用工具 ${event.tool_steps ?? "?"} 次`, why: "运行框架已发起一次模型调用，等待适配器返回；没有后续事件时，不能仅凭等待时间判断失败。" });
        break;
      case "model_http_request":
        Object.assign(info, { title: "发送 HTTP 请求", summary: `第 ${event.attempt ?? "?"} 次发送 · ${event.url || ""}`, why: "这是适配器发送给模型服务的实际请求体；可以核对模型名称、消息与工具定义。" });
        break;
      case "model_http_response":
        Object.assign(info, { title: "收到 HTTP 响应", summary: `HTTP ${event.status ?? "?"} · ${event.url || ""}`, why: "服务已返回 HTTP 响应。适配器仍需提取文字或原生工具调用，HTTP 成功本身不代表任务已经完成。", tone: number(event.status) >= 400 ? "error" : "" });
        break;
      case "model_http_error":
        Object.assign(info, { title: "HTTP 请求异常", summary: short(event.error), why: "这次 HTTP 发送发生异常；是否重试或停止，需要结合后续事件判断。", tone: "error" });
        break;
      case "model_extracted":
        Object.assign(info, { title: "适配器提取响应", summary: `${event.format || "text"} 协议 · ${event.tool_calls?.length || 0} 个原生工具调用`, why: "适配器已从服务响应中提取文本或工具调用。下一步由运行框架判定为工具、最终回答或重试。" });
        break;
      case "model_parsed":
        Object.assign(info, {
          title: { tool: "决定调用工具", final: "决定返回回答", retry: "决定要求重试" }[event.kind] || "解析模型响应",
          summary: event.kind === "tool" ? event.tool_name || event.payload?.name || "工具调用" : event.kind === "final" ? short(event.payload ?? event.answer_preview) : short(event.payload || event.kind),
          why: event.kind === "tool" ? "运行框架将模型输出解析为工具调用；接下来还要校验参数与权限，尚不能据此确认工具已经执行。" : event.kind === "final" ? "运行框架将模型输出解析为最终回答，因此本轮无需再调用工具。" : "运行框架未得到可直接完成的结果，将依据当前预算处理重试。",
          tone: event.kind === "retry" ? "warn" : "",
        });
        break;
      case "tool_requested":
        Object.assign(info, { title: `准备 ${event.name || "工具"}`, summary: short(json(event.args || {})), why: "工具调用已进入执行器；参数校验、审批与实际执行的进度会继续记录。" });
        break;
      case "tool_stage": {
        const stage = event.stage === "approval_requested" && event.approval === "ask" ? "等待人工审批" : toolStages[event.stage] || event.stage;
        Object.assign(info, { title: `${event.name || "工具"} · ${stage || "处理阶段"}`, summary: event.approval ? `审批策略：${event.approval}` : "工具执行过程", why: event.stage === "approval_denied" ? "审批没有通过，这次工具操作不会按原请求继续执行。" : event.stage === "approval_requested" && event.approval === "ask" ? "执行器正在等待用户明确审批；此时应查看运行 Page 的终端。" : "这是工具执行器实际记录的阶段，可以据此区分校验、审批与执行。", tone: event.stage === "approval_denied" ? "warn" : "" });
        break;
      }
      case "tool_executed":
        Object.assign(info, { title: `${event.name || "工具"} · ${statuses[event.tool_status] || event.tool_status || "已返回"}`, summary: short(event.tool_error_code || event.diff_summary || event.result), why: event.tool_status === "rejected" ? "执行器拒绝了这次工具操作。拒绝结果会反馈给模型，整次运行仍可能继续并完成。" : "执行器已经返回工具结果；可以检查实际参数、读写权限、受影响路径和副作用。", tone: event.tool_status === "rejected" || event.tool_status === "partial_success" ? "warn" : event.tool_status === "error" ? "error" : "" });
        break;
      case "checkpoint_created":
        Object.assign(info, { title: "保存检查点", summary: event.trigger || event.checkpoint_id || "保存可恢复状态", why: "运行框架保存了恢复所需的检查点，供进程中断后校验状态并继续处理。" });
        break;
      case "recovery_reconciled":
        Object.assign(info, { title: "核对恢复与副作用", summary: short([event.decision, event.resume_status, event.reason].filter(Boolean).join(" · ")), why: "运行框架核对检查点与动作日志，决定哪些动作已完成、可重试或需要人工复核。", tone: event.manual_review_actions?.length ? "warn" : "" });
        break;
      case "runtime_identity_mismatch":
        Object.assign(info, { title: "工作区身份不匹配", summary: (event.fields || []).join("、"), why: "恢复现场与当前工作区身份不一致；框架记录差异，避免盲目沿用旧状态。", tone: "warn" });
        break;
      case "finalization_requested":
        Object.assign(info, { title: "工具预算用尽，整理回答", summary: "进入收尾阶段", why: "本轮已达到工具步数预算，运行框架要求模型整理最终回答，而不是继续执行工具。", tone: "warn" });
        break;
      case "context_failed":
      case "model_failed":
        Object.assign(info, { title: event.event === "context_failed" ? "上下文构建失败" : "模型调用失败", summary: short(event.error || event.error_type), why: "运行框架记录了失败原因，并按当前任务状态处理停止与恢复。", tone: "error" });
        break;
      case "run_finished":
        Object.assign(info, { title: `运行${statuses[event.status] || event.status || "结束"}`, summary: event.stop_reason || "结束状态已记录", why: "这是本次运行的最终状态。停止原因与最终回答应结合工具结果一起查看。", tone: ["failed", "error"].includes(event.status) ? "error" : event.status === "stopped" ? "warn" : "" });
        break;
    }
    return info;
  }

  function isVisible(event) {
    if (state.filter === "all") return true;
    if (state.filter === "focus") return important.has(event.event) || !/^(prompt_rendered|model_http_request|model_http_response|model_extracted)$/.test(event.event || "");
    return category(event) === state.filter || state.filter === "model" && category(event) === "decision";
  }

  function empty(parent, title, detail = "") {
    const box = node("div", "empty-state");
    box.append(node("strong", "", title));
    if (detail) box.append(node("p", "", detail));
    parent.replaceChildren(box);
  }

  function connection(message, error = false) {
    if (nodes.connection.textContent !== message) nodes.connection.textContent = message;
    nodes.connection.classList.toggle("is-error", error);
    nodes.connection.classList.toggle("is-ok", !error);
    nodes.connection.title = error ? message : `只读本地日志；${state.follow ? "自动跟随最新运行" : "保持当前运行"}${state.skipped ? `；已跳过 ${state.skipped} 条无效记录` : ""}`;
  }

  function renderRuns() {
    const query = nodes.runSearch.value.trim().toLowerCase();
    const filter = nodes.runStatus.value;
    const visible = state.runs.filter((run) => {
      const matches = !query || [run.id, run.prompt, run.model, run.provider].some((value) => String(value || "").toLowerCase().includes(query));
      if (!matches) return false;
      if (!filter) return true;
      if (filter === "unfinished") return !terminal(run.status);
      return run.status === filter || filter === "failed" && run.status === "error";
    });
    nodes.runCount.textContent = `${visible.length} / ${state.total || state.runs.length}`;
    nodes.follow.textContent = state.follow ? "跟随最新 · 开" : "跟随最新 · 已暂停";
    nodes.follow.setAttribute("aria-pressed", String(state.follow));
    nodes.follow.classList.toggle("is-selected", state.follow);
    if (!visible.length) {
      empty(nodes.runList, state.loaded ? state.runs.length ? "没有匹配的运行" : "还没有运行记录" : "正在读取本地运行…", state.runs.length ? "调整搜索词或状态筛选。" : "在 Page 中发送一个请求后，记录会自动出现在这里。");
      return;
    }
    const scrollTop = nodes.runList.scrollTop;
    const focusedRun = nodes.runList.contains(document.activeElement) ? document.activeElement.dataset.runId : undefined;
    const fragment = document.createDocumentFragment();
    for (const run of visible) {
      const button = node("button", "run-row");
      button.type = "button";
      button.dataset.runId = run.id;
      button.classList.toggle("is-selected", run.id === state.runId);
      if (run.id === state.runId) button.setAttribute("aria-current", "true");
      const top = node("span", "run-row-top");
      top.append(node("span", `status-pill${["failed", "error"].includes(run.status) ? " is-error" : run.status === "completed" ? " is-ok" : " is-warn"}`, statuses[run.status] || run.status || "进行中"));
      top.append(node("time", "run-time", clock(run.updated_at)));
      button.append(top, node("span", "run-prompt", run.prompt || "未记录用户请求"), node("span", "run-foot", [run.model || run.provider || "未知模型", `工具 ${run.tool_steps ?? "—"} 次`].join(" · ")));
      button.title = run.id;
      button.addEventListener("click", () => {
        state.follow = false;
        chooseRun(run.id);
        renderRuns();
        if (!nodes.connection.classList.contains("is-error")) connection("保持当前运行");
        void loadSelected();
      });
      fragment.append(button);
    }
    nodes.runList.replaceChildren(fragment);
    nodes.runList.scrollTop = scrollTop;
    if (focusedRun) [...nodes.runList.children].find((row) => row.dataset.runId === focusedRun)?.focus({ preventScroll: true });
  }

  function renderOverview() {
    const run = selectedRun();
    const report = state.report || {};
    const finish = [...state.events].reverse().find((event) => event.event === "run_finished");
    const status = runStatus();
    nodes.runTitle.textContent = run.prompt || state.events.find((event) => event.event === "run_started")?.user_request || (state.runId ? "运行详情" : "选择一次运行，了解 Page 如何完成任务");
    nodes.runId.textContent = state.runId || "等待本地日志";
    nodes.runBadge.textContent = state.runId ? statuses[status] || status : "尚未选择";
    nodes.runBadge.classList.toggle("is-ok", status === "completed" && !!state.runId);
    nodes.runBadge.classList.toggle("is-error", ["failed", "error"].includes(status));
    nodes.runBadge.classList.toggle("is-warn", status === "stopped");
    nodes.runMeta.textContent = state.runId ? [report.provider || run.provider || "未知后端", report.model || run.model || "未知模型", `${state.events.length} 条事件`, report.tool_protocol ? `${report.tool_protocol} 协议` : ""].filter(Boolean).join(" · ") : "数据来自当前工作区的 .page/runs";
    const detailed = state.events.some((event) => event.event === "prompt_rendered" || event.event === "model_http_request" || event.full_request);
    nodes.captureBadge.textContent = state.runId ? detailed ? "详细采集" : "基础采集" : "只读查看";
    nodes.captureBadge.classList.toggle("is-ok", detailed);
    nodes.captureBadge.classList.toggle("is-warn", !!state.runId && !detailed);
    const parsed = state.events.filter((event) => event.event === "model_parsed");
    const calls = Math.max(state.events.filter((event) => event.event === "model_requested").length, parsed.length, number(report.attempts) || 0, number(run.attempts) || 0);
    const tools = Math.max(state.events.filter((event) => event.event === "tool_executed").length, number(report.tool_steps) || 0, number(run.tool_steps) || 0);
    const httpAttempts = state.events.filter((event) => event.event === "model_http_request").length;
    nodes.statCalls.textContent = state.runId ? calls : "—";
    nodes.statHttpDetail.textContent = httpAttempts ? `已记录 HTTP 尝试 ${httpAttempts} 次` : "HTTP 尝试未单独记录";
    nodes.statTools.textContent = state.runId ? tools : "—";
    // report 的用量可能只对应最后一次调用，优先按各次响应求和并注明覆盖范围。
    const usages = parsed.map((event) => event.completion_metadata || {}).filter((usage) => number(usage.total_tokens) !== null || number(usage.input_tokens) !== null || number(usage.output_tokens) !== null);
    const lastUsage = report.prompt_metadata || {};
    if (usages.length) {
      const input = usages.reduce((sum, usage) => sum + (number(usage.input_tokens) || 0), 0);
      const output = usages.reduce((sum, usage) => sum + (number(usage.output_tokens) || 0), 0);
      const total = usages.reduce((sum, usage) => sum + (number(usage.total_tokens) ?? ((number(usage.input_tokens) || 0) + (number(usage.output_tokens) || 0))), 0);
      const inputKnown = usages.filter((usage) => number(usage.input_tokens) !== null).length;
      const outputKnown = usages.filter((usage) => number(usage.output_tokens) !== null).length;
      const partialTotal = usages.length < calls || usages.some((usage) => number(usage.total_tokens) === null && (number(usage.input_tokens) === null || number(usage.output_tokens) === null));
      nodes.statTokens.textContent = `${partialTotal ? "≥ " : ""}${total.toLocaleString("zh-CN")}`;
      nodes.statTokens.title = "已记录的各次模型响应用量之和";
      const inputText = inputKnown ? `${inputKnown < calls ? "≥ " : ""}${input.toLocaleString("zh-CN")}` : "—";
      const outputText = outputKnown ? `${outputKnown < calls ? "≥ " : ""}${output.toLocaleString("zh-CN")}` : "—";
      nodes.statTokenDetail.textContent = `输入 ${inputText} · 输出 ${outputText}${usages.length < calls ? ` · 已记录 ${usages.length}/${calls} 次` : ""}`;
    } else if (number(lastUsage.total_tokens) !== null) {
      nodes.statTokens.textContent = Number(lastUsage.total_tokens).toLocaleString("zh-CN");
      nodes.statTokenDetail.textContent = `仅最后一次 · 输入 ${lastUsage.input_tokens ?? "—"} · 输出 ${lastUsage.output_tokens ?? "—"}`;
    } else {
      nodes.statTokens.textContent = "—";
      nodes.statTokenDetail.textContent = "日志未记录 Token 用量";
    }
    const start = Date.parse(state.events.find((event) => event.event === "run_started")?.created_at);
    // 未结束的旧日志不能证明进程仍在运行，耗时只计算到最后一条已记录事件。
    const end = terminal(status) || status === "unknown" ? Date.parse(finish?.created_at || state.events.at(-1)?.created_at) : Date.now();
    nodes.statDuration.textContent = duration(finish?.run_duration_ms ?? (Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : null));
    nodes.statDuration.title = finish?.run_duration_ms === undefined ? "按首末事件估算；日志未结束时不代表进程仍在运行" : "运行结束时记录的总耗时";
    renderStages(status);
  }

  function renderStages(status) {
    const finished = terminal(status);
    const latest = state.events.at(-1);
    let current = latest ? category(latest) : "context";
    if (latest?.event === "run_started") current = "context";
    const fragment = document.createDocumentFragment();
    for (const [key, title] of stageNames) {
      const items = state.events.filter((event) => category(event) === key && (key !== "lifecycle" || event.event === "run_finished"));
      if (key === "model" && !items.length && state.events.some((event) => event.event === "model_parsed")) items.push({});
      const reached = items.length > 0 || key === "lifecycle" && finished && !!state.runId;
      const active = !!state.runId && !finished && current === key;
      const stage = node("li", "stage");
      stage.dataset.category = key;
      stage.classList.toggle("is-current", active);
      stage.classList.toggle("is-done", reached && !active);
      stage.classList.toggle("is-error", items.some((event) => describe(event).tone === "error"));
      stage.classList.toggle("is-warn", items.some((event) => describe(event).tone === "warn"));
      if (active) stage.setAttribute("aria-current", "step");
      let hint = reached ? `${items.length || 1} 条记录` : finished ? "本轮未经过" : "等待进入";
      if (!state.runId) hint = "等待运行";
      if (active) hint = latest?.event === "model_requested" || latest?.event === "model_http_request" ? "未见模型响应" : latest?.event === "tool_stage" && latest.approval === "ask" && latest.stage === "approval_requested" ? "记录为等待审批" : "最后记录阶段";
      if (key === "lifecycle" && finished && state.runId) hint = statuses[status] || status;
      stage.append(node("span", "stage-label", title), node("span", "stage-hint", hint));
      fragment.append(stage);
    }
    nodes.stages.replaceChildren(fragment);
  }

  function renderTimeline() {
    const visible = state.events.map((event, index) => ({ event, index })).filter(({ event }) => isVisible(event));
    nodes.eventCount.textContent = `${visible.length} / ${state.events.length} 条`;
    for (const button of nodes.eventFilters.querySelectorAll("[data-filter]")) {
      button.classList.toggle("is-selected", button.dataset.filter === state.filter);
      button.setAttribute("aria-pressed", String(button.dataset.filter === state.filter));
    }
    if (!visible.length) {
      empty(nodes.eventList, state.loading ? "正在读取日志…" : state.error && !state.events.length ? "暂时无法读取日志" : state.runId ? "此筛选下还没有事件" : "等待选择运行", state.error || (state.runId ? "新的执行记录会自动追加到时间线。" : "从左侧选择一次运行，或等待新的请求。"));
      return;
    }
    const scrollTop = nodes.eventList.scrollTop;
    const atBottom = !nodes.eventList.childElementCount || scrollTop + nodes.eventList.clientHeight >= nodes.eventList.scrollHeight - 64;
    const focusedEvent = nodes.eventList.contains(document.activeElement) ? document.activeElement.dataset.eventIndex : undefined;
    const fragment = document.createDocumentFragment();
    for (const { event, index } of visible) {
      const info = describe(event);
      const button = node("button", "event-row");
      button.type = "button";
      button.dataset.category = category(event);
      button.dataset.eventIndex = index;
      button.classList.toggle("is-selected", index === state.selected && state.inspector === "event");
      if (info.tone) button.classList.add(`is-${info.tone}`);
      if (index === state.selected) button.setAttribute("aria-current", "true");
      const copy = node("span", "event-copy");
      copy.append(node("span", "event-title", info.title), node("span", "event-summary", info.summary));
      button.append(node("time", "event-time", clock(event.created_at)), node("span", "event-dot"), copy, node("span", "event-duration", duration(event.duration_ms ?? event.run_duration_ms)));
      button.addEventListener("click", () => {
        state.selected = index;
        state.pinned = true;
        state.inspector = "event";
        renderTimeline();
        renderDetail();
      });
      fragment.append(button);
    }
    nodes.eventList.replaceChildren(fragment);
    nodes.eventList.scrollTop = atBottom && !state.pinned ? nodes.eventList.scrollHeight : scrollTop;
    if (focusedEvent !== undefined) nodes.eventList.querySelector(`[data-event-index="${focusedEvent}"]`)?.focus({ preventScroll: true });
  }

  function section(title, value, { raw = false } = {}) {
    const wrapper = node(raw ? "details" : "section", "detail-section");
    wrapper.append(node(raw ? "summary" : "h3", "", title), node("pre", "payload", json(value)));
    return wrapper;
  }

  function fields(values) {
    const list = node("dl", "detail-kv");
    for (const [label, value] of values) {
      if (value === undefined || value === null || value === "") continue;
      list.append(node("dt", "", label), node("dd", "", typeof value === "object" ? json(value) : value));
    }
    return list;
  }

  function showEvent(event) {
    const info = describe(event);
    nodes.detailTitle.textContent = info.title;
    nodes.detailTag.textContent = event.event || "未知事件";
    const body = document.createDocumentFragment();
    body.append(node("p", "detail-note", info.why), fields([["记录时间", event.created_at], ["耗时", event.duration_ms === undefined ? undefined : duration(event.duration_ms)]]));
    switch (event.event) {
      case "run_started":
        if (!event.full_request) body.append(node("p", "detail-note", "这份日志中的用户请求可能是预览；完整内容以详细采集记录为准。"));
        body.append(section("用户请求", event.user_request || ""));
        break;
      case "prompt_built": {
        const metadata = event.prompt_metadata || {};
        body.append(fields([["提示词字符", metadata.prompt_chars], ["预算字符", metadata.prompt_budget_chars], ["估算 Token", metadata.token_estimate], ["估算方式", metadata.token_estimate_method]]));
        for (const [key, title] of [["budget_reductions", "上下文裁剪决策"], ["sections", "各段预算与保留情况"], ["context_blocks", "内容块的保留、压缩与丢弃"], ["relevant_memory", "相关记忆"], ["stale_rejected_paths", "拒绝沿用的过期路径"]]) {
          if (metadata[key] !== undefined) body.append(section(title, metadata[key]));
        }
        break;
      }
      case "prompt_rendered": {
        const order = event.section_order || [];
        if (order.length) body.append(section("段落顺序", order.map((key, index) => `${index + 1}. ${sectionNames[key] || key} [${key}]`).join("\n")));
        if (event.sections) body.append(section("各段原始与实际字符数", event.sections));
        body.append(section("适配器收到的完整提示词", event.prompt || ""));
        break;
      }
      case "model_http_request":
        body.append(fields([["接口", event.url], ["HTTP 发送次数", event.attempt]]), section("实际 HTTP 请求体", event.body ?? ""));
        break;
      case "model_http_response": {
        body.append(fields([["接口", event.url], ["HTTP 状态", event.status], ["HTTP 发送次数", event.attempt]]));
        let parsed = event.body;
        if (typeof parsed === "string") {
          try { parsed = JSON.parse(parsed); } catch { /* SSE 与非 JSON 响应保持原样，不能丢失原始服务数据。 */ }
        }
        body.append(section("HTTP 响应正文", parsed ?? ""));
        if (parsed !== event.body) body.append(section("原始 HTTP 响应文本", event.body, { raw: true }));
        break;
      }
      case "model_http_error":
      case "model_failed":
      case "context_failed":
        body.append(fields([["异常类型", event.error_type], ["接口", event.url], ["发送次数", event.attempt]]), section("错误信息", event.error ?? "未记录详细错误"));
        break;
      case "model_extracted":
        body.append(section("提取后的模型文本", event.text ?? ""));
        if (event.tool_calls?.length) body.append(section("原生工具调用", event.tool_calls));
        break;
      case "model_parsed":
        body.append(fields([["判定类型", event.kind], ["工具名称", event.tool_name]]));
        if (Object.hasOwn(event, "payload")) body.append(section("运行框架解析出的操作", event.payload));
        else body.append(section("回答预览", event.answer_preview || "此旧日志未采集完整解析结果。"));
        if (event.completion_metadata) body.append(section("这一次调用的用量与缓存", event.completion_metadata));
        break;
      case "model_requested":
        body.append(fields([["模型调用次数", event.attempts], ["已用工具次数", event.tool_steps], ["提示词缓存标识", event.prompt_cache_key]]));
        break;
      case "tool_requested":
      case "tool_stage":
      case "tool_executed":
        body.append(fields([["工具", event.name], ["阶段", toolStages[event.stage] || event.stage], ["状态", statuses[event.tool_status] || event.tool_status], ["审批策略", event.approval], ["风险等级", event.risk_level], ["只读操作", event.read_only], ["工作区变化", event.workspace_changed], ["调用标识", event.call_id], ["错误代码", event.tool_error_code], ["安全事件", event.security_event_type]]));
        if (event.args) body.append(section("工具参数", event.args));
        if (Object.hasOwn(event, "result")) body.append(section(event.verbose ? "工具返回内容" : "工具结果预览（旧日志可能已截断）", event.result));
        for (const [key, title] of [["affected_paths", "受影响路径"], ["diff_summary", "变更摘要"], ["action_journal", "副作用动作记录"]]) {
          if (event[key] !== undefined) body.append(section(title, event[key]));
        }
        break;
      case "recovery_reconciled":
        body.append(fields([["恢复决定", event.decision], ["恢复状态", event.resume_status], ["模式", event.mode], ["原因", event.reason]]));
        for (const [key, title] of [["reconciled_actions", "已核对动作"], ["skipped_actions", "跳过的动作"], ["retryable_actions", "可重试动作"], ["manual_review_actions", "需要人工复核的动作"]]) {
          if (event[key] !== undefined) body.append(section(title, event[key]));
        }
        break;
      case "checkpoint_created":
        body.append(fields([["检查点", event.checkpoint_id], ["保存触发原因", event.trigger]]));
        break;
      case "run_finished":
        body.append(fields([["最终状态", statuses[event.status] || event.status], ["停止原因", event.stop_reason], ["运行耗时", duration(event.run_duration_ms)]]), section("最终回答", event.final_answer ?? "未记录最终回答"));
        break;
    }
    // 专门说明之外保留全部字段，旧日志和后续新增事件仍可完整检查。
    body.append(section("全部事件字段", event, { raw: true }));
    nodes.detailBody.replaceChildren(body);
  }

  function renderDetail() {
    for (const button of nodes.detailTabs.querySelectorAll("[data-inspector]")) {
      button.classList.toggle("is-selected", button.dataset.inspector === state.inspector);
      button.setAttribute("aria-pressed", String(button.dataset.inspector === state.inspector));
    }
    if (state.inspector === "report") {
      nodes.detailTitle.textContent = "运行报告";
      nodes.detailTag.textContent = "report.json";
      if (!state.report) {
        empty(nodes.detailBody, state.runId ? "报告尚未生成" : "尚未选择运行", "报告通常在运行结束时生成；执行过程可先查看时间线。");
        return;
      }
      const report = state.report;
      const body = document.createDocumentFragment();
      body.append(fields([["状态", statuses[report.status] || report.status], ["停止原因", report.stop_reason], ["后端", report.provider], ["模型", report.model], ["工具协议", report.tool_protocol], ["模型调用", report.attempts], ["工具调用", report.tool_steps], ["恢复状态", report.resume_status], ["检查点", report.checkpoint_id]]));
      for (const [key, title] of [["final_answer", "最终回答"], ["recovery_decision", "恢复决策"], ["action_journal", "副作用动作日志"], ["prompt_metadata", "最后一次上下文与用量"], ["durable_promotions", "记忆写入"], ["durable_rejections", "记忆拒绝"], ["durable_superseded", "被替换的记忆"]]) {
        if (report[key] !== undefined) body.append(section(title, report[key]));
      }
      body.append(section("完整运行报告", report, { raw: true }));
      nodes.detailBody.replaceChildren(body);
      return;
    }
    const event = state.events[state.selected];
    if (event) showEvent(event);
    else {
      nodes.detailTitle.textContent = "查看一次执行决定";
      nodes.detailTag.textContent = "事件详情";
      empty(nodes.detailBody, "点击时间线中的步骤", "这里会解释这一步的含义，并展示日志实际采集的提示词、响应、参数与恢复数据。");
    }
  }

  function chooseRun(id) {
    if (state.runId === id) return;
    state.runId = id;
    state.version += 1;
    state.events = [];
    state.offset = 0;
    state.report = null;
    state.selected = -1;
    state.pinned = false;
    state.loading = true;
    state.error = "";
    state.skipped = 0;
    renderOverview();
    renderTimeline();
    renderDetail();
  }

  async function get(url) {
    const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(`本地接口返回 HTTP ${response.status}`);
    return response.json();
  }

  async function loadSelected() {
    if (!state.runId || state.loadingVersion === state.version) return;
    const version = state.version;
    const id = state.runId;
    state.loadingVersion = version;
    let changed = false;
    const needsOverview = state.loading || Boolean(state.error);
    try {
      let more = true;
      // 偏移由服务端返回，逐批消费完整事件；切换运行后丢弃旧请求的迟到结果。
      while (more && state.version === version) {
        const offset = state.offset;
        const data = await get(`/api/runs/${encodeURIComponent(id)}/events?offset=${offset}`);
        if (state.version !== version) return;
        if (data.reset) {
          state.events = [];
          state.selected = -1;
          state.pinned = false;
          state.skipped = 0;
          changed = true;
        }
        const incoming = (Array.isArray(data.events) ? data.events : []).filter((event) => event && typeof event === "object" && !Array.isArray(event));
        state.events.push(...incoming);
        changed ||= incoming.length > 0;
        state.skipped += number(data.skipped) || 0;
        const next = number(data.next_offset);
        if (next === null || next < 0 || !Number.isSafeInteger(next)) throw new Error("本地接口返回了无效日志偏移");
        if (data.has_more && next === offset && !data.reset) throw new Error("日志读取未取得进展，请刷新重试");
        state.offset = next;
        more = Boolean(data.has_more);
      }
      // 完成的报告可以复用，运行结束但尚未落盘时仍会在下一次轮询重试。
      const report = changed || !state.report ? await get(`/api/runs/${encodeURIComponent(id)}/report`) : state.report;
      if (state.version !== version) return;
      const reportChanged = report !== state.report && JSON.stringify(state.report) !== JSON.stringify(report);
      state.report = report;
      state.error = "";
      state.loading = false;
      if (!state.pinned || state.selected < 0) {
        const latest = state.events.findLastIndex(isVisible);
        state.selected = latest >= 0 ? latest : state.events.length - 1;
      }
      if (changed || reportChanged || needsOverview) renderOverview();
      if (changed || !state.events.length) renderTimeline();
      if (changed && !state.pinned || reportChanged || state.selected >= 0 && !nodes.detailBody.childElementCount) renderDetail();
      connection(state.follow ? "实时跟随中" : "保持当前运行");
    } catch (error) {
      if (state.version !== version) return;
      state.loading = false;
      state.error = error.message || "无法连接本地服务";
      connection(`${state.error} · 将自动重试`, true);
      if (changed || !state.events.length) renderTimeline();
    } finally {
      if (state.loadingVersion === version) state.loadingVersion = null;
    }
  }

  let synchronizing = null;
  function synchronize() {
    if (synchronizing) return synchronizing;
    synchronizing = (async () => {
      try {
        const data = await get("/api/runs");
        const runs = Array.isArray(data.runs) ? data.runs.filter((run) => run && typeof run.id === "string") : [];
        const total = number(data.total) ?? runs.length;
        const previous = state.runId;
        const listChanged = !state.loaded || total !== state.total || JSON.stringify(runs) !== JSON.stringify(state.runs);
        state.runs = runs;
        state.total = total;
        state.loaded = true;
        if ((!state.runId || state.follow) && state.runs.length) chooseRun(state.runs[0].id);
        // 列表未变时保留现有按钮和键盘焦点。
        if (listChanged || previous !== state.runId) renderRuns();
        if (listChanged && previous === state.runId) renderOverview();
        if (state.runId) await loadSelected();
        else connection("已连接 · 等待运行");
      } catch (error) {
        state.loaded = false;
        connection(`${error.message || "无法连接本地服务"} · 将自动重试`, true);
        if (!state.runs.length) empty(nodes.runList, "无法读取运行列表", "确认本地查看器服务仍在运行，然后点击刷新重试。");
      }
    })().finally(() => {
      synchronizing = null;
    });
    return synchronizing;
  }

  nodes.runSearch.addEventListener("input", renderRuns);
  nodes.runStatus.addEventListener("change", renderRuns);
  nodes.refresh.addEventListener("click", () => { void synchronize(); });
  nodes.follow.addEventListener("click", () => {
    state.follow = !state.follow;
    renderRuns();
    if (!nodes.connection.classList.contains("is-error")) connection(state.follow ? "实时跟随中" : "保持当前运行");
    if (state.follow) void synchronize();
  });
  for (const button of nodes.eventFilters.querySelectorAll("[data-filter]")) {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      if (state.selected < 0 || !isVisible(state.events[state.selected])) state.selected = state.events.findLastIndex(isVisible);
      renderTimeline();
      renderDetail();
    });
  }
  for (const button of nodes.detailTabs.querySelectorAll("[data-inspector]")) {
    button.addEventListener("click", () => {
      state.inspector = button.dataset.inspector;
      renderTimeline();
      renderDetail();
    });
  }

  renderRuns();
  renderOverview();
  renderTimeline();
  renderDetail();
  void synchronize();
  setInterval(() => { void synchronize(); }, 1400);
})();
