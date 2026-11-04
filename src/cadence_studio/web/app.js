/* Cadence Studio — local workbench UI */
(() => {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const icon = (name, cls = "") =>
    `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  const attr = (value) => escapeHtml(value).replace(/`/g, "&#096;");
  const clamp = (n, min, max) => Math.min(max, Math.max(min, n));
  const num = (n) => new Intl.NumberFormat("zh-CN").format(Number(n || 0));
  const pct = (n) => `${Math.round(Number(n || 0) * 10) / 10}%`;

  function bytes(value) {
    const n = Number(value || 0);
    if (!n) return "0 B";
    if (n < 1024) return `${n} B`;
    if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
    return `${(n / 1024 ** 3).toFixed(2)} GB`;
  }

  function duration(value) {
    const seconds = Number(value || 0);
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function dateLabel(iso, withTime = true) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    const options = withTime
      ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
      : { month: "short", day: "numeric" };
    return new Intl.DateTimeFormat("zh-CN", options).format(date);
  }

  function timeOnly(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
  }

  function relTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    const diff = (Date.now() - date.getTime()) / 1000;
    if (diff < 50) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    return dateLabel(iso, false);
  }

  const STATUS = {
    draft: ["草稿", "neutral"],
    queued: ["排队中", "paused"],
    running: ["运行中", "running"],
    paused: ["已暂停", "paused"],
    completed: ["已完成", "completed"],
    completed_with_errors: ["部分完成", "failed"],
    canceled: ["已取消", "canceled"],
    failed: ["失败", "failed"],
    preprocessing: ["预处理", "running"],
    inferencing: ["分析中", "running"],
    normalizing: ["规范化", "running"],
    saving: ["写入中", "running"],
    unreviewed: ["未复核", "neutral"],
    approved: ["已通过", "completed"],
    needs_changes: ["需修改", "paused"],
  };

  function statusBadge(status) {
    const [label, cls] = STATUS[status] || [status || "—", "neutral"];
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  }

  function stageMeta(item) {
    if (item.status === "failed") return { label: "失败", progress: 0, failed: true };
    if (item.status === "completed") return { label: "完成", progress: 100, failed: false };
    if (item.status === "canceled") return { label: "已取消", progress: 0, failed: true };
    if (item.status === "queued") {
      if (item.stage === "resume_normalize") return { label: "等待规范化", progress: 4, failed: false };
      if (item.stage === "retry_wait") return { label: "等待重试", progress: 3, failed: false };
      return { label: "排队中", progress: 0, failed: false };
    }
    const map = {
      preprocessing: "媒体预处理",
      transcoding: "转码中",
      endpoint_wait: "端点启动 / 等待",
      checking_endpoint: "检查端点",
      inferencing: "音频模型分析",
      raw_received: "原始结果已返回",
      normalizing: "规范化与标签校验",
      saving: "写入结果",
    };
    return { label: map[item.stage] || "处理中", progress: Number(item.progress || 0), failed: false };
  }

  function empty(value, fallback = "—") {
    return value === null || value === undefined || value === "" ? fallback : value;
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function childValue(container, key) {
    if (Array.isArray(container)) {
      return container.find((item) => item && item.id === key);
    }
    return container == null ? undefined : container[key];
  }

  function getPath(object, path) {
    return path.split(".").reduce((acc, key) => childValue(acc, key), object);
  }

  function setPath(object, path, value) {
    const keys = path.split(".");
    let cursor = object;
    for (let i = 0; i < keys.length - 1; i += 1) {
      let next = childValue(cursor, keys[i]);
      if (!next || typeof next !== "object") {
        if (Array.isArray(cursor)) return;
        cursor[keys[i]] = {};
        next = cursor[keys[i]];
      }
      cursor = next;
    }
    if (Array.isArray(cursor)) {
      const item = cursor.find((entry) => entry && entry.id === keys[keys.length - 1]);
      if (item) item.enabled = value;
      return;
    }
    cursor[keys[keys.length - 1]] = value;
  }

  // --------------------------------------------------------------------- API
  class APIError extends Error {
    constructor(message, code, status) {
      super(message);
      this.code = code;
      this.status = status;
    }
  }

  async function api(path, options = {}) {
    const opts = { ...options, headers: { ...(options.headers || {}) } };
    if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
      opts.headers["Content-Type"] = "application/json";
    }
    let response;
    try {
      response = await fetch(`/api${path}`, opts);
    } catch (error) {
      throw new APIError("无法连接本地工作台，请确认服务仍在运行。", "network", 0);
    }
    const type = response.headers.get("content-type") || "";
    const data = type.includes("application/json") ? await response.json().catch(() => ({})) : {};
    if (!response.ok) {
      const detail = data.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message || data.message || `请求失败（HTTP ${response.status}）`;
      throw new APIError(message, detail?.code || "http_error", response.status);
    }
    return data;
  }

  // ------------------------------------------------------------------- state
  const state = {
    overview: null,
    modules: [],
    hardwareProfiles: [],
    settings: null,
    settingsDraft: null,
    settingsTab: "endpoints",
    settingsDirty: false,
    batches: [],
    sidebarBatches: [],
    batch: null,
    items: [],
    itemsTotal: 0,
    selected: new Set(),
    endpoint: null,
    endpointTimer: null,
    taxonomy: null,
    tax: { category: "Genre", query: "", group: "", tagId: null, expanded: new Set() },
    activity: [],
    activityLevel: "",
    route: { name: "overview", id: null },
    routeToken: 0,
    filters: { batchQuery: "", batchStatus: "", itemQuery: "", itemStatus: "", itemSort: "position" },
    upload: { files: [], busy: false, progress: 0, modules: new Set(), advanced: false, metrics: null },
    drawer: null,
    palette: { open: false, index: 0, items: [] },
    lastEventId: 0,
    liveTimer: null,
    bootError: null,
    loaded: false,
  };

  const views = {
    overview: $("#view"),
  };

  // ----------------------------------------------------------------- utilities
  function toast(message, options = {}) {
    const type = options.type || "success";
    const root = $("#toast-root");
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    const iconName = type === "error" ? "alert" : type === "warn" ? "alert" : "check";
    node.innerHTML = `${icon(iconName)}<div><strong>${escapeHtml(options.title || (type === "error" ? "操作失败" : type === "warn" ? "请注意" : "已完成"))}</strong><p>${escapeHtml(message)}</p></div>`;
    if (type === "success") $$(".toast.success").forEach((old) => old.remove());
    root.appendChild(node);
    setTimeout(() => {
      node.classList.add("leaving");
      setTimeout(() => node.remove(), 220);
    }, options.duration || 3000);
  }

  function setServerHealth(ok) {
    const el = $("#server-health");
    if (!el) return;
    el.innerHTML = `<span class="status-dot small ${ok ? "ok" : "error"}"></span>${ok ? "Local" : "Offline"}`;
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f1efe7" : "#0b0c0d");
    $$(".theme-icon use").forEach((use) => {
      use.setAttribute("href", theme === "light" ? "#i-sun" : "#i-moon");
    });
    localStorage.setItem("cadence.theme", theme);
  }

  function toggleTheme() {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  }

  function setBreadcrumb(parts) {
    const el = $("#breadcrumb");
    if (!el) return;
    el.innerHTML = parts
      .map((part, index) =>
        index === parts.length - 1
          ? `<b>${escapeHtml(part.label)}</b>`
          : `<span>${escapeHtml(part.label)}</span>${icon("chevron")}`
      )
      .join("");
  }

  function setActiveNav(name) {
    $$(".nav-item[data-nav]").forEach((el) => el.classList.toggle("active", el.dataset.nav === name));
  }

  function nav(hash) {
    if (location.hash === hash) {
      route();
      return;
    }
    location.hash = hash;
  }

  function confirmDialog(title, message, confirmLabel = "确认") {
    return new Promise((resolve) => {
      const root = $("#modal-root");
      root.innerHTML = `
        <div class="modal-backdrop" data-action="confirm-close">
          <div class="modal" style="width:min(430px,92vw)" role="dialog" aria-modal="true">
            <div class="modal-head"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p></div>
              <button class="drawer-close" data-action="confirm-close" aria-label="关闭">${icon("x")}</button></div>
            <div class="modal-footer">
              <button class="btn" data-action="confirm-close">取消</button>
              <button class="btn danger" data-action="confirm-yes">${escapeHtml(confirmLabel)}</button>
            </div>
          </div>
        </div>`;
      const close = (value) => {
        root.innerHTML = "";
        resolve(value);
      };
      root.querySelector('[data-action="confirm-yes"]').addEventListener("click", () => close(true));
      root.querySelectorAll('[data-action="confirm-close"]').forEach((el) => {
        el.addEventListener("click", (event) => {
          if (event.target === el || event.currentTarget.classList.contains("drawer-close") || event.currentTarget.tagName === "BUTTON") close(false);
        });
      });
    });
  }

  // -------------------------------------------------------------------- boot
  async function boot() {
    applyTheme(localStorage.getItem("cadence.theme") || "dark");
    bindGlobalEvents();
    try {
      const [modules, taxonomy, settings, hardware] = await Promise.all([
        api("/modules"),
        api("/taxonomy"),
        api("/settings"),
        api("/hardware-profiles"),
      ]);
      state.modules = modules.modules;
      state.taxonomy = taxonomy;
      state.settings = settings;
      state.hardwareProfiles = hardware.profiles || [];
      state.settingsDraft = deepClone(settings);
      state.loaded = true;
      await refreshOverview();
      await refreshSidebarBatches();
      renderShell();
      await route();
      refreshEndpointStatus();
      connectSSE();
      state.endpointTimer = setInterval(() => {
        if (!document.hidden) refreshEndpointStatus(true);
      }, 20000);
    } catch (error) {
      state.bootError = error;
      renderBootError(error);
    }
  }

  function renderBootError(error) {
    const view = $("#view");
    view.innerHTML = `
      <div class="first-run" style="max-width:700px;margin-top:12vh">
        <div class="drop-large" style="border-color:color-mix(in srgb,var(--danger) 50%,transparent);color:var(--danger)">${icon("alert")}</div>
        <h2>工作台未能启动</h2>
        <p>${escapeHtml(error.message || error)}</p>
        <div class="first-run-actions"><button class="btn primary" data-action="reload">重新加载</button></div>
        <div class="first-run-meta"><span>检查终端窗口是否有错误信息</span><span>API · /api/health</span></div>
      </div>`;
  }

  async function refreshOverview() {
    state.overview = await api("/system/overview");
    if (!state.settings) return;
    renderShell();
  }

  async function refreshSidebarBatches() {
    try {
      const data = await api("/batches?limit=5");
      state.sidebarBatches = data.items || [];
      renderSidebarBatches();
    } catch (error) {
      // Non-fatal: the sidebar list is decorative.
    }
  }

  async function refreshEndpointStatus(silent = false) {
    if (!state.settings) return;
    const routeId = state.settings.inference.active_route_id;
    if (!routeId) return;
    try {
      state.endpoint = await api(`/inference/status?route_id=${encodeURIComponent(routeId)}`);
      updateEndpointUI();
    } catch (error) {
      state.endpoint = {
        state: "unknown",
        state_label: "无法检查",
        error: error.message,
        route_id: routeId,
      };
      updateEndpointUI();
      if (!silent) toast(error.message, { type: "warn", title: "端点状态不可用" });
    }
  }

  function updateEndpointUI() {
    if (!state.settings) return;
    const route = (state.settings.inference.routes || []).find(
      (r) => r.id === state.settings.inference.active_route_id
    ) || {};
    const endpoint = state.endpoint || {};
    const status = endpoint.state || "unknown";
    const dotClass = status === "running" ? "ok" : status === "paused" || status === "scaledToZero" ? "warning" : status === "failed" || status === "unreachable" ? "error" : "";
    const label = endpoint.state_label || (status === "unknown" ? "待检查" : status);
    const topLabel = status === "running" ? "Endpoint live" : status === "paused" ? "Endpoint paused" : status === "unreachable" ? "Endpoint offline" : label;
    ["#endpoint-dot", "#top-dot"].forEach((selector) => {
      const el = $(selector);
      if (!el) return;
      el.className = `status-dot ${dotClass} ${status === "running" ? "pulse" : ""}`;
    });
    const stateEl = $("#endpoint-state");
    if (stateEl) stateEl.textContent = label;
    const modelEl = $("#endpoint-model");
    if (modelEl) modelEl.textContent = route.name || "未选择端点";
    const metaEl = $("#endpoint-meta");
    if (metaEl) {
      let host = "";
      try {
        if (endpoint.url) host = new URL(endpoint.url).hostname.replace(".endpoints.huggingface.cloud", "");
      } catch (error) {
        host = "";
      }
      metaEl.textContent = endpoint.url
        ? `${route.model || "模型未填写"} · ${host || "URL 待解析"}`
        : route.model || "尚未配置 Inference URL";
    }
    const topState = $("#top-state");
    if (topState) topState.textContent = topLabel;
    const top = $("#top-endpoint");
    if (top) top.title = endpoint.error ? `${label} · ${endpoint.error}` : `${route.name || ""} · ${label}`;
  }

  // --------------------------------------------------------------- navigation
  function parseHash() {
    const hash = location.hash.replace(/^#\/?/, "");
    const segments = hash.split("/").filter(Boolean);
    if (!segments.length) return { name: "overview", id: null };
    if (segments[0] === "batch" && segments[1]) return { name: "batch", id: segments[1] };
    if (["overview", "batches", "taxonomy", "activity", "settings"].includes(segments[0])) {
      return { name: segments[0], id: null };
    }
    return { name: "overview", id: null };
  }

  async function route() {
    const routeInfo = parseHash();
    state.route = routeInfo;
    const token = ++state.routeToken;
    closeDrawer(false);
    setActiveNav(routeInfo.name);
    const labels = {
      overview: [{ label: "Workspace" }, { label: "总览" }],
      batches: [{ label: "Workspace" }, { label: "批次" }],
      taxonomy: [{ label: "Workspace" }, { label: "标签体系" }],
      activity: [{ label: "Workspace" }, { label: "活动" }],
      settings: [{ label: "Workspace" }, { label: "设置" }],
      batch: [{ label: "Workspace" }, { label: "批次" }, { label: "批次详情" }],
    };
    setBreadcrumb(labels[routeInfo.name] || labels.overview);
    const view = $("#view");
    view.classList.remove("fade-in");
    try {
      if (routeInfo.name === "overview") {
        await refreshOverview();
        if (token !== state.routeToken) return;
        renderOverview();
      } else if (routeInfo.name === "batches") {
        await refreshBatches();
        if (token !== state.routeToken) return;
        renderBatchesPage();
      } else if (routeInfo.name === "batch") {
        await openBatch(routeInfo.id);
        if (token !== state.routeToken) return;
      } else if (routeInfo.name === "taxonomy") {
        renderTaxonomyPage();
      } else if (routeInfo.name === "activity") {
        await refreshActivity();
        if (token !== state.routeToken) return;
        renderActivityPage();
      } else if (routeInfo.name === "settings") {
        renderSettingsPage();
      }
      view.scrollTop = 0;
      requestAnimationFrame(() => view.classList.add("fade-in"));
    } catch (error) {
      if (token !== state.routeToken) return;
      renderViewError(error);
    }
  }

  function renderViewError(error) {
    $("#view").innerHTML = `
      <div class="first-run" style="max-width:680px;margin-top:9vh">
        <div class="drop-large" style="color:var(--danger)">${icon("alert")}</div>
        <h2>这一页没有加载成功</h2>
        <p>${escapeHtml(error.message || error)}</p>
        <div class="first-run-actions"><button class="btn primary" data-action="reload">重试</button><a class="btn" href="#/overview">返回总览</a></div>
      </div>`;
  }

  // ---------------------------------------------------------------- shell
  function renderShell() {
    const overview = state.overview;
    const settings = state.settings;
    if (settings?.workspace) {
      $("#workspace-name").textContent = settings.workspace.name || "My Music Studio";
      $("#workspace-avatar").textContent = (settings.workspace.name || "C").trim().charAt(0).toUpperCase();
    }
    if (overview) {
      $("#nav-batch-count").textContent = overview.total_batches ?? 0;
    }
    renderSidebarBatches();
    updateEndpointUI();
    $$(".nav-item[data-nav]").forEach((el) => el.classList.toggle("active", el.dataset.nav === state.route.name));
  }

  function renderSidebarBatches() {
    const root = $("#sidebar-batches");
    if (!root) return;
    const batches = state.sidebarBatches || [];
    if (!batches.length) {
      root.innerHTML = `<div class="sidebar-batch"><span class="batch-dot"></span><span>还没有批次</span><small>—</small></div>`;
      return;
    }
    root.innerHTML = batches
      .map((batch) => {
        const running = ["running", "queued"].includes(batch.status);
        const failed = ["failed", "completed_with_errors"].includes(batch.status);
        return `<a class="sidebar-batch ${state.batch?.id === batch.id ? "active" : ""}" href="#/batch/${attr(batch.id)}">
          <span class="batch-dot ${running ? "running" : failed ? "failed" : ""}"></span>
          <span>${escapeHtml(batch.name)}</span>
          <small>${batch.counts?.total ?? 0}</small>
        </a>`;
      })
      .join("");
  }

  function renderTags(tags, cls = "") {
    if (!tags || !tags.length) return `<span class="muted">—</span>`;
    return `<div class="tag-row">${tags
      .map((tag) => {
        const name = tag.name_zh || tag.name_en || tag.id || "";
        const extra = tag.source_label && tag.source_label !== name ? ` · ${tag.source_label}` : "";
        return `<span class="tag ${cls} ${tag.mapped ? "mapped" : ""}" title="${attr(extra ? `原始：${tag.source_label} → 规范：${name}` : name)}">${escapeHtml(name)}${tag.confidence != null ? `<span class="tag-conf">${Math.round(tag.confidence * 100)}</span>` : ""}</span>`;
      })
      .join("")}</div>`;
  }

  function renderTagSingle(tag, cls = "") {
    if (!tag) return `<span class="muted">—</span>`;
    return renderTags([tag], cls);
  }

  function renderGenreItem(tag) {
    const path = Array.isArray(tag.path) && tag.path.length ? tag.path.join(" › ") : (tag.name_en || tag.name_zh || "");
    const level = Number(tag.level || 1);
    return `<div class="genre-hierarchy-item">
      <span class="badge ${tag.category === "Extra" ? "demo" : "neutral"}">${tag.category === "Extra" ? "补充" : `L${level}`}</span>
      <div class="genre-hierarchy-main"><strong>${escapeHtml(tag.name_zh || tag.name_en || tag.id)}</strong><small>${escapeHtml(path)}${tag.source_label && tag.source_label !== tag.name_en && tag.source_label !== tag.name_zh ? ` · 原始：${escapeHtml(tag.source_label)}` : ""}</small></div>
      <span class="genre-conf">${Math.round((tag.confidence || 0) * 100)}</span>
    </div>`;
  }

  // ---------------------------------------------------------------- overview
  function greeting() {
    const hour = new Date().getHours();
    if (hour < 5) return "夜深了";
    if (hour < 11) return "早上好";
    if (hour < 14) return "中午好";
    if (hour < 18) return "下午好";
    return "晚上好";
  }

  function sparkline(points = "2,18 10,14 18,17 26,9 34,11 42,6 50,8 58,3") {
    return `<svg class="kpi-spark" viewBox="0 0 60 24" preserveAspectRatio="none"><path d="M${points.replaceAll(" ", " L")}"/></svg>`;
  }

  function renderOverview() {
    const o = state.overview || {};
    const goal = Number(o.daily_goal || 500);
    const today = Number(o.today_completed || 0);
    const runway = goal ? Math.min(100, (today / goal) * 100) : 0;
    const successBase = Number(o.completed || 0) + Number(o.failed || 0);
    const success = successBase ? (Number(o.completed || 0) / successBase) * 100 : 0;
    const recent = o.recent_batches || [];
    const modules = state.modules || [];
    const endpoint = state.endpoint || {};
    const route = (state.settings?.inference.routes || []).find(
      (r) => r.id === state.settings?.inference.active_route_id
    ) || {};
    const hasBatches = Number(o.total_batches || 0) > 0 || recent.length > 0;
    const now = new Date();
    const dateText = new Intl.DateTimeFormat("zh-CN", {
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(now);

    $("#view").innerHTML = `
      <div class="dashboard-hero">
        <div class="hero-copy">
          <div class="eyebrow"><span class="status-dot"></span> CADENCE WORKBENCH · ${escapeHtml(dateText)}</div>
          <h1>${greeting()}，<br>把声音变成<em>可用数据</em>。</h1>
          <p>从整曲描述到曲风、情绪、BPM、结构与歌词。一次上传，交给专用音频模型听，再由 DeepSeek 按你的标签体系校准。全部原始输出与规范结果都可追溯。</p>
          <div class="hero-actions">
            <button class="btn primary large" data-action="new-batch">${icon("plus")}新建标注批次</button>
            <button class="btn ghost large" data-action="command">${icon("command")}打开命令面板</button>
          </div>
          <div class="hero-proof">
            <span>${icon("shield")}本地工作台</span>
            <span>${icon("tag")}${state.taxonomy?.source?.label_count || 641} 个规范标签</span>
            <span>${icon("cpu")}HF 专用端点</span>
          </div>
        </div>
        <div class="runway-card">
          <div class="runway-head"><span>Daily runway</span><button class="runway-target" data-action="edit-goal" title="修改每日目标">目标 ${num(goal)} ${icon("edit")}</button><strong>${Math.round(runway)}%</strong></div>
          <div class="runway-main"><b>${num(today)}</b><span>/ ${num(goal)} tracks</span></div>
          <div class="runway-bar"><i style="width:${runway}%"></i></div>
          <div class="runway-stats">
            <div><strong>${num(o.today_completed_minutes || 0)}</strong><span>min today</span></div>
            <div><strong>${num(o.queued || 0)}</strong><span>in queue</span></div>
            <div><strong>${num(o.running || 0)}</strong><span>in flight</span></div>
          </div>
          <div class="runway-footer">
            <span class="status-dot ${endpoint.state === "running" ? "ok" : endpoint.state === "paused" ? "warning" : ""}"></span>
            ${endpoint.state === "running" ? "端点在线，队列可以立即运行" : endpoint.state === "paused" ? "端点已暂停，提交时会自动唤醒" : "先完成端点配置与连接检查"}
          </div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-top"><span>今日完成</span>${icon("check")}</div>
          <div class="kpi-value"><strong>${num(today)}</strong><span>tracks</span></div>
          <div class="kpi-sub"><span class="status-dot ok"></span>${goal ? `${Math.max(0, goal - today)} 首到今日目标` : "未设置目标"}</div>
          ${sparkline()}
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>今日音频时长</span>${icon("wave")}</div>
          <div class="kpi-value"><strong>${num(o.today_completed_minutes || 0)}</strong><span>min</span></div>
          <div class="kpi-sub">${icon("clock")} 按完成项累计</div>
          ${sparkline("2,19 12,17 20,18 28,12 36,10 44,13 52,7 58,9")}
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>处理队列</span>${icon("pulse")}</div>
          <div class="kpi-value"><strong>${num((o.queued || 0) + (o.running || 0))}</strong><span>pending</span></div>
          <div class="kpi-sub">${o.running ? `<span class="status-dot ok pulse"></span>${o.running} 个正在处理` : "当前没有运行中的任务"}</div>
          ${sparkline("2,20 10,18 18,14 26,16 34,9 42,12 50,5 58,8")}
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>累计成功率</span>${icon("shield")}</div>
          <div class="kpi-value"><strong>${success ? Math.round(success) : 0}</strong><span>%</span></div>
          <div class="kpi-sub">${num(o.total_completed || 0)} 首完成 · ${num(o.total_items || 0)} 首入库</div>
          ${sparkline("2,18 10,16 18,17 26,12 34,13 42,8 50,9 58,6")}
        </div>
      </div>

      ${
        hasBatches
          ? `<div class="dashboard-grid">
              <section class="section-card">
                <div class="section-head">
                  <div><h2>批次动态 <span class="count">${num(o.total_batches)} total</span></h2><p>继续正在运行的工作，或回看最近完成的批次。</p></div>
                  <a class="section-link" href="#/batches">全部批次 ${icon("arrow-right")}</a>
                </div>
                <div class="mini-batch-list">${renderMiniBatches(recent)}</div>
              </section>
              <div style="display:flex;flex-direction:column;gap:14px">
                ${renderEndpointPanel()}
                ${renderTaxonomyMini()}
              </div>
            </div>
            <div class="drop-strip" data-action="new-batch" role="button" tabindex="0">
              <div class="drop-strip-icon">${icon("upload")}</div>
              <div><strong>把音频拖到这里，开始一个新批次</strong><span>支持批量导入 · 自动压缩上传 · 完成后导出 XLSX / JSON / Markdown</span></div>
              <kbd>N</kbd>
            </div>`
          : `<div class="first-run">
              <div class="drop-large">${icon("upload")}</div>
              <h2>先导入第一组声音</h2>
              <p>把 3–4 分钟的音乐拖进来，或者先载入内置演示批次，看看完整的数据结构、原始输出与导出效果。</p>
              <div class="first-run-actions">
                <button class="btn primary" data-action="new-batch">${icon("plus")}新建批次</button>
                <button class="btn" data-action="seed-demo">${icon("spark")}载入演示批次</button>
              </div>
              <div class="first-run-meta"><span>641 个规范标签</span><span>15 个标注模块</span><span>原始 + 规范化双轨结果</span></div>
            </div>`
      }
    `;
  }

  function renderMiniBatches(batches) {
    if (!batches.length) return `<div class="batch-empty"><strong>还没有批次</strong><p>创建一个批次开始标注。</p></div>`;
    return batches
      .map((batch) => {
        const counts = batch.counts || { total: 0, completed: 0 };
        const progress = counts.total ? Math.round(((counts.completed + (counts.failed || 0)) / counts.total) * 100) : 0;
        return `<div class="mini-batch" data-action="open-batch" data-id="${attr(batch.id)}">
          <div class="mini-batch-icon">${icon("layers")}</div>
          <div class="mini-batch-main"><strong>${escapeHtml(batch.name)}</strong><span>${statusBadge(batch.status)} <span>${counts.total || 0} 首</span> <span>${relTime(batch.created_at)}</span></span></div>
          <div class="mini-batch-progress"><div class="bar"><i style="width:${progress}%"></i></div><small>${progress}%</small></div>
          ${icon("chevron")}
        </div>`;
      })
      .join("");
  }

  function renderEndpointPanel() {
    const endpoint = state.endpoint || {};
    const route = (state.settings?.inference.routes || []).find(
      (r) => r.id === state.settings?.inference.active_route_id
    ) || {};
    const running = endpoint.state === "running";
    const label = endpoint.state_label || "待检查";
    return `<section class="section-card">
      <div class="section-head"><div><h2>推理端点</h2><p>自动恢复 · 空闲暂停 · 费用控制</p></div><button class="section-link" data-action="endpoint-panel">管理 ${icon("arrow-right")}</button></div>
      <div class="endpoint-panel">
        <div class="endpoint-hero">
          <div class="endpoint-orbit ${running ? "running" : ""}">${icon("cloud")}</div>
          <div class="endpoint-state-block">
            <div class="endpoint-state-label"><span class="status-dot ${running ? "ok" : endpoint.state === "paused" ? "warning" : endpoint.state === "failed" ? "error" : ""}"></span>${escapeHtml(label)}</div>
            <strong>${escapeHtml(route.name || "未配置端点")}</strong>
            <small>${escapeHtml(route.model || "选择模型后显示")}</small>
          </div>
        </div>
        <div class="endpoint-actions">
          <button class="btn small" data-action="endpoint-panel">${icon("settings")}查看状态</button>
          <button class="btn small ${running ? "" : "primary"}" data-action="endpoint-quick-resume">${icon(running ? "pause-circle" : "play-circle")}${running ? "暂停" : "恢复"}</button>
        </div>
        <div class="endpoint-meta">
          <div><span>Adapter</span><strong>${escapeHtml(route.adapter || "cadence")}</strong></div>
          <div><span>Concurrency</span><strong>${route.max_concurrency || 1} worker</strong></div>
          <div><span>Auto pause</span><strong>${state.settings?.inference?.lifecycle?.auto_pause ? "开启" : "关闭"}</strong></div>
          <div><span>Idle grace</span><strong>${state.settings?.inference?.lifecycle?.pause_grace_seconds || 120}s</strong></div>
        </div>
      </div>
    </section>`;
  }

  function renderTaxonomyMini() {
    const cats = state.taxonomy?.categories || {};
    const entries = Object.values(cats).sort((a, b) => b.count - a.count);
    const max = Math.max(...entries.map((c) => c.count), 1);
    return `<section class="section-card">
      <div class="taxonomy-mini">
        <div class="taxonomy-mini-head"><strong>标签体系</strong><span>${escapeHtml(state.taxonomy?.version || "")}</span></div>
        <div class="taxonomy-bars">
          ${entries
            .slice(0, 5)
            .map(
              (cat) => `<div class="taxonomy-bar-row"><span>${escapeHtml(cat.label_zh)}</span><i><b style="width:${Math.round((cat.count / max) * 100)}%;background:var(--${cat.color === "slate" ? "muted" : cat.color})"></b></i><em>${cat.count}</em></div>`
            )
            .join("")}
        </div>
        <div class="taxonomy-mini-foot"><span>${state.taxonomy?.source?.label_count || 641} 个标签 · ${state.taxonomy?.rule_count || 15} 条规则</span><a href="#/taxonomy" class="section-link">浏览 ${icon("arrow-right")}</a></div>
      </div>
    </section>`;
  }

  // ------------------------------------------------------------------ batches
  async function refreshBatches() {
    const params = new URLSearchParams({ limit: "100" });
    if (state.filters.batchQuery) params.set("query", state.filters.batchQuery);
    if (state.filters.batchStatus) params.set("status", state.filters.batchStatus);
    const data = await api(`/batches?${params}`);
    state.batches = data.items || [];
  }

  function renderBatchesPage() {
    const batches = state.batches || [];
    $("#view").innerHTML = `
      <div class="page-head">
        <div><div class="eyebrow"><span class="status-dot"></span> LIBRARY / BATCHES</div><h1>批次档案</h1><p>每一个批次冻结当时的标注要求、模型路由与标签版本。可以按状态、名称或 ID 快速定位。</p></div>
        <div class="head-actions"><button class="btn primary" data-action="new-batch">${icon("plus")}新建批次</button></div>
      </div>
      <section class="section-card">
        <div class="batch-toolbar">
          <label class="search-field">${icon("search")}<input id="batch-search" placeholder="搜索批次名称、备注或 ID" value="${attr(state.filters.batchQuery)}"></label>
          <select class="select" id="batch-status-filter">
            <option value="">全部状态</option>
            ${["draft", "queued", "running", "paused", "completed", "completed_with_errors", "failed", "canceled"]
              .map((s) => `<option value="${s}" ${state.filters.batchStatus === s ? "selected" : ""}>${STATUS[s]?.[0] || s}</option>`)
              .join("")}
          </select>
          <div class="toolbar-right"><span class="table-count">${batches.length} batches</span><button class="btn small" data-action="refresh-batches">${icon("refresh")}刷新</button></div>
        </div>
        ${batches.length ? renderBatchesTable(batches) : `<div class="batch-empty">${icon("layers")}<strong>没有匹配的批次</strong><p>调整筛选条件，或创建一个新批次。</p></div>`}
      </section>`;
    $("#batch-search").addEventListener("input", debounce((event) => {
      state.filters.batchQuery = event.target.value;
      refreshBatches().then(renderBatchesPage);
    }, 250));
    $("#batch-status-filter").addEventListener("change", (event) => {
      state.filters.batchStatus = event.target.value;
      refreshBatches().then(renderBatchesPage);
    });
  }

  function renderBatchesTable(batches) {
    return `<div class="batch-table-wrap"><table class="data-table">
      <thead><tr><th>批次</th><th>状态</th><th>进度</th><th>曲目</th><th>模型</th><th>创建时间</th><th></th></tr></thead>
      <tbody>${batches
        .map((batch) => {
          const counts = batch.counts || {};
          const total = counts.total || 0;
          const done = (counts.completed || 0) + (counts.failed || 0);
          const progress = total ? Math.round((done / total) * 100) : 0;
          const route = batch.route_snapshot?.inference_route || {};
          return `<tr data-action="open-batch" data-id="${attr(batch.id)}" style="cursor:pointer">
            <td class="file-cell"><div class="file-main"><div class="file-glyph">${icon("layers")}</div><div style="min-width:0"><div class="file-name">${escapeHtml(batch.name)}</div><div class="file-sub">${escapeHtml(batch.id)} ${batch.mode === "demo" ? "· DEMO" : ""}</div></div></div></td>
            <td>${statusBadge(batch.status)}</td>
            <td><div class="stage-cell"><div class="stage-label"><span>${progress}%</span><span class="muted">${done}/${total}</span></div><div class="stage-bar"><i style="width:${progress}%"></i></div></div></td>
            <td class="mono">${total}</td>
            <td><span class="muted">${escapeHtml(route.model || "—")}</span></td>
            <td><span class="mono muted">${dateLabel(batch.created_at)}</span></td>
            <td><div class="row-actions"><a class="icon-mini" href="#/batch/${attr(batch.id)}" title="打开" data-no-action>${icon("arrow-right")}</a></div></td>
          </tr>`;
        })
        .join("")}</tbody>
    </table></div>`;
  }

  async function openBatch(batchId) {
    const [batch, items] = await Promise.all([
      api(`/batches/${encodeURIComponent(batchId)}`),
      api(`/batches/${encodeURIComponent(batchId)}/items?limit=200&sort=${encodeURIComponent(state.filters.itemSort)}`),
    ]);
    state.batch = batch;
    state.items = items.items || [];
    state.itemsTotal = items.total || 0;
    state.selected = new Set();
    state.filters.itemQuery = "";
    state.filters.itemStatus = "";
    state.route = { name: "batch", id: batchId };
    setBreadcrumb([{ label: "Workspace" }, { label: "批次" }, { label: batch.name }]);
    setActiveNav("batches");
    renderBatchPage();
    refreshSidebarBatches();
  }

  async function reloadBatchData(soft = false) {
    if (!state.batch) return;
    const params = new URLSearchParams({ limit: "200", sort: state.filters.itemSort });
    if (state.filters.itemQuery) params.set("query", state.filters.itemQuery);
    if (state.filters.itemStatus) params.set("status", state.filters.itemStatus);
    const [batch, items] = await Promise.all([
      api(`/batches/${state.batch.id}`),
      api(`/batches/${state.batch.id}/items?${params}`),
    ]);
    state.batch = batch;
    state.items = items.items || [];
    state.itemsTotal = items.total || 0;
    if (!soft) {
      state.selected = new Set([...state.selected].filter((id) => state.items.some((item) => item.id === id)));
    }
    if (state.route.name === "batch") renderBatchPage();
    refreshSidebarBatches();
  }

  function batchActionButtons(batch) {
    const status = batch.status;
    const buttons = [];
    if (["draft", "queued", "running"].includes(status)) {
      if (status !== "draft") buttons.push(`<button class="btn" data-action="batch-pause">${icon("pause")}暂停</button>`);
    }
    if (status === "paused") buttons.push(`<button class="btn primary" data-action="batch-resume">${icon("play")}继续</button>`);
    if (status === "draft") buttons.push(`<button class="btn primary" data-action="batch-start">${icon("play")}开始处理</button>`);
    if (["completed_with_errors", "canceled", "failed"].includes(status)) {
      buttons.push(`<button class="btn" data-action="batch-retry">${icon("refresh")}重试失败项</button>`);
    }
    buttons.push(`<button class="btn" data-action="batch-menu">${icon("more")}更多</button>`);
    buttons.push(`<button class="btn primary" data-action="batch-export">${icon("download")}导出</button>`);
    return buttons.join("");
  }

  function renderBatchPage() {
    const batch = state.batch;
    if (!batch) return;
    const counts = batch.counts || {};
    const total = counts.total || 0;
    const done = counts.completed || 0;
    const failed = counts.failed || 0;
    const running = counts.running || 0;
    const queued = counts.queued || 0;
    const finished = done + failed;
    const progress = total ? Math.round((finished / total) * 100) : 0;
    const doneWidth = total ? (done / total) * 100 : 0;
    const failedWidth = total ? (failed / total) * 100 : 0;
    const runningWidth = total ? (running / total) * 100 : 0;
    const modules = (batch.spec?.modules || []).map((id) => state.modules.find((m) => m.id === id)?.label_zh || id);
    const route = batch.route_snapshot?.inference_route || {};
    const llm = batch.route_snapshot?.llm_route || {};
    const activeStatus = batch.status;
    $("#view").innerHTML = `
      <a class="back-link" href="#/batches">${icon("arrow-left")}所有批次</a>
      <div class="batch-head">
        <div class="batch-title-block">
          <div class="batch-title-line"><h1>${escapeHtml(batch.name)}</h1>${statusBadge(activeStatus)}${batch.mode === "demo" ? `<span class="badge demo">DEMO</span>` : ""}</div>
          <div class="batch-meta-line">
            <span>${icon("layers")}${escapeHtml(batch.id)}</span>
            <span>${icon("clock")}${dateLabel(batch.created_at)}</span>
            <span>${icon("bot")}${escapeHtml(route.name || route.model || "—")}</span>
            <span>${icon("tag")}${escapeHtml((batch.spec?.modules || []).length)} 个模块</span>
          </div>
        </div>
        <div class="batch-actions">${batchActionButtons(batch)}</div>
      </div>
      <div class="progress-card">
        <div class="progress-top">
          <div class="progress-number"><strong>${progress}</strong><span>%</span></div>
          <div class="progress-info">
            <div class="progress-label"><strong>${statusLabel(batch.status)}</strong><span>${finished} / ${total} 已处理</span></div>
            <div class="progress-track"><i class="done" style="width:${doneWidth}%"></i><i class="failed" style="width:${failedWidth}%"></i><i class="running" style="width:${runningWidth}%"></i></div>
          </div>
          <div class="progress-stats">
            <div class="progress-stat"><strong class="ok">${done}</strong><span>完成</span></div>
            <div class="progress-stat"><strong class="bad">${failed}</strong><span>失败</span></div>
            <div class="progress-stat"><strong>${queued}</strong><span>排队</span></div>
            <div class="progress-stat"><strong>${running}</strong><span>处理中</span></div>
          </div>
        </div>
        <div class="queue-strip">
          <span class="status-dot ${activeStatus === "running" ? "ok pulse" : activeStatus === "paused" ? "warning" : ""}"></span>
          <span>${activeStatus === "running" ? "处理队列正在工作" : activeStatus === "paused" ? "已暂停，新的音频不会开始" : activeStatus === "completed" ? "批次已完成，可导出交付" : "等待开始"}</span>
          <span class="queue-model">${icon("cpu")}${escapeHtml(route.model || "未绑定模型")} · ${escapeHtml(llm.model || "未绑定规范模型")}</span>
        </div>
      </div>
      <div class="batch-workspace">
        <div class="batch-toolbar">
          <label class="search-field">${icon("search")}<input id="item-search" placeholder="搜索文件名、原始输出或错误" value="${attr(state.filters.itemQuery)}"></label>
          <select class="select" id="item-status-filter">
            <option value="">全部状态</option>
            ${["completed", "failed", "queued", "preprocessing", "inferencing", "normalizing", "canceled"]
              .map((s) => `<option value="${s}" ${state.filters.itemStatus === s ? "selected" : ""}>${STATUS[s]?.[0] || s}</option>`)
              .join("")}
          </select>
          <select class="select" id="item-sort">
            <option value="position" ${state.filters.itemSort === "position" ? "selected" : ""}>按导入顺序</option>
            <option value="duration" ${state.filters.itemSort === "duration" ? "selected" : ""}>按时长</option>
            <option value="newest" ${state.filters.itemSort === "newest" ? "selected" : ""}>最新导入</option>
          </select>
          <div class="toolbar-right"><span class="table-count" id="item-count">${state.itemsTotal} tracks</span><button class="btn small" data-action="refresh-batch">${icon("refresh")}刷新</button></div>
        </div>
        ${state.items.length ? renderItemsTable() : renderItemsEmpty()}
        ${state.itemsTotal > state.items.length ? `<div class="pagination"><span>显示 ${state.items.length} / ${state.itemsTotal}</span><button class="btn small" data-action="load-more-items">加载更多</button></div>` : `<div class="pagination"><span>${state.items.length} / ${state.itemsTotal} tracks</span><span>${modules.join(" · ")}</span></div>`}
      </div>`;
    $("#item-search").addEventListener("input", debounce((event) => {
      state.filters.itemQuery = event.target.value;
      reloadBatchData().then(() => $("#item-search")?.focus());
    }, 300));
    $("#item-status-filter").addEventListener("change", (event) => {
      state.filters.itemStatus = event.target.value;
      reloadBatchData();
    });
    $("#item-sort").addEventListener("change", (event) => {
      state.filters.itemSort = event.target.value;
      reloadBatchData();
    });
  }

  function statusLabel(status) {
    const map = {
      draft: "草稿尚未开始",
      queued: "已加入处理队列",
      running: "批量处理中",
      paused: "批次已暂停",
      completed: "批次完成",
      completed_with_errors: "批次部分完成",
      canceled: "批次已取消",
      failed: "批次失败",
    };
    return map[status] || status;
  }

  function renderItemsEmpty() {
    return `<div class="batch-empty">${icon("music")}<strong>没有匹配的曲目</strong><p>调整搜索条件，或等待批次开始处理。</p></div>`;
  }

  function renderItemsTable() {
    return `<div class="batch-table-wrap"><table class="data-table">
      <thead><tr>
        <th style="width:30px"><input class="checkbox" type="checkbox" data-action="select-all" aria-label="全选"></th>
        <th style="width:34px">#</th><th>音频文件</th><th>时长</th><th>状态</th><th>曲风</th><th>情绪</th><th>BPM / Key</th><th style="width:42px"></th>
      </tr></thead>
      <tbody>${state.items
        .map((item, index) => {
          const summary = item.summary || {};
          const stage = stageMeta(item);
          return `<tr data-action="open-item" data-id="${attr(item.id)}" style="cursor:pointer">
            <td><input class="checkbox" type="checkbox" data-item-select="${attr(item.id)}" ${state.selected.has(item.id) ? "checked" : ""} aria-label="选择 ${attr(item.file_name)}"></td>
            <td class="mono muted">${String(item.position || index + 1).padStart(3, "0")}</td>
            <td class="file-cell"><div class="file-main"><div class="file-glyph">${icon("music")}</div><div style="min-width:0"><div class="file-name">${escapeHtml(item.file_name)}</div><div class="file-sub">${escapeHtml(summary.caption || (item.error_message ? item.error_message : "等待分析结果"))}</div></div></div></td>
            <td class="mono muted">${duration(item.duration_sec)}</td>
            <td><div class="stage-cell"><div class="stage-label"><span class="status-dot ${item.status === "completed" ? "ok" : item.status === "failed" ? "error" : item.status === "queued" ? "" : "ok pulse"}"></span>${escapeHtml(stage.label)}</div><div class="stage-bar ${stage.failed ? "failed" : ""}"><i style="width:${stage.progress}%"></i></div></div></td>
            <td>${summary.genre ? `<span class="tag genre">${escapeHtml(summary.genre)}</span>` : `<span class="muted">—</span>`}</td>
            <td>${summary.mood ? `<span class="tag mood">${escapeHtml(summary.mood)}</span>` : `<span class="muted">—</span>`}</td>
            <td class="mono muted">${summary.bpm ? `${summary.bpm}` : "—"} <span style="opacity:.55">${escapeHtml(summary.key || "")}</span></td>
            <td><div class="row-actions">${item.status === "failed" ? `<button class="icon-mini" data-action="item-retry" data-id="${attr(item.id)}" data-mode="normalize" title="重试">${icon("refresh")}</button>` : ""}<button class="icon-mini" data-action="open-item" data-id="${attr(item.id)}" title="查看">${icon("arrow-right")}</button></div></td>
          </tr>`;
        })
        .join("")}</tbody>
    </table></div>`;
  }

  // ------------------------------------------------------------- item drawer
  async function openItem(itemId, tab = "structured") {
    const root = $("#drawer-root");
    if (!state.drawer || state.drawer.id !== itemId) {
      root.innerHTML = `<div class="drawer-backdrop" data-action="close-drawer"></div><div class="drawer" role="dialog" aria-modal="true"><div class="drawer-head"><div class="drawer-title"><div class="eyebrow">LOADING</div><h2>正在读取…</h2></div></div><div class="drawer-body"><div class="skeleton-line"></div><div class="skeleton-line"></div></div></div>`;
    }
    try {
      const item = await api(`/items/${encodeURIComponent(itemId)}`);
      state.drawer = { id: itemId, item, tab, peaks: state.drawer?.id === itemId ? state.drawer.peaks : null, audioTime: state.drawer?.id === itemId ? state.drawer.audioTime : 0, playing: false };
      renderDrawer();
    } catch (error) {
      root.innerHTML = `<div class="drawer-backdrop" data-action="close-drawer"></div><div class="drawer"><div class="drawer-head"><div class="drawer-title"><h2>无法打开音频</h2></div><button class="drawer-close" data-action="close-drawer">${icon("x")}</button></div><div class="drawer-body"><div class="alert">${icon("alert")}${escapeHtml(error.message)}</div></div></div>`;
    }
  }

  function renderDrawer() {
    const drawer = state.drawer;
    if (!drawer) return;
    const item = drawer.item;
    const batch = item.batch || {};
    const root = $("#drawer-root");
    const specModules = batch.spec?.modules || [];
    const canNormalizeOnly = Boolean(item.raw_text);
    root.innerHTML = `
      <div class="drawer-backdrop" data-action="close-drawer"></div>
      <div class="drawer" role="dialog" aria-modal="true" aria-label="${attr(item.file_name)}">
        <div class="drawer-head">
          <div class="drawer-title-row">
            <div class="drawer-title">
              <div class="eyebrow">${escapeHtml(batch.name || "TRACK")} · ${escapeHtml(item.id)}</div>
              <h2>${escapeHtml(item.file_name)}</h2>
              <p>${statusBadge(item.status)} <span>${duration(item.duration_sec)}</span> <span>${bytes(item.size_bytes)}</span> <span>${escapeHtml(item.inference_model || "")}</span></p>
            </div>
            <button class="drawer-close" data-action="close-drawer" aria-label="关闭详情">${icon("x")}</button>
          </div>
          <div class="audio-player">
            <button class="play-button" data-action="toggle-play" aria-label="播放或暂停">${icon("play")}</button>
            <div class="wave-wrap" data-action="seek-audio"><canvas id="wave-canvas"></canvas></div>
            <div class="wave-time" id="wave-time">0:00 / ${duration(item.duration_sec)}</div>
          </div>
          <div class="drawer-tabs">
            ${[["structured", "结构化"], ["raw", "原始输出"], ["json", "规范化 JSON"], ["mappings", "标签映射"], ["meta", "元数据"]]
              .map(([key, label]) => `<button class="drawer-tab ${drawer.tab === key ? "active" : ""}" data-action="drawer-tab" data-tab="${key}">${label}</button>`)
              .join("")}
          </div>
        </div>
        <div class="drawer-body" id="drawer-body">${renderDrawerBody()}</div>
        <div class="drawer-footer">
          <button class="btn small ${item.review_status === "approved" ? "primary" : ""}" data-action="review-item" data-value="approved">${icon("check")}已通过</button>
          <button class="btn small ${item.review_status === "needs_changes" ? "danger" : ""}" data-action="review-item" data-value="needs_changes">${icon("alert")}需修改</button>
          <span class="spacer"></span>
          <button class="btn small" data-action="item-download" data-format="json">${icon("download")}JSON</button>
          <button class="btn small" data-action="item-retry" data-mode="normalize" ${canNormalizeOnly ? "" : "disabled"}>${icon("spark")}重新规范化</button>
          <button class="btn small" data-action="item-retry" data-mode="full">${icon("refresh")}完整重跑</button>
        </div>
      </div>`;
    mountAudio(item);
  }

  function renderDrawerBody() {
    const drawer = state.drawer;
    if (!drawer) return "";
    const item = drawer.item;
    const normalized = item.normalized;
    if (drawer.tab === "raw") return renderRawTab(item);
    if (drawer.tab === "json") return renderJsonTab(normalized);
    if (drawer.tab === "mappings") return renderMappingsTab(normalized);
    if (drawer.tab === "meta") return renderMetaTab(item);
    return renderStructuredTab(item);
  }

  function renderStructuredTab(item) {
    const normalized = item.normalized;
    if (!normalized) {
      return `<div class="alert ${item.error_code ? "" : "info"}">${icon(item.error_code ? "alert" : "clock")}
        ${escapeHtml(item.error_code ? item.error_message || item.error_code : "这条音频还没有规范化结果。若正在处理，请稍后刷新；也可以查看原始模型输出。")}
      </div>`;
    }
    const caption = normalized.caption || {};
    const genre = normalized.genre || {};
    const genreItems = genre.items || [genre.primary, ...(genre.secondary || [])].filter(Boolean);
    const mood = normalized.mood || {};
    const bpm = normalized.bpm_key || {};
    const instruments = normalized.instruments || {};
    const vocal = normalized.vocal || {};
    const language = normalized.language || {};
    const structure = normalized.structure || {};
    const lyrics = normalized.lyrics || {};
    const quality = normalized.quality || {};
    const production = normalized.production || {};
    const safety = normalized.safety || {};
    const scene = normalized.scene || {};
    const tags = mood.tags || [];
    const mapped = (normalized._meta?.warnings || []).length;
    return `
      ${item.error_code ? `<div class="alert">${icon("alert")}${escapeHtml(item.error_message || item.error_code)}</div>` : ""}
      ${normalized._meta?.warnings?.length ? `<div class="alert warn">${icon("alert")}<div>${normalized._meta.warnings.map(escapeHtml).join("<br>")}</div></div>` : ""}
      <div class="detail-section">
        <h3>${icon("caption")}CAPTION · 听觉描述</h3>
        <div class="caption-box">${escapeHtml(caption.text || "—")}${caption.short ? `<div class="caption-short">${escapeHtml(caption.short)}</div>` : ""}</div>
      </div>
      <div class="detail-section">
        <h3>${icon("genre")}核心标签</h3>
        <div class="detail-grid">
          <div class="metric-box"><span>Genre · ${genreItems.length} 个</span>${renderTagSingle(genre.primary, "genre")}<small>${escapeHtml(genre.reason || "")}</small></div>
          <div class="metric-box"><span>Mood / energy</span>${renderTagSingle(mood.dominant, "mood")}<small>valence ${mood.valence ?? "—"} · energy ${mood.energy ?? "—"}</small></div>
          <div class="metric-box"><span>Tempo</span><strong>${bpm.bpm ? `${bpm.bpm} BPM` : "—"}</strong><small>${escapeHtml(bpm.groove || "未检测")}</small></div>
          <div class="metric-box"><span>Key / meter</span><strong>${escapeHtml(`${empty(bpm.key, "—")} ${empty(bpm.mode, "")}`.trim())}</strong><small>${escapeHtml(bpm.time_signature || "拍号未知")}</small></div>
        </div>
      </div>
      ${tags.length ? `<div class="detail-section"><h3>${icon("mood")}情绪标签</h3>${renderTags(tags, "mood")}</div>` : ""}
      ${genreItems.length ? `<div class="detail-section"><h3>${icon("layers")}曲风层级 · 全部保留，不设主次上限</h3><div class="genre-hierarchy">${genreItems.map(renderGenreItem).join("")}</div></div>` : ""}
      <div class="detail-section">
        <h3>${icon("instrument")}乐器与声音</h3>
        ${renderTags([...(instruments.primary || []), ...(instruments.secondary || [])], "instrument")}
        ${instruments.notes ? `<div class="caption-short">${escapeHtml(instruments.notes)}</div>` : ""}
      </div>
      ${structure.sections?.length ? `<div class="detail-section"><h3>${icon("structure")}曲式结构 <span style="color:var(--faint);font-family:var(--font-mono);font-size:8px">${structure.sections.length} sections</span></h3><div class="structure-list">${structure.sections
        .map((section) => {
          const width = item.duration_sec ? ((section.end_sec - section.start_sec) / item.duration_sec) * 100 : 30;
          return `<div class="structure-row"><b>${escapeHtml(section.label)} <span style="color:var(--faint);font-weight:400">${escapeHtml(section.label_zh || "")}</span></b><div class="structure-bar" style="width:${clamp(width, 8, 100)}%"></div><span>${section.start_sec.toFixed(0)}s</span></div>`;
        })
        .join("")}</div></div>` : ""}
      ${vocal.present || vocal.tags?.length ? `<div class="detail-section"><h3>${icon("vocal")}人声</h3><div class="caption-box" style="font-size:10.5px">${renderTags(vocal.tags, "")}<div class="caption-short">${escapeHtml([vocal.lead?.gender, vocal.lead?.timbre, vocal.lead?.delivery].filter(Boolean).join(" · ") || "未描述")}</div></div></div>` : ""}
      ${language.primary || language.instrumental ? `<div class="detail-section"><h3>${icon("language")}语言</h3>${renderTagSingle(language.primary, "")}<span class="caption-short">${language.instrumental ? "纯器乐 / 无人声" : escapeHtml(language.notes || "")}</span></div>` : ""}
      ${lyrics.text ? `<div class="detail-section"><h3>${icon("lyrics")}歌词 ${lyrics.explicit ? `<span class="badge failed">EXPLICIT</span>` : ""}</h3><div class="caption-box" style="white-space:pre-line;font-size:10.5px;line-height:1.8">${escapeHtml(lyrics.text)}</div></div>` : ""}
      ${scene.primary ? `<div class="detail-section"><h3>${icon("scene")}场景与用途</h3>${renderTagSingle(scene.primary, "scene")}${scene.secondary?.length ? renderTags(scene.secondary, "scene") : ""}</div>` : ""}
      ${production.era || production.production_style ? `<div class="detail-section"><h3>${icon("production")}制作与年代</h3><div class="caption-box" style="font-size:10.5px">${escapeHtml(production.era || "—")} · ${escapeHtml(production.production_style || "")}<div class="caption-short">${escapeHtml(production.mix_character || production.texture || "")}</div></div></div>` : ""}
      ${quality.score != null ? `<div class="detail-section"><h3>${icon("quality")}音频质量</h3><div class="metric-box"><span>Quality score</span><strong>${quality.score} / 100</strong><small>${quality.usable ? "可用于标注交付" : "建议人工复核"} ${escapeHtml((quality.issues || []).join(" · "))}</small></div></div>` : ""}
      ${safety.explicit || safety.flags?.length ? `<div class="detail-section"><h3>${icon("shield")}内容安全</h3><div class="tag-row">${(safety.flags || []).map((flag) => `<span class="tag" style="color:var(--danger)">${escapeHtml(flag)}</span>`).join("")}</div></div>` : ""}
      ${mapped ? "" : ""}
      <div class="review-strip">${icon("check")}人工复核：<strong>${escapeHtml(STATUS[item.review_status]?.[0] || item.review_status)}</strong>${item.review_note ? ` · ${escapeHtml(item.review_note)}` : ""}</div>
    `;
  }

  function renderRawTab(item) {
    return `
      <div class="detail-section">
        <h3>${icon("wave")}AUDIO MODEL · 原始观察 ${item.raw_text ? `· ${num(item.raw_text.length)} chars` : ""}</h3>
        ${renderCode(item.raw_text || "音频模型还没有返回内容。", "音频模型原始输出")}
      </div>
      <div class="detail-section">
        <h3>${icon("bot")}NORMALIZER · 大模型原始输出 ${item.llm_raw_text ? `· ${num(item.llm_raw_text.length)} chars` : ""}</h3>
        ${renderCode(item.llm_raw_text || "还没有大模型输出。", "规范化模型原始输出")}
      </div>`;
  }

  function renderJsonTab(normalized) {
    if (!normalized) return `<div class="empty-detail">还没有规范化结果。</div>`;
    return `<div class="detail-section"><h3>${icon("code")}NORMALIZED JSON</h3>${renderCode(JSON.stringify(normalized, null, 2), "规范化 JSON", "json")}</div>`;
  }

  function renderMappingsTab(normalized) {
    if (!normalized) return `<div class="empty-detail">还没有可映射的标签。</div>`;
    const rows = [];
    const modules = [["genre", "曲风"], ["mood", "情绪"], ["scene", "场景"], ["instruments", "乐器"], ["vocal", "人声"], ["language", "语言"], ["extra", "补充"]];
    modules.forEach(([key, label]) => {
      const value = normalized[key] || {};
      const tags = [];
      if (Array.isArray(value.items)) tags.push(...value.items);
      if (value.primary) tags.push(value.primary);
      if (Array.isArray(value.secondary)) tags.push(...value.secondary);
      if (Array.isArray(value.tags)) tags.push(...value.tags);
      const seenTags = new Set();
      tags.filter(Boolean).forEach((tag) => {
        if (!tag.id || seenTags.has(tag.id)) return;
        seenTags.add(tag.id);
        if (tag.mapped || (tag.source_label && tag.source_label !== tag.name_zh && tag.source_label !== tag.name_en)) {
          rows.push(`<div class="mapping-row"><span class="from">${escapeHtml(tag.source_label || "—")}</span><span class="arrow">${icon("arrow-right")}</span><span class="to">${escapeHtml(tag.name_zh)} <em class="muted" style="font-style:normal">${escapeHtml(tag.id)}</em></span><span class="conf">${Math.round((tag.confidence || 0) * 100)}%</span></div>`);
        }
      });
    });
    const unmapped = normalized.unmapped || [];
    return `<div class="detail-section"><h3>${icon("tag")}规范映射 ${rows.length ? `· ${rows.length}` : ""}</h3>${rows.length ? `<div class="mapping-list">${rows.join("")}</div>` : `<div class="empty-detail">全部标签都是标准名，没有发生近似映射。</div>`}</div>
      <div class="detail-section"><h3>${icon("alert")}未能映射</h3>${unmapped.length ? `<div class="mapping-list">${unmapped.map((u) => `<div class="mapping-row"><span class="from">${escapeHtml(u.source_label || "—")}</span><span class="arrow">${icon("arrow-right")}</span><span class="to">${escapeHtml(u.closest_hint || "无可靠标签")}</span><span class="conf">${escapeHtml(u.category || "")}</span></div>`).join("")}</div>` : `<div class="empty-detail">没有未映射标签。</div>`}</div>`;
  }

  function renderMetaTab(item) {
    const rows = [
      ["Item ID", item.id],
      ["Batch", item.batch?.name || item.batch_id],
      ["文件", item.file_name],
      ["时长", `${item.duration_sec ?? "—"} s`],
      ["采样率", item.sample_rate ? `${item.sample_rate} Hz` : "—"],
      ["声道", item.channels ?? "—"],
      ["SHA-256", item.sha256 || "—"],
      ["音频模型", item.inference_model || "—"],
      ["文字模型", item.llm_model || "—"],
      ["尝试次数", item.attempts ?? 0],
      ["创建时间", dateLabel(item.created_at)],
      ["完成时间", item.finished_at ? dateLabel(item.finished_at) : "—"],
      ["总耗时", item.timings?.total_ms ? `${(item.timings.total_ms / 1000).toFixed(1)} s` : "—"],
      ["错误码", item.error_code || "—"],
    ];
    return `<div class="detail-section"><h3>${icon("database")}TRACK METADATA</h3><div class="meta-list">${rows.map(([k, v]) => `<div class="meta-row"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("")}</div></div>
      ${item.error_message ? `<div class="alert">${icon("alert")}${escapeHtml(item.error_message)}</div>` : ""}`;
  }

  function renderCode(text, label, prefer = "text") {
    return `<div class="code-block"><div class="code-toolbar"><span>${escapeHtml(label)}</span><button data-action="copy-code" data-copy-target="code-${prefer}-${Math.random().toString(36).slice(2, 7)}">${icon("copy")}复制</button></div><pre>${escapeHtml(text)}</pre></div>`;
  }

  function mountAudio(item) {
    const drawer = state.drawer;
    drawer.audioTime = drawer.audioTime || 0;
    const audio = new Audio(`/api/items/${encodeURIComponent(item.id)}/audio`);
    audio.preload = "metadata";
    drawer.audio = audio;
    const canvas = $("#wave-canvas");
    const timeEl = $("#wave-time");
    const playBtn = $('[data-action="toggle-play"]');
    const setPlayIcon = (playing) => {
      if (playBtn) playBtn.innerHTML = icon(playing ? "pause" : "play");
    };
    audio.addEventListener("loadedmetadata", () => {
      if (drawer.audioTime > 0) audio.currentTime = Math.min(drawer.audioTime, audio.duration || 0);
    });
    audio.addEventListener("play", () => setPlayIcon(true));
    audio.addEventListener("pause", () => setPlayIcon(false));
    audio.addEventListener("ended", () => setPlayIcon(false));
    audio.addEventListener("timeupdate", () => {
      drawer.audioTime = audio.currentTime;
      if (timeEl) timeEl.textContent = `${duration(audio.currentTime)} / ${duration(audio.duration || item.duration_sec)}`;
      drawWave(canvas, drawer.peaks, audio.currentTime / (audio.duration || item.duration_sec || 1));
    });
    drawWave(canvas, drawer.peaks, 0);
    fetch(`/api/items/${encodeURIComponent(item.id)}/audio`)
      .then((response) => response.arrayBuffer())
      .then((buffer) => {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) throw new Error("no audio context");
        const context = new Context();
        return context.decodeAudioData(buffer).then((decoded) => {
          const data = decoded.getChannelData(0);
          const count = 150;
          const peaks = [];
          const block = Math.floor(data.length / count);
          for (let i = 0; i < count; i += 1) {
            let max = 0;
            for (let j = 0; j < block; j += 8) max = Math.max(max, Math.abs(data[i * block + j] || 0));
            peaks.push(max);
          }
          drawer.peaks = peaks;
          drawWave(canvas, peaks, 0);
          context.close();
        });
      })
      .catch(() => {
        drawer.peaks = Array.from({ length: 150 }, (_, i) => 0.2 + Math.abs(Math.sin(i * 0.3)) * 0.5);
        drawWave(canvas, drawer.peaks, 0);
      });
    canvas?.addEventListener("click", (event) => {
      const rect = canvas.getBoundingClientRect();
      const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      if (audio.duration) audio.currentTime = ratio * audio.duration;
    });
  }

  function drawWave(canvas, peaks, progress = 0) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 400;
    const height = canvas.clientHeight || 34;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    const data = peaks && peaks.length ? peaks : Array.from({ length: 120 }, () => 0.35);
    const barWidth = width / data.length;
    data.forEach((peak, index) => {
      const x = index * barWidth;
      const h = Math.max(2, peak * height * 0.8);
      const played = index / data.length <= progress;
      ctx.fillStyle = played ? "#c9f56a" : "rgba(145,150,143,.38)";
      ctx.fillRect(x, (height - h) / 2, Math.max(1, barWidth * 0.55), h);
    });
    ctx.fillStyle = "#f3f1e8";
    ctx.fillRect(progress * width, 0, 1, height);
  }

  function closeDrawer(clear = true) {
    if (state.drawer?.audio) {
      state.drawer.audio.pause();
      state.drawer.audio.src = "";
    }
    state.drawer = null;
    if (clear) $("#drawer-root").innerHTML = "";
    else $("#drawer-root").innerHTML = "";
  }

  // ------------------------------------------------------------------ taxonomy
  function renderTaxonomyPage() {
    if (!state.taxonomy) return;
    const tax = state.taxonomy;
    const categories = tax.categories || {};
    const counts = tax.source?.category_counts || {};
    const total = tax.source?.label_count || 641;
    const cats = Object.values(categories);
    const max = Math.max(...cats.map((c) => c.count), 1);
    $("#view").innerHTML = `
      <div class="taxonomy-hero">
        <div>
          <div class="eyebrow"><span class="status-dot"></span> GOVERNANCE / TAXONOMY</div>
          <h1>一套说话算数的<br>声音标签语言。</h1>
          <p>641 个正式标签、15 条标注规则与 7 组场景公式。模型不能发明标签；所有近似映射都会保留原始说法、规范 ID 与置信度，方便复核和回滚。</p>
          <div class="rule-callout" style="margin-top:16px"><span>${icon("shield")}</span><div>${escapeHtml(tax.mood_rule || "情绪标签应标尽标；五个心情节奏类标签互斥。")}</div></div>
        </div>
        <div class="taxonomy-stats">
          <div class="taxonomy-stat"><strong>${total}</strong><span>规范标签</span><i><b style="width:100%"></b></i></div>
          <div class="taxonomy-stat"><strong>${tax.rule_count || 15}</strong><span>条规则</span><i><b style="width:72%"></b></i></div>
          <div class="taxonomy-stat"><strong>${tax.formula_count || 7}</strong><span>组公式</span><i><b style="width:45%"></b></i></div>
          <div class="taxonomy-stat"><strong>${cats.length}</strong><span>大类</span><i><b style="width:35%"></b></i></div>
        </div>
      </div>
      <div class="taxonomy-workspace">
        <section class="taxonomy-browser">
          <div class="taxonomy-toolbar">
            <label class="search-field">${icon("search")}<input id="tax-search" placeholder="搜索中文名、英文名、标签 ID 或定义" value="${attr(state.tax.query)}"></label>
            <span class="table-count" id="tax-count">${total} tags</span>
            <button class="btn small" data-action="tax-expand-all">展开全部</button>
            <button class="btn small" data-action="tax-collapse-all">收起</button>
          </div>
          <div class="category-tabs" id="category-tabs">${renderCategoryTabs()}</div>
          <div class="taxonomy-list" id="taxonomy-list"></div>
        </section>
        <aside class="taxonomy-detail" id="taxonomy-detail"></aside>
      </div>`;
    renderTaxonomyRows();
    renderTaxonomyDetail();
    $("#tax-search").addEventListener("input", debounce((event) => {
      state.tax.query = event.target.value;
      state.tax.tagId = null;
      renderTaxonomyRows();
      renderTaxonomyDetail();
    }, 150));
    $("#category-tabs").addEventListener("click", (event) => {
      const button = event.target.closest("[data-tax-category]");
      if (!button) return;
      state.tax.category = button.dataset.taxCategory;
      state.tax.tagId = null;
      state.tax.expanded = new Set();
      renderCategoryTabs();
      renderTaxonomyRows();
      renderTaxonomyDetail();
    });
    $("#taxonomy-list").addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-tax-toggle]");
      if (toggle) {
        event.stopPropagation();
        const id = toggle.dataset.taxToggle;
        if (state.tax.expanded.has(id)) state.tax.expanded.delete(id);
        else state.tax.expanded.add(id);
        renderTaxonomyRows();
        return;
      }
      const row = event.target.closest("[data-tax-id]");
      if (!row) return;
      state.tax.tagId = row.dataset.taxId;
      renderTaxonomyRows();
      renderTaxonomyDetail();
    });
  }

  function renderCategoryTabs() {
    const cats = state.taxonomy?.categories || {};
    return `<button class="category-tab ${state.tax.category === "all" ? "active" : ""}" data-tax-category="all">全部 <em>${state.taxonomy?.source?.label_count || 641}</em></button>${Object.values(cats)
      .map((cat) => `<button class="category-tab ${state.tax.category === cat.key ? "active" : ""}" data-tax-category="${attr(cat.key)}">${escapeHtml(cat.label_zh)} <em>${cat.count}</em></button>`)
      .join("")}`;
  }

  function filteredTaxonomy() {
    const tags = state.taxonomy?.tags || [];
    const category = state.tax.category;
    const query = state.tax.query.trim().toLowerCase();
    return tags.filter((tag) => {
      if (category !== "all" && tag.category !== category) return false;
      if (!query) return true;
      const haystack = `${tag.id} ${tag.zh} ${tag.en} ${tag.group} ${tag.definition}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function genreChildrenMap() {
    const all = (state.taxonomy?.tags || []).filter((tag) => tag.category === "Genre");
    const map = new Map();
    all.forEach((tag) => {
      const parent = tag.genre_parent_id || "";
      if (!map.has(parent)) map.set(parent, []);
      map.get(parent).push(tag);
    });
    for (const list of map.values()) list.sort((a, b) => (a.seq || 0) - (b.seq || 0));
    return map;
  }

  function taxonomyRowHtml(tag, options = {}) {
    const depth = Number(options.depth || 0);
    const children = options.children || [];
    const hasChildren = children.length > 0;
    const expanded = state.tax.expanded.has(tag.id);
    const isActive = state.tax.tagId === tag.id;
    const seq = options.code || String(tag.seq || options.index || 1).padStart(2, "0");
    return `<div class="taxonomy-row ${hasChildren ? "tree-parent" : ""} ${isActive ? "active" : ""}" data-tax-id="${attr(tag.id)}" style="padding-left:${13 + depth * 18}px">
      <button class="tax-arrow ${hasChildren ? "" : "empty"} ${expanded ? "open" : ""}" ${hasChildren ? `data-tax-toggle="${attr(tag.id)}"` : ""} aria-label="${hasChildren ? "展开子风格" : ""}" aria-expanded="${expanded}">${hasChildren ? icon("chevron") : ""}</button>
      <span class="taxonomy-seq">${seq}</span>
      <div class="taxonomy-name"><strong>${escapeHtml(tag.zh)}</strong><span>${escapeHtml(tag.en)}${tag.category === "Genre" ? ` · L${tag.genre_level || 1}` : ""}</span></div>
      <span class="taxonomy-group">${hasChildren ? `${children.length} 子级` : escapeHtml(tag.group || tag.category)}</span>
    </div>${hasChildren && expanded ? children.map((child, index) => taxonomyRowHtml(child, { depth: depth + 1, code: `${seq}.${String(index + 1).padStart(2, "0")}`, children: (genreChildrenMap().get(child.id) || []) })).join("") : ""}`;
  }

  function renderGenreTree(tags) {
    const list = $("#taxonomy-list");
    const children = genreChildrenMap();
    const roots = tags.filter((tag) => !tag.genre_parent_id);
    const expandedCount = tags.filter((tag) => state.tax.expanded.has(tag.id)).length;
    $("#tax-count").textContent = `${tags.length} tags · ${roots.length} 个一级风格${expandedCount ? ` · 已展开 ${expandedCount}` : ""}`;
    if (!roots.length) {
      list.innerHTML = `<div class="taxonomy-empty">没有匹配的标签。</div>`;
      return;
    }
    list.innerHTML = roots
      .map((tag, index) => taxonomyRowHtml(tag, { code: String(index + 1).padStart(2, "0"), children: children.get(tag.id) || [] }))
      .join("");
  }

  function renderTaxonomyRows() {
    const list = $("#taxonomy-list");
    if (!list) return;
    const tags = filteredTaxonomy();
    if (!tags.length) {
      $("#tax-count").textContent = "0 tags";
      list.innerHTML = `<div class="taxonomy-empty">没有匹配的标签。</div>`;
      return;
    }
    if (state.tax.category === "Genre" && !state.tax.query.trim()) {
      renderGenreTree(tags);
      return;
    }
    $("#tax-count").textContent = `${tags.length} tags`;
    list.innerHTML = tags
      .map(
        (tag, index) => `<div class="taxonomy-row ${state.tax.tagId === tag.id ? "active" : ""}" data-tax-id="${attr(tag.id)}">
          <button class="tax-arrow empty" aria-hidden="true"></button>
          <span class="taxonomy-seq">${String(tag.seq || index + 1).padStart(2, "0")}</span>
          <div class="taxonomy-name"><strong>${escapeHtml(tag.zh)}</strong><span>${escapeHtml(tag.en)}${tag.category === "Genre" ? ` · L${tag.genre_level || 1}` : ""}</span></div>
          <span class="taxonomy-group">${escapeHtml(tag.group || tag.category)}</span>
        </div>`
      )
      .join("");
  }

  function renderTaxonomyDetail() {
    const root = $("#taxonomy-detail");
    if (!root) return;
    const tags = filteredTaxonomy();
    if (!state.tax.tagId && tags.length) state.tax.tagId = tags[0].id;
    const tag = (state.taxonomy?.tags || []).find((item) => item.id === state.tax.tagId);
    if (!tag) {
      root.innerHTML = `<div class="taxonomy-empty">选择一个标签，查看定义、特征与别名。</div>`;
      return;
    }
    const category = state.taxonomy.categories[tag.category] || {};
    const lineage = (tag.genre_lineage || []).map((id) => (state.taxonomy.tags || []).find((item) => item.id === id)).filter(Boolean);
    const pathHtml = tag.category === "Genre" && lineage.length
      ? `<div class="taxonomy-lineage">${lineage.map((item, index) => `<span class="taxonomy-path-step ${item.id === tag.id ? "current" : ""}"><b>L${item.genre_level || index + 1}</b> ${escapeHtml(item.zh)}</span>${index < lineage.length - 1 ? icon("chevron") : ""}`).join("")}</div>`
      : "";
    root.innerHTML = `
      <div class="eyebrow"><span class="status-dot"></span> ${escapeHtml(category.label_zh || tag.category)} / ${escapeHtml(tag.group || "未分组")} · #${tag.seq || 1}</div>
      <h2>${escapeHtml(tag.zh)}</h2>
      <div class="en">${escapeHtml(tag.en)} · ${tag.category === "Genre" ? `L${tag.genre_level || 1}` : escapeHtml(category.label_en || tag.category)}</div>
      ${pathHtml}
      <div class="definition">${escapeHtml(tag.definition || "该标签没有额外定义，按名称与所属分组使用。")}</div>
      ${tag.features ? `<div class="features">${escapeHtml(tag.features)}</div>` : ""}
      ${tag.sentiment && tag.sentiment !== "/" ? `<div class="features">情绪倾向：${escapeHtml(tag.sentiment)}</div>` : ""}
      ${tag.aliases?.length ? `<div class="aliases">${tag.aliases.slice(0, 10).map((alias) => `<span class="tag">${escapeHtml(alias)}</span>`).join("")}</div>` : ""}
      <div class="divider-h"></div>
      <div class="taxonomy-internal">展示序号 #${tag.seq || 1} · 内部稳定 ID <code>${escapeHtml(tag.id)}</code></div>
      <div class="taxonomy-mini-foot"><span>${escapeHtml(category.description || "")}</span></div>`;
  }

  // ------------------------------------------------------------------ activity
  async function refreshActivity() {
    const level = state.activityLevel ? `&level=${encodeURIComponent(state.activityLevel)}` : "";
    const data = await api(`/activity?limit=250${level}`);
    state.activity = data.items || [];
  }

  function renderActivityPage() {
    const items = state.activity || [];
    $("#view").innerHTML = `
      <div class="page-head">
        <div><div class="eyebrow"><span class="status-dot"></span> OBSERVABILITY / ACTIVITY</div><h1>活动流</h1><p>端点启停、批次状态、模型调用与失败重试。工作台后台发生的每一件事，都应该能被看见。</p></div>
        <div class="head-actions">
          <select class="select" id="activity-level"><option value="">全部级别</option><option value="error" ${state.activityLevel === "error" ? "selected" : ""}>仅错误</option><option value="warn" ${state.activityLevel === "warn" ? "selected" : ""}>仅警告</option></select>
          <button class="btn" data-action="refresh-activity">${icon("refresh")}刷新</button>
        </div>
      </div>
      <div class="activity-list">${items.length ? items.map(renderActivityRow).join("") : `<div class="batch-empty">${icon("pulse")}<strong>还没有活动记录</strong><p>创建批次后，这里会显示处理过程。</p></div>`}</div>`;
    $("#activity-level").addEventListener("change", (event) => {
      state.activityLevel = event.target.value;
      refreshActivity().then(renderActivityPage);
    });
  }

  function renderActivityRow(event) {
    const level = event.level || "info";
    const iconName = event.kind?.includes("fail") || level === "error" ? "alert" : event.kind?.includes("pause") || level === "warn" ? "pause-circle" : event.kind?.includes("complete") ? "check" : "pulse";
    return `<div class="activity-row">
      <span class="activity-time">${timeOnly(event.created_at)}</span>
      <span class="activity-icon ${level === "error" ? "error" : level === "warn" ? "warn" : "ok"}">${icon(iconName)}</span>
      <div class="activity-message">${escapeHtml(event.message)}${event.batch_id ? `<small><a href="#/batch/${attr(event.batch_id)}" style="color:var(--accent)">${escapeHtml(event.batch_id)}</a>${event.item_id ? ` · ${escapeHtml(event.item_id)}` : ""}</small>` : ""}</div>
      <span class="activity-tag">${escapeHtml(event.kind || "event")}</span>
    </div>`;
  }

  // ------------------------------------------------------------------ settings
  function renderSettingsPage() {
    const draft = state.settingsDraft || state.settings;
    if (!draft) return;
    const tabs = [
      ["workspace", "工作区", "grid"],
      ["endpoints", "推理端点", "cloud"],
      ["models", "文字模型", "bot"],
      ["processing", "处理与能力", "cpu"],
      ["data", "数据与安全", "database"],
      ["about", "关于声刻", "spark"],
    ];
    $("#view").innerHTML = `
      <div class="page-head">
        <div><div class="eyebrow"><span class="status-dot"></span> SYSTEM / SETTINGS</div><h1>设置与连接</h1><p>密钥保存在本机操作系统凭据库。切换模型、管理端点生命周期，或调整批处理策略。</p></div>
        <div class="head-actions"><button class="btn primary" data-action="save-settings">${icon("check")}保存设置</button></div>
      </div>
      <div class="settings-layout">
        <nav class="settings-nav">${tabs.map(([key, label, ic]) => `<button class="${state.settingsTab === key ? "active" : ""}" data-action="settings-tab" data-tab="${key}">${icon(ic)}${label}</button>`).join("")}</nav>
        <div class="settings-content" id="settings-content">${renderSettingsContent(draft)}</div>
      </div>
      <div class="save-bar ${state.settingsDirty ? "" : "hidden"}" id="save-bar"><span>有未保存的更改</span><button class="btn small" data-action="reset-settings">重置更改</button><button class="btn small primary" data-action="save-settings">${icon("check")}保存设置</button></div>`;
  }

  function renderSettingsContent(draft) {
    if (state.settingsTab === "workspace") return renderWorkspaceSettings(draft);
    if (state.settingsTab === "models") return renderModelSettings(draft);
    if (state.settingsTab === "processing") return renderProcessingSettings(draft);
    if (state.settingsTab === "data") return renderDataSettings(draft);
    if (state.settingsTab === "about") return renderAboutSettings(draft);
    return renderEndpointSettings(draft);
  }

  function settingSwitch(path, label, description, value) {
    return `<div class="switch-row"><div class="switch-copy"><strong>${label}</strong><span>${description}</span></div><button class="switch ${value ? "on" : ""}" data-action="toggle-setting" data-path="${attr(path)}" aria-label="${attr(label)}" aria-pressed="${value ? "true" : "false"}"></button></div>`;
  }

  function renderWorkspaceSettings(draft) {
    const workspace = draft.workspace || {};
    return `
      <div class="settings-head"><div><h2>工作区</h2><p>名称与每日目标只影响工作台展示与进度节奏，不会限制并发或模型能力。</p></div></div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("grid")}</div><div><h3>工作区信息</h3><p>会显示在左侧工作区切换器与总览中。</p></div></div>
        <div class="form-grid">
          <div class="field"><label>工作区名称</label><input data-path="workspace.name" value="${attr(workspace.name || "")}"></div>
          <div class="field"><label>负责人 / 团队（可选）</label><input data-path="workspace.owner" value="${attr(workspace.owner || "")}"></div>
        </div>
      </div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("pulse")}</div><div><h3>每日目标</h3><p>随时可改，例如 100、300、500、1000。目标不是产能保证。</p></div></div>
        <div class="form-grid">
          <div class="field"><label>每天计划完成（首）</label><input type="number" min="1" max="10000" step="1" data-path="workspace.daily_goal" value="${attr(workspace.daily_goal || 500)}"></div>
          <div class="field"><label>当前产能提示</label><input value="根据真实单首耗时调整" disabled></div>
        </div>
        <p class="route-note">${icon("clock")}总览的 Daily runway 会立即使用这个数字；实际完成量取决于端点、音频长度与重试。</p>
      </div>`;
  }

  function renderEndpointSettings(draft) {
    const inference = draft.inference;
    return `
      <div class="settings-head"><div><h2>推理端点</h2><p>每个模型是一个独立路由。A10G 24GB 建议并发 1，并通过自定义容器暴露 /health 与 /v1/annotate。</p></div><button class="btn small" data-action="add-inference-route">${icon("plus")}添加端点</button></div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("key")}</div><div><h3>Hugging Face 访问令牌</h3><p>用于管理端点状态、调用私有端点。令牌仅加密保存在本机。</p></div><div class="right"><button class="btn small" data-action="test-hf">${icon("cloud")}验证令牌</button></div></div>
        <div class="secret-row"><div class="field" style="flex:1"><label>HF TOKEN</label><input type="password" data-secret="hf_token" placeholder="${draft.secrets_meta?.stored_names?.includes("hf_token") ? "已保存，留空表示不修改" : "hf_xxxxxxxxxxxxxxxxxxxx"}"></div><span class="secret-status">${inference.routes.some((r) => r.secret_configured) ? `${icon("check")}已加密` : "未保存"}</span></div>
        <p class="route-note">${icon("shield")}需要 Inference Endpoints 的读取与管理权限。若只调用已部署的公网 URL，可只填 URL 并保留令牌。</p>
      </div>
      ${inference.routes.map((route) => renderInferenceRoute(route, draft)).join("")}
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("clock")}</div><div><h3>费用守卫</h3><p>队列开始时自动恢复端点；空闲后排空并暂停，避免按小时待机计费。</p></div></div>
        ${settingSwitch("inference.lifecycle.auto_resume", "自动恢复端点", "提交批次时，如果端点为 paused 或 scaledToZero，自动调用 resume 并等待健康检查通过。", inference.lifecycle.auto_resume)}
        ${settingSwitch("inference.lifecycle.auto_pause", "空闲自动暂停", "最后一个任务完成且超过宽限期后，自动暂停端点。新批次会自动恢复。", inference.lifecycle.auto_pause)}
        <div class="form-grid" style="margin-top:12px">
          <div class="field"><label>暂停宽限期（秒）</label><input type="number" min="0" max="3600" data-path="inference.lifecycle.pause_grace_seconds" value="${attr(inference.lifecycle.pause_grace_seconds)}"></div>
          <div class="field"><label>恢复超时（秒）</label><input type="number" min="60" max="3600" data-path="inference.lifecycle.resume_timeout_seconds" value="${attr(inference.lifecycle.resume_timeout_seconds)}"></div>
        </div>
      </div>`;
  }

  function renderInferenceRoute(route, draft) {
    const active = draft.inference.active_route_id === route.id;
    const status = state.endpoint?.route_id === route.id ? state.endpoint : null;
    const profileId = route.hardware_profile || "custom";
    const profile = state.hardwareProfiles.find((item) => item.id === profileId) || state.hardwareProfiles.find((item) => item.id === "custom") || {};
    return `<div class="route-card ${active ? "active" : ""}">
      <div class="route-card-head">
        <button class="route-radio" data-action="activate-inference-route" data-id="${attr(route.id)}" aria-label="设为主端点" title="设为当前端点"></button>
        <strong>${escapeHtml(route.name || "未命名端点")}</strong><span class="route-model">${escapeHtml(route.model || "")}</span>
        <div class="right">
          ${status ? `<span class="badge ${status.state === "running" ? "completed" : status.state === "paused" ? "paused" : "neutral"}">${escapeHtml(status.state_label)}</span>` : `<span class="badge neutral">待检查</span>`}
          <button class="btn small" data-action="test-endpoint" data-id="${attr(route.id)}">${icon("pulse")}测试</button>
          <button class="btn small" data-action="remove-inference-route" data-id="${attr(route.id)}">${icon("trash")}</button>
        </div>
      </div>
      <div class="route-form">
        <div class="field"><label>显示名称</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="name" value="${attr(route.name)}"></div>
        <div class="field"><label>模型仓库</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="model" value="${attr(route.model)}" placeholder="OpenMOSS-Team/MOSS-Music-8B-Instruct"></div>
        <div class="field"><label>适配器</label><select data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="adapter"><option value="cadence" ${route.adapter === "cadence" ? "selected" : ""}>Cadence custom /v1/annotate</option><option value="openai_audio" ${route.adapter === "openai_audio" ? "selected" : ""}>OpenAI-compatible audio</option></select></div>
        <div class="field"><label>最大并发</label><input type="number" min="1" max="8" data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="max_concurrency" value="${attr(route.max_concurrency || 1)}"></div>
        <div class="field span-2"><label>硬件预设 · 仅用于推荐参数</label><div class="secret-row"><select data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="hardware_profile" style="flex:1">${state.hardwareProfiles.map((item) => `<option value="${attr(item.id)}" ${item.id === profileId ? "selected" : ""}>${escapeHtml(item.label)}${item.reference_price_usd_hour ? ` · ~$${item.reference_price_usd_hour}/h` : ""}</option>`).join("")}</select><button class="btn small" data-action="apply-hardware-profile" data-id="${attr(route.id)}">${icon("spark")}应用推荐</button></div><p class="route-note">${icon("cpu")}${escapeHtml(profile.note || "")}${profile.recommended_concurrency ? ` 建议并发 ${profile.recommended_concurrency} · 音频 ≤${profile.recommended_max_audio_seconds}s · ${escapeHtml(profile.verdict || "")}` : ""}</p></div>
        <div class="field"><label>HF NAMESPACE</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="hf_namespace" value="${attr(route.hf_namespace)}" placeholder="你的用户名或组织"></div>
        <div class="field"><label>HF ENDPOINT NAME</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="hf_endpoint_name" value="${attr(route.hf_endpoint_name)}" placeholder="moss-music-a10g"></div>
        <div class="field span-2"><label>INFERENCE URL（可留空，由 HF API 解析）</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="base_url" value="${attr(route.base_url)}" placeholder="https://xxxxx.us-east-1.aws.endpoints.huggingface.cloud"></div>
        <div class="field"><label>标注路径</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="infer_path" value="${attr(route.infer_path || "/v1/annotate")}"></div>
        <div class="field"><label>健康检查路径</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="health_path" value="${attr(route.health_path || "/health")}"></div>
        <div class="field"><label>超时（秒）</label><input type="number" min="30" max="3600" data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="timeout_seconds" value="${attr(route.timeout_seconds || 900)}"></div>
        <div class="field"><label>音频上限（秒）</label><input type="number" min="10" max="1200" data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="max_audio_seconds" value="${attr(route.max_audio_seconds || 1200)}"></div>
        <div class="field"><label>最大输出 tokens</label><input type="number" min="128" max="4096" data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="max_new_tokens" value="${attr(route.max_new_tokens || 900)}"></div>
        <div class="field span-2"><label>端点 API 密钥（留空不修改）</label><input type="password" data-secret="${attr(route.api_key_secret || "hf_token")}" placeholder="${route.secret_configured ? "已保存 · " + route.secret_hint : "可复用 HF Token"}"></div>
        <div class="field span-2"><label>备注</label><input data-route-kind="inference" data-route-id="${attr(route.id)}" data-field="notes" value="${attr(route.notes || "")}" placeholder="模型版本、硬件、已知限制"></div>
      </div>
      <div style="display:flex;gap:6px;margin-top:9px;flex-wrap:wrap">
        ${settingSwitch(`inference.routes.${route.id}.enabled`, "启用此路由", "停用后不会出现在新批次的路由选择中。", route.enabled !== false)}
        <button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="resume">${icon("play")}Resume</button>
        <button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="pause">${icon("pause")}Pause</button>
        <button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="scale-to-zero">${icon("cloud")}Scale to zero</button>
      </div>
      <p class="route-note">${icon("shield")}${escapeHtml(route.notes || "自定义容器必须监听平台端口，提供健康路径，并在 /v1/annotate 接收 multipart 音频。")}</p>
    </div>`;
  }

  function renderModelSettings(draft) {
    const llm = draft.llm;
    return `
      <div class="settings-head"><div><h2>文字模型</h2><p>只接收音频模型产生的文字与元数据，不上传音频。用于标签映射、结构校验与最终 JSON。</p></div><button class="btn small" data-action="add-llm-route">${icon("plus")}添加模型</button></div>
      ${llm.routes.map((route) => renderLlmRoute(route, draft)).join("")}
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("shield")}</div><div><h3>规范化策略</h3><p>控制目录大小、近似映射与置信度。越严格的策略越可审计，但可能丢弃模型观察。</p></div></div>
        ${settingSwitch("llm.normalization.strict_taxonomy", "严格标签模式", "只允许目录内 ID；不在目录中的标签进入 unmapped，不污染主结果。", llm.normalization.strict_taxonomy)}
        ${settingSwitch("llm.normalization.allow_approximate_mapping", "允许语义近似映射", "例如 Modal Jazz → Cool Jazz；结果会标记 mapped=true 并保留原始说法。", llm.normalization.allow_approximate_mapping)}
        ${settingSwitch("llm.normalization.include_confidence", "包含逐标签置信度", "所有标签输出 0–1 置信度，便于抽样复核。", llm.normalization.include_confidence)}
        <div class="form-grid" style="margin-top:12px">
          <div class="field"><label>目录最大字符数</label><input type="number" min="4000" max="120000" step="1000" data-path="llm.normalization.max_catalog_chars" value="${attr(llm.normalization.max_catalog_chars)}"></div>
          <div class="field"><label>JSON 修复次数</label><input type="number" min="0" max="3" data-path="llm.normalization.repair_attempts" value="${attr(llm.normalization.repair_attempts ?? 1)}"></div>
        </div>
      </div>`;
  }

  function renderLlmRoute(route, draft) {
    const active = draft.llm.active_route_id === route.id;
    return `<div class="route-card ${active ? "active" : ""}">
      <div class="route-card-head"><button class="route-radio" data-action="activate-llm-route" data-id="${attr(route.id)}" aria-label="设为当前文字模型"></button><strong>${escapeHtml(route.name || "未命名模型")}</strong><span class="route-model">${escapeHtml(route.model || "")}</span><div class="right"><span class="badge ${route.secret_configured || route.base_url?.includes("localhost") ? "completed" : "neutral"}">${route.secret_configured ? "已配置密钥" : "未保存密钥"}</span><button class="btn small" data-action="test-llm" data-id="${attr(route.id)}">${icon("pulse")}测试</button><button class="btn small" data-action="remove-llm-route" data-id="${attr(route.id)}">${icon("trash")}</button></div></div>
      <div class="route-form">
        <div class="field"><label>显示名称</label><input data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="name" value="${attr(route.name)}"></div>
        <div class="field"><label>模型名</label><input list="deepseek-models" data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="model" value="${attr(route.model)}" placeholder="deepseek-flash"><datalist id="deepseek-models"><option value="deepseek-flash"><option value="deepseek-v4-pro"></datalist></div>
        <div class="field span-2"><label>BASE URL</label><input data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="base_url" value="${attr(route.base_url)}" placeholder="https://api.deepseek.com"></div>
        <div class="field"><label>API KEY（留空不修改）</label><input type="password" data-secret="${attr(route.api_key_secret || "deepseek_api_key")}" placeholder="${route.secret_configured ? "已保存 · " + route.secret_hint : "sk-..."}"></div>
        <div class="field"><label>思考模式</label><select data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="thinking_mode"><option value="disabled" ${route.thinking_mode !== "enabled" ? "selected" : ""}>关闭（推荐 · 更快）</option><option value="enabled" ${route.thinking_mode === "enabled" ? "selected" : ""}>开启（更慢，输出推理）</option></select></div>
        <div class="field"><label>TEMPERATURE</label><input type="number" min="0" max="1.5" step="0.05" data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="temperature" value="${attr(route.temperature)}"></div>
        <div class="field"><label>MAX TOKENS</label><input type="number" min="256" max="16000" data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="max_tokens" value="${attr(route.max_tokens)}"></div>
        <div class="field"><label>超时（秒）</label><input type="number" min="30" max="1200" data-route-kind="llm" data-route-id="${attr(route.id)}" data-field="timeout_seconds" value="${attr(route.timeout_seconds || 240)}"></div>
      </div>
      <p class="route-note">${icon("bot")}DeepSeek 当前模型名是 <strong>deepseek-flash</strong>（V4.1 Flash）或 <strong>deepseek-v4-pro</strong>；API Key 不决定模型类型。默认关闭思考以降低延迟，JSON 模式负责结构化输出。</p>
    </div>`;
  }

  function renderProcessingSettings(draft) {
    const p = draft.processing;
    return `
      <div class="settings-head"><div><h2>处理与能力</h2><p>吞吐与稳定性的平衡。A10G 单卡建议同时只跑 1 个音频模型请求。</p></div></div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("pulse")}</div><div><h3>队列</h3><p>并行项目数与失败重试。过高的并发会让 8B 音频模型争抢显存。</p></div></div>
        <div class="form-grid three">
          <div class="field"><label>全局并行项目</label><input type="number" min="1" max="8" data-path="processing.max_parallel_items" value="${attr(p.max_parallel_items)}"></div>
          <div class="field"><label>最大尝试次数</label><input type="number" min="1" max="6" data-path="processing.max_attempts" value="${attr(p.max_attempts)}"></div>
          <div class="field"><label>重试退避（秒）</label><input type="number" min="1" max="120" data-path="processing.retry_backoff_seconds" value="${attr(p.retry_backoff_seconds)}"></div>
        </div>
      </div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("wave")}</div><div><h3>音频预处理</h3><p>原文件保留；上传副本转为紧凑 MP3，减少请求体与冷启动传输时间。</p></div></div>
        ${settingSwitch("processing.transcode", "转码上传副本", "使用 ffmpeg 生成 44.1kHz / 双声道 / 96kbps 的 MP3；原始文件不修改。", p.transcode)}
        <div class="form-grid">
          <div class="field"><label>转码码率</label><input data-path="processing.transcode_bitrate" value="${attr(p.transcode_bitrate)}" placeholder="96k"></div>
          <div class="field"><label>单文件上限（MB）</label><input type="number" min="10" max="4096" data-path="processing.max_upload_mb" value="${attr(p.max_upload_mb)}"></div>
          <div class="field"><label>单批文件上限</label><input type="number" min="1" max="5000" data-path="processing.max_items_per_batch" value="${attr(p.max_items_per_batch)}"></div>
        </div>
      </div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("tag")}</div><div><h3>标签与导出</h3><p>标签版本随批次冻结；导出默认包含原始与规范化两条轨道。</p></div></div>
        <div class="form-grid">
          <div class="field"><label>标签版本</label><input value="${attr(state.taxonomy?.version || "")}" disabled></div>
          <div class="field"><label>标签数</label><input value="${state.taxonomy?.source?.label_count || 641}" disabled></div>
        </div>
      </div>`;
  }

  function renderDataSettings(draft) {
    const meta = state.settings?.secrets_meta || {};
    return `
      <div class="settings-head"><div><h2>数据与安全</h2><p>所有音频、结果、SQLite 与密钥都留在本机。默认只监听 127.0.0.1。</p></div><button class="btn small" data-action="backup-db">${icon("database")}备份数据库</button></div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("folder")}</div><div><h3>本地数据目录</h3><p>音频原件、转码副本、数据库与导出文件。</p></div></div>
        <div class="info-grid">
          <div class="info-box"><span>DATA DIRECTORY</span><strong>${escapeHtml(meta.data_dir || "—")}</strong></div>
          <div class="info-box"><span>SECRET STORAGE</span><strong>${meta.secure_storage ? "Windows DPAPI · 已加密" : "开发模式 · 文件权限保护"}</strong></div>
          <div class="info-box"><span>DATABASE</span><strong>SQLite · WAL</strong></div>
          <div class="info-box"><span>BIND</span><strong>127.0.0.1 · 仅本机</strong></div>
        </div>
      </div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("spark")}</div><div><h3>演示数据</h3><p>四首本地生成的原创合成音频，用于熟悉界面；结果明确标记为 DEMO。</p></div><div class="right"><button class="btn small" data-action="seed-demo">${icon("plus")}载入演示批次</button></div></div>
      </div>
      <div class="setting-card">
        <div class="setting-card-head"><div class="setting-card-icon">${icon("shield")}</div><div><h3>安全边界</h3><p>这是一个本机单用户工作台，不应直接暴露到公网。</p></div></div>
        <p class="route-note">${icon("check")}HTTP 服务仅接受 Host 为 localhost / 127.0.0.1 的请求，并拒绝跨站写请求。<br>${icon("check")}API Key 使用 Windows DPAPI 加密，绑定当前用户与电脑。<br>${icon("check")}音频与模型结果不进入 Git 仓库；导出前请自行确认版权与隐私。</p>
      </div>`;
  }

  function renderAboutSettings(draft) {
    return `
      <div class="settings-head"><div><h2>关于声刻</h2><p>为可审计的音乐数据生产而设计。</p></div><span class="badge neutral">v0.2.0</span></div>
      <div class="taxonomy-hero" style="grid-template-columns:1fr;padding:28px">
        <div>
          <div class="brand" style="margin-bottom:16px"><span class="brand-mark"><svg><use href="#i-logo"></use></svg></span><div class="brand-word"><strong>Cadence</strong><span>声刻 · STUDIO</span></div></div>
          <h1 style="font-size:30px;max-width:620px">声音值得一套<br>比表格更聪明的秩序。</h1>
          <p style="margin-top:12px">本工作台把音频理解模型、标签治理、批量队列与交付导出放进一个本地界面。音频理解可替换，规范化规则与标签版本始终可追溯。</p>
        </div>
      </div>
      <div class="setting-card" style="margin-top:12px">
        <div class="info-grid">
          <div class="info-box"><span>VERSION</span><strong>0.2.0</strong></div>
          <div class="info-box"><span>TAXONOMY</span><strong>${escapeHtml(state.taxonomy?.version || "")}</strong></div>
          <div class="info-box"><span>DEFAULT AUDIO MODEL</span><strong>MOSS-Music 8B / Music Flamingo</strong></div>
          <div class="info-box"><span>NORMALIZER</span><strong>DeepSeek / OpenAI-compatible</strong></div>
        </div>
        <div class="divider-h"></div>
        <p class="route-note">${icon("alert")}Music Flamingo 权重标注为 NVIDIA 非商业研究许可；商业使用前请自行核对许可与服务条款。模型输出和映射结果仍需人工抽检。</p>
      </div>`;
  }

  function updateDraftFromInput(event) {
    const target = event.target;
    if (!state.settingsDraft) return;
    if (target.dataset.routeKind) {
      const kind = target.dataset.routeKind;
      const collection = kind === "inference" ? state.settingsDraft.inference.routes : state.settingsDraft.llm.routes;
      const route = collection.find((item) => item.id === target.dataset.routeId);
      if (!route) return;
      const value = target.type === "number" ? Number(target.value) : target.value;
      route[target.dataset.field] = value;
      state.settingsDirty = true;
      return;
    }
    if (target.dataset.path) {
      let value = target.value;
      if (target.type === "number") value = Number(value);
      setPath(state.settingsDraft, target.dataset.path, value);
      state.settingsDirty = true;
    }
  }

  function collectSecrets() {
    const secrets = {};
    $$("[data-secret]").forEach((input) => {
      if (input.value.trim()) secrets[input.dataset.secret] = input.value.trim();
    });
    return secrets;
  }

  function cleanSettingsDraft(draft) {
    const cleaned = deepClone(draft);
    delete cleaned.secrets_meta;
    for (const section of ["inference", "llm"]) {
      (cleaned[section]?.routes || []).forEach((route) => {
        delete route.secret_configured;
        delete route.secret_hint;
        delete route.management_configured;
        delete route.resolved_url;
      });
    }
    return cleaned;
  }

  function applyHardwareProfile(routeId) {
    if (!state.settingsDraft) return;
    const route = state.settingsDraft.inference.routes.find((item) => item.id === routeId);
    if (!route) return;
    const profile = state.hardwareProfiles.find((item) => item.id === route.hardware_profile) || state.hardwareProfiles.find((item) => item.id === "custom");
    if (!profile) return;
    route.max_concurrency = profile.recommended_concurrency;
    route.max_audio_seconds = profile.recommended_max_audio_seconds;
    route.max_new_tokens = profile.recommended_max_new_tokens;
    route.timeout_seconds = profile.recommended_timeout_seconds;
    state.settingsDirty = true;
    renderSettingsPage();
    toast(`${profile.label}：并发 ${profile.recommended_concurrency} · 音频 ≤${profile.recommended_max_audio_seconds}s · 超时 ${profile.recommended_timeout_seconds}s。`, {
      title: "已应用硬件推荐",
      type: "success",
    });
  }

  async function saveSettings() {
    try {
      const data = await api("/settings", {
        method: "PUT",
        body: { config: cleanSettingsDraft(state.settingsDraft), secrets: collectSecrets() },
      });
      state.settings = data;
      state.settingsDraft = deepClone(data);
      state.settingsDirty = false;
      renderShell();
      renderSettingsPage();
      refreshEndpointStatus(true);
      toast("设置已保存到本机。", { title: "设置已更新" });
    } catch (error) {
      toast(error.message, { type: "error", title: "保存失败" });
    }
  }

  // ------------------------------------------------------------------ new batch
  function openNewBatch(files = null) {
    if (!state.settings) return;
    state.upload = {
      files: [],
      busy: false,
      progress: 0,
      modules: new Set(state.modules.filter((m) => m.default).map((m) => m.id)),
      advanced: false,
      metrics: null,
      autoStart: true,
    };
    if (files) setUploadFiles(files, false);
    const route = state.settings.inference.routes.find((r) => r.id === state.settings.inference.active_route_id) || {};
    const llm = state.settings.llm.routes.find((r) => r.id === state.settings.llm.active_route_id) || {};
    $("#modal-root").innerHTML = `
      <div class="modal-backdrop" data-action="close-modal">
        <div class="modal wide" role="dialog" aria-modal="true" aria-label="新建标注批次">
          <div class="modal-head">
            <div><div class="eyebrow"><span class="status-dot"></span> NEW BATCH</div><h2>新建标注批次</h2><p>导入音频，只选择这次真正需要的字段。越少的模块，越快的处理。</p></div>
            <button class="drawer-close" data-action="close-modal" aria-label="关闭">${icon("x")}</button>
          </div>
          <div class="modal-body">
            <div class="form-section">
              <div class="form-section-head"><span class="step-num">01</span><strong>音频</strong><small>批量拖入，系统自动去重并读取时长</small></div>
              <div class="dropzone" id="batch-dropzone" tabindex="0" role="button">
                ${icon("upload")}<strong>拖入音频，或点击选择文件</strong><span>MP3 · WAV · FLAC · M4A · OGG · 单批最多 ${state.settings.processing.max_items_per_batch || 1000} 个</span>
                <input type="file" id="batch-files" accept="audio/*,.mp3,.wav,.flac,.m4a,.aac,.ogg,.opus" multiple hidden>
              </div>
              <div class="file-picked-list hidden" id="file-picked-list"></div>
            </div>
            <div class="form-section">
              <div class="form-section-head"><span class="step-num">02</span><strong>批次信息</strong><small>便于以后定位与交付</small></div>
              <div class="form-grid">
                <div class="field"><label>批次名称</label><input id="batch-name" placeholder="例如：Q4 广告音乐 · 第一批" value=""></div>
                <div class="field"><label>备注（可选）</label><input id="batch-note" placeholder="供应商、用途、审听标准…"></div>
              </div>
            </div>
            <div class="form-section">
              <div class="form-section-head"><span class="step-num">03</span><strong>需要模型输出什么</strong><small>只输出选中的模块</small></div>
              <div class="module-grid" id="module-grid">${renderModuleToggles()}</div>
            </div>
            <div class="form-section">
              <div class="form-section-head"><span class="step-num">04</span><strong>输出选项</strong><small>规范标签与语言</small></div>
              <div class="form-grid three">
                <div class="field"><label>自然语言</label><select id="batch-language"><option value="zh">简体中文</option><option value="en">English</option><option value="bilingual">中英双语 Caption</option></select></div>
                <div class="field"><label>Caption 长度</label><select id="caption-length"><option value="short">短 · 2–3 句</option><option value="medium" selected>中 · 4–6 句</option><option value="long">长 · 8–12 句</option></select></div>
                <div class="field"><label>标签策略</label><select id="taxonomy-mode"><option value="strict">严格映射（推荐）</option><option value="open">优先映射，保留原词</option></select></div>
              </div>
              <div class="advanced-toggle" id="advanced-toggle" data-action="toggle-advanced">${icon("chevron")}额外要求 / 自定义字段</div>
              <div class="advanced-panel hidden" id="advanced-panel">
                <div class="field"><label>额外提示词（会同时影响音频模型与规范化）</label><textarea id="custom-instruction" placeholder="例如：重点判断是否适合 15 秒短视频卡点；Caption 要提到情绪转折。"></textarea></div>
                <div class="field" style="margin-top:9px"><label>自定义输出字段（逗号分隔，可选）</label><input id="custom-fields" placeholder="sync_suitability, trailer_moment"></div>
              </div>
            </div>
            <div class="estimate-bar">
              <span>${icon("cpu")}音频模型 <strong>${escapeHtml(route.name || "未选择")}</strong></span>
              <span>${icon("bot")}规范模型 <strong>${escapeHtml(llm.name || "未选择")}</strong></span>
              <span class="divider"></span>
              <span id="batch-metric">${icon("tag")}正在计算目录上下文…</span>
            </div>
            <div class="progress-upload hidden" id="upload-progress">
              <div class="progress-track"><i class="done" id="upload-bar" style="width:0"></i></div>
              <div class="upload-status"><span id="upload-status-text">准备上传…</span><span id="upload-percent">0%</span></div>
            </div>
            <div class="alert hidden" id="upload-error" style="margin-top:10px"></div>
          </div>
          <div class="modal-footer">
            <label style="display:flex;align-items:center;gap:6px;margin-right:auto;font-size:9.5px;color:var(--faint)"><input class="checkbox" type="checkbox" id="auto-start" checked>创建后立即开始</label>
            <button class="btn" data-action="close-modal">取消</button>
            <button class="btn primary" data-action="submit-batch" id="submit-batch">${icon("arrow-right")}创建批次</button>
          </div>
        </div>
      </div>`;
    const input = $("#batch-files");
    input.addEventListener("change", (event) => setUploadFiles(event.target.files));
    const dropzone = $("#batch-dropzone");
    dropzone.addEventListener("click", () => input.click());
    dropzone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") input.click();
    });
    dropzone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
      setUploadFiles(event.dataTransfer.files);
    });
    $("#module-grid").addEventListener("click", (event) => {
      const button = event.target.closest("[data-module]");
      if (!button) return;
      const id = button.dataset.module;
      if (state.upload.modules.has(id)) {
        if (state.upload.modules.size === 1) {
          toast("至少保留一个标注模块。", { type: "warn" });
          return;
        }
        state.upload.modules.delete(id);
      } else {
        state.upload.modules.add(id);
        if (id === "custom") {
          state.upload.advanced = true;
          $("#advanced-panel")?.classList.remove("hidden");
          $("#advanced-toggle")?.classList.add("open");
        }
      }
      button.classList.toggle("active", state.upload.modules.has(id));
      updateBatchMetrics();
    });
    $("#advanced-toggle").addEventListener("click", () => {
      state.upload.advanced = !state.upload.advanced;
      $("#advanced-toggle").classList.toggle("open", state.upload.advanced);
      $("#advanced-panel").classList.toggle("hidden", !state.upload.advanced);
    });
    $("#batch-name").addEventListener("input", () => {});
    if (files) setUploadFiles(files, false);
    updateBatchMetrics();
  }

  function moduleIcon(id) {
    return (
      {
        caption: "caption",
        genre: "genre",
        mood: "mood",
        bpm_key: "tempo",
        instruments: "instrument",
        structure: "structure",
        scene: "scene",
        vocal: "vocal",
        language: "language",
        lyrics: "lyrics",
        production: "production",
        quality: "quality",
        safety: "shield",
        extra: "tag",
        custom: "custom",
      }[id] || "tag"
    );
  }

  function renderModuleToggles() {
    return state.modules
      .map((module) => `<button type="button" class="module-toggle ${state.upload.modules.has(module.id) ? "active" : ""}" data-module="${attr(module.id)}"><span class="module-icon">${icon(moduleIcon(module.id))}</span><span><strong>${escapeHtml(module.label_zh)}</strong><small>${escapeHtml(module.description)}</small></span></button>`)
      .join("");
  }

  function setUploadFiles(fileList, announce = true) {
    const incoming = Array.from(fileList || []).filter((file) => {
      const name = file.name.toLowerCase();
      return /\.(mp3|wav|flac|m4a|aac|ogg|opus|wma|aiff|aif|mp4|webm)$/.test(name);
    });
    if (!incoming.length) {
      if (announce) toast("没有可导入的音频文件。", { type: "warn" });
      return;
    }
    const max = Number(state.settings?.processing?.max_items_per_batch || 1000);
    const combined = [...state.upload.files, ...incoming];
    state.upload.files = combined.slice(0, max);
    if (combined.length > max) toast(`已截断到单批上限 ${max} 个文件。`, { type: "warn" });
    renderPickedFiles();
    const nameInput = $("#batch-name");
    if (nameInput && !nameInput.value.trim() && state.upload.files.length) {
      const stamp = new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date()).replace("/", "-");
      nameInput.value = `${stamp} 音乐标注 · ${state.upload.files.length} 首`;
    }
  }

  function renderPickedFiles() {
    const list = $("#file-picked-list");
    if (!list) return;
    if (!state.upload.files.length) {
      list.classList.add("hidden");
      return;
    }
    list.classList.remove("hidden");
    list.innerHTML = state.upload.files
      .map(
        (file, index) => `<div class="file-picked">${icon("music")}<span class="name">${escapeHtml(file.name)}</span><span class="size">${bytes(file.size)}</span><button type="button" class="remove" data-remove-file="${index}" aria-label="移除">${icon("x")}</button></div>`
      )
      .join("");
    list.querySelectorAll("[data-remove-file]").forEach((button) => {
      button.addEventListener("click", () => {
        state.upload.files.splice(Number(button.dataset.removeFile), 1);
        renderPickedFiles();
      });
    });
  }

  function localPromptMetrics(modules) {
    const categories = new Set();
    modules.forEach((module) => {
      if (module === "genre") {
        categories.add("Genre");
        categories.add("Extra");
      } else if (module === "extra") {
        categories.add("Extra");
      } else {
        const map = { mood: "Mood", scene: "Scene", instruments: "Instrument", vocal: "Vocal", language: "Language" };
        if (map[module]) categories.add(map[module]);
      }
    });
    let tags = 0;
    let chars = 0;
    (state.taxonomy?.tags || []).forEach((tag) => {
      if (!categories.has(tag.category)) return;
      tags += 1;
      chars += tag.id.length + tag.zh.length + tag.en.length + (tag.group || "").length + 8;
      if (tag.category === "Genre") chars += 18; // hierarchy hint in catalog
    });
    return { taxonomy_tags: tags, normalizer_tokens_estimate: Math.ceil((chars + 2800) / 2.2) };
  }

  async function updateBatchMetrics() {
    const target = $("#batch-metric");
    if (!target) return;
    const modules = [...state.upload.modules];
    const local = localPromptMetrics(modules);
    target.innerHTML = `${icon("tag")}目录 <strong>${local.taxonomy_tags}</strong> 标签 · 规范化上下文约 <strong>${Math.ceil(local.normalizer_tokens_estimate / 1000)}k</strong> tokens`;
    try {
      const data = await api(`/settings/prompt-metrics?modules=${encodeURIComponent(modules.join(","))}`);
      state.upload.metrics = data.metrics;
      if ($("#batch-metric")) {
        target.innerHTML = `${icon("tag")}目录 <strong>${data.metrics.taxonomy_tags || local.taxonomy_tags}</strong> 标签 · 规范化上下文约 <strong>${Math.ceil(data.metrics.normalizer_tokens_estimate / 1000)}k</strong> tokens`;
      }
    } catch (error) {
      // Local estimate is intentional: the modal must never get stuck on a
      // slow settings request.
    }
  }

  function buildBatchSpec() {
    const fields = $("#custom-fields")?.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean) || [];
    return {
      modules: [...state.upload.modules],
      language: $("#batch-language")?.value || "zh",
      caption_length: $("#caption-length")?.value || "medium",
      structure_detail: "sections",
      lyrics_timestamps: false,
      include_confidence: true,
      taxonomy_mode: $("#taxonomy-mode")?.value || "strict",
      custom_instruction: $("#custom-instruction")?.value.trim() || "",
      custom_fields: fields,
      audio_model_prompt: "",
      output_language_note: "",
    };
  }

  async function submitBatch() {
    if (state.upload.busy) return;
    if (!state.upload.files.length) {
      showUploadError("请先选择至少一个音频文件。");
      return;
    }
    const spec = buildBatchSpec();
    if (state.upload.modules.has("custom") && !spec.custom_instruction && !spec.custom_fields.length) {
      showUploadError("选择了自定义模块，但没有填写额外要求或字段。");
      return;
    }
    state.upload.busy = true;
    $("#submit-batch").disabled = true;
    $("#submit-batch").innerHTML = `${icon("refresh", "spin")}上传并创建…`;
    const bar = $("#upload-progress");
    bar.classList.remove("hidden");
    const form = new FormData();
    state.upload.files.forEach((file) => form.append("files", file));
    form.append("name", $("#batch-name")?.value.trim() || "");
    form.append("note", $("#batch-note")?.value.trim() || "");
    form.append("spec", JSON.stringify(spec));
    form.append("auto_start", $("#auto-start")?.checked ? "true" : "false");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/batches");
    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      state.upload.progress = percent;
      $("#upload-bar").style.width = `${percent}%`;
      $("#upload-percent").textContent = `${percent}%`;
      $("#upload-status-text").textContent = percent >= 100 ? "服务器正在读取音频…" : "正在上传音频…";
    });
    xhr.addEventListener("load", async () => {
      state.upload.busy = false;
      $("#submit-batch").disabled = false;
      $("#submit-batch").innerHTML = `${icon("arrow-right")}创建批次`;
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (error) {}
      if (xhr.status >= 200 && xhr.status < 300) {
        const warnings = data.warnings || [];
        closeModal();
        await refreshOverview();
        await refreshSidebarBatches();
        nav(`#/batch/${data.batch.id}`);
        toast(
          warnings.length ? `已导入 ${data.imported} 首，${warnings.length} 条提示。` : `已导入 ${data.imported} 首音频。`,
          { title: data.batch.status === "queued" || data.batch.status === "running" ? "批次已进入队列" : "批次已创建", type: warnings.length ? "warn" : "success", duration: 6000 }
        );
        if (warnings.length) console.warn("Batch import warnings", warnings);
      } else {
        const detail = data.detail;
        showUploadError(detail?.message || data.message || `上传失败（HTTP ${xhr.status}）`);
        $("#submit-batch").disabled = false;
        $("#submit-batch").innerHTML = `${icon("arrow-right")}创建批次`;
      }
    });
    xhr.addEventListener("error", () => {
      state.upload.busy = false;
      $("#submit-batch").disabled = false;
      $("#submit-batch").innerHTML = `${icon("arrow-right")}创建批次`;
      showUploadError("上传中断，请检查工作台是否仍在运行。");
    });
    xhr.send(form);
  }

  function showUploadError(message) {
    const el = $("#upload-error");
    if (!el) return;
    el.classList.remove("hidden");
    el.innerHTML = `${icon("alert")}${escapeHtml(message)}`;
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeModal() {
    $("#modal-root").innerHTML = "";
    state.upload.busy = false;
  }

  // ---------------------------------------------------------------- endpoint panel
  async function openEndpointPanel() {
    const route = state.settings?.inference.routes.find((r) => r.id === state.settings.inference.active_route_id);
    if (!route) return;
    state.endpoint = null;
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal-backdrop" data-action="close-modal"><div class="modal" style="width:min(520px,94vw)" role="dialog"><div class="modal-head"><div><div class="eyebrow">ENDPOINT LIFECYCLE</div><h2>${escapeHtml(route.name)}</h2><p>${escapeHtml(route.model)}</p></div><button class="drawer-close" data-action="close-modal">${icon("x")}</button></div><div class="modal-body" id="endpoint-panel-body"><div class="skeleton-line"></div><div class="skeleton-line"></div></div></div></div>`;
    await refreshEndpointStatus(true).catch(() => {});
    const endpoint = state.endpoint || {};
    const running = endpoint.state === "running";
    $("#endpoint-panel-body").innerHTML = `
      <div class="endpoint-hero" style="margin-bottom:14px"><div class="endpoint-orbit ${running ? "running" : ""}">${icon("cloud")}</div><div class="endpoint-state-block"><div class="endpoint-state-label"><span class="status-dot ${running ? "ok" : endpoint.state === "paused" ? "warning" : "error"}"></span>${escapeHtml(endpoint.state_label || "状态未知")}</div><strong>${escapeHtml(route.model || "")}</strong><small>${escapeHtml(endpoint.url || route.base_url || "还没有解析到 Inference URL")}</small></div></div>
      ${endpoint.error ? `<div class="alert" style="margin-bottom:12px">${icon("alert")}${escapeHtml(endpoint.error)}</div>` : ""}
      <div class="meta-list">
        <div class="meta-row"><span>路由</span><strong>${escapeHtml(route.id)}</strong></div>
        <div class="meta-row"><span>适配器</span><strong>${escapeHtml(route.adapter)}</strong></div>
        <div class="meta-row"><span>HF 管理</span><strong>${route.hf_namespace && route.hf_endpoint_name ? `${escapeHtml(route.hf_namespace)} / ${escapeHtml(route.hf_endpoint_name)}` : "仅 URL 模式"}</strong></div>
        <div class="meta-row"><span>自动恢复</span><strong>${state.settings.inference.lifecycle.auto_resume ? "开启" : "关闭"}</strong></div>
        <div class="meta-row"><span>空闲暂停</span><strong>${state.settings.inference.lifecycle.auto_pause ? `${state.settings.inference.lifecycle.pause_grace_seconds}s 后` : "关闭"}</strong></div>
        <div class="meta-row"><span>并发</span><strong>${route.max_concurrency || 1}</strong></div>
        <div class="meta-row"><span>检查时间</span><strong>${dateLabel(endpoint.checked_at)}</strong></div>
      </div>
      <div class="alert warn" style="margin-top:12px">${icon("clock")}冷启动通常需要数分钟。恢复操作会立即返回，之后由工作台轮询健康检查。Pause 不收费但保留配额；Scale to zero 需在 HF 端点开启。</div>`;
    const head = root.querySelector(".modal-head");
    if (head) {
      const actions = document.createElement("div");
      actions.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;padding:0 21px 12px;";
      actions.innerHTML = `<button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="resume">${icon("play")}Resume</button><button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="pause">${icon("pause")}Pause</button><button class="btn small" data-action="endpoint-action" data-id="${attr(route.id)}" data-op="scale-to-zero">${icon("cloud")}Scale to zero</button><button class="btn small" data-action="test-endpoint" data-id="${attr(route.id)}">${icon("pulse")}健康检查</button>`;
      head.after(actions);
    }
  }

  // --------------------------------------------------------------------- batch actions
  async function doBatchAction(action, batchId = state.batch?.id) {
    if (!batchId) return;
    if ($("#modal-root .modal") && !["batch-delete"].includes(action)) closeModal();
    try {
      if (action === "batch-delete") {
        const ok = await confirmDialog("删除批次？", "批次记录、原始音频和所有结果都会被删除，无法恢复。", "删除");
        if (!ok) return;
        await api(`/batches/${batchId}`, { method: "DELETE" });
        toast("批次已删除。", { title: "已删除" });
        await refreshOverview();
        await refreshSidebarBatches();
        nav("#/batches");
        return;
      }
      const endpoints = {
        "batch-start": "start",
        "batch-pause": "pause",
        "batch-resume": "resume",
        "batch-cancel": "cancel",
        "batch-retry": "retry-failed",
      };
      const endpoint = endpoints[action];
      if (!endpoint) {
        if (action === "batch-rename") {
          const current = state.batch?.name || "";
          const name = window.prompt("新的批次名称", current);
          if (!name || name.trim() === current) return;
          await api(`/batches/${batchId}`, { method: "PATCH", body: { name: name.trim() } });
          toast("批次名称已更新。");
          await reloadBatchData();
          await refreshSidebarBatches();
          return;
        }
        if (action === "batch-refresh") {
          await reloadBatchData();
          toast("批次状态已刷新。", { duration: 1600 });
          return;
        }
        return;
      }
      await api(`/batches/${batchId}/${endpoint}`, { method: "POST" });
      toast(
        action === "batch-pause" ? "正在处理的音频会完成，其余项目暂停。" : action === "batch-start" ? "批次已加入队列。" : "操作已提交。",
        { title: "批次已更新" }
      );
      await reloadBatchData();
      await refreshOverview();
    } catch (error) {
      toast(error.message, { type: "error", title: "批次操作失败" });
    }
  }

  function openBatchMenu() {
    closeModal();
    const batch = state.batch;
    if (!batch) return;
    $("#modal-root").innerHTML = `<div class="modal-backdrop" data-action="close-modal"><div class="modal" style="width:min(390px,94vw)"><div class="modal-head"><div><h2>批次操作</h2><p>${escapeHtml(batch.name)}</p></div><button class="drawer-close" data-action="close-modal">${icon("x")}</button></div><div class="modal-body" style="padding:8px"><button class="palette-item" data-action="batch-rename" style="width:100%">${icon("edit")}<span>重命名批次</span></button><button class="palette-item" data-action="batch-refresh" style="width:100%">${icon("refresh")}<span>刷新状态</span></button><button class="palette-item" data-action="batch-cancel" style="width:100%">${icon("x")}<span>取消未处理项目</span></button><button class="palette-item" data-action="batch-delete" style="width:100%;color:var(--danger)">${icon("trash")}<span>删除整个批次</span></button></div></div></div>`;
  }

  function openExportDialog() {
    const batch = state.batch;
    if (!batch) return;
    $("#modal-root").innerHTML = `<div class="modal-backdrop" data-action="close-modal"><div class="modal" style="width:min(480px,94vw)"><div class="modal-head"><div><h2>导出批次</h2><p>包含原始模型输出、规范化 JSON、标签映射与结构时间轴。</p></div><button class="drawer-close" data-action="close-modal">${icon("x")}</button></div><div class="modal-body" style="padding:12px">
      ${[
        ["xlsx", "Excel 工作簿", "适合交付与人工复核，含标注总表、原始输出、结构、映射"],
        ["json", "JSON 数据包", "完整结构化结果，含每个标签的来源与置信度"],
        ["md", "Markdown 报告", "可直接审阅的批次报告，保留每个曲目的原始观察"],
        ["csv", "CSV 平表", "一行一首，适合导入 BI 或数据表格"],
        ["zip", "完整 ZIP 包", "JSON + XLSX + MD + CSV + 标签体系快照"],
      ].map(([fmt, label, desc]) => `<button class="palette-item" style="width:100%;align-items:flex-start;padding:10px" data-action="download-export" data-format="${fmt}">${icon("download")}<span><strong style="display:block;font-size:11px;color:var(--text)">${label}</strong><small style="display:block;margin-top:2px;font-family:var(--font-sans);font-size:9px;color:var(--faint);white-space:normal">${desc}</small></span></button>`).join("")}
    </div></div></div>`;
  }

  function downloadExport(fmt) {
    if (!state.batch) return;
    window.location.href = `/api/batches/${encodeURIComponent(state.batch.id)}/export?format=${encodeURIComponent(fmt)}`;
    closeModal();
    toast("正在生成导出文件，浏览器会自动下载。", { title: "开始导出" });
  }

  // ------------------------------------------------------------------ palette
  function openPalette() {
    const root = $("#palette-root");
    state.palette.open = true;
    state.palette.index = 0;
    root.innerHTML = `<div class="palette-backdrop" data-action="close-palette"><div class="palette" role="dialog" aria-modal="true"><div class="palette-input">${icon("search")}<input id="palette-input" placeholder="搜索批次、页面或操作…" autocomplete="off"><kbd>ESC</kbd></div><div class="palette-results" id="palette-results"></div><div class="palette-foot"><span>↑↓ 移动</span><span>↵ 选择</span><span>ESC 关闭</span></div></div></div>`;
    renderPalette("");
    const input = $("#palette-input");
    input.addEventListener("input", () => renderPalette(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        state.palette.index = Math.min(state.palette.items.length - 1, state.palette.index + 1);
        updatePaletteActive();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        state.palette.index = Math.max(0, state.palette.index - 1);
        updatePaletteActive();
      } else if (event.key === "Enter") {
        event.preventDefault();
        const item = state.palette.items[state.palette.index];
        if (item) executePaletteItem(item);
      }
    });
    setTimeout(() => input.focus(), 20);
  }

  function renderPalette(query) {
    const q = query.trim().toLowerCase();
    const actions = [
      { kind: "action", label: "新建标注批次", icon: "plus", hint: "N", run: () => openNewBatch() },
      { kind: "action", label: "总览", icon: "grid", hint: "G O", run: () => nav("#/overview") },
      { kind: "action", label: "全部批次", icon: "layers", run: () => nav("#/batches") },
      { kind: "action", label: "标签体系", icon: "tag", run: () => nav("#/taxonomy") },
      { kind: "action", label: "活动流", icon: "pulse", run: () => nav("#/activity") },
      { kind: "action", label: "设置", icon: "settings", run: () => nav("#/settings") },
      { kind: "action", label: "切换主题", icon: "sun", run: () => toggleTheme() },
      { kind: "action", label: "载入演示批次", icon: "spark", run: () => seedDemo() },
      { kind: "action", label: "端点状态", icon: "cloud", run: () => openEndpointPanel() },
    ].filter((item) => !q || item.label.toLowerCase().includes(q));
    const batches = (state.batches || state.sidebarBatches || [])
      .filter((batch) => !q || batch.name.toLowerCase().includes(q) || batch.id.includes(q))
      .slice(0, 8)
      .map((batch) => ({
        kind: "batch",
        label: batch.name,
        hint: statusLabel(batch.status),
        icon: "layers",
        run: () => nav(`#/batch/${batch.id}`),
      }));
    state.palette.items = [...actions, ...batches];
    if (state.palette.index >= state.palette.items.length) state.palette.index = 0;
    const root = $("#palette-results");
    if (!root) return;
    const grouped = [["操作", actions], ["批次", batches]].filter(([, items]) => items.length);
    let flatIndex = 0;
    root.innerHTML = grouped
      .map(
        ([label, items]) => `<div class="palette-group-label">${label}</div>${items
          .map((item) => {
            const index = flatIndex++;
            return `<button class="palette-item ${index === state.palette.index ? "active" : ""}" data-palette-index="${index}">${icon(item.icon)}<span>${escapeHtml(item.label)}</span><small>${escapeHtml(item.hint || "")}</small></button>`;
          })
          .join("")}`
      )
      .join("");
    $$("[data-palette-index]", root).forEach((button) => {
      button.addEventListener("mouseenter", () => {
        state.palette.index = Number(button.dataset.paletteIndex);
        updatePaletteActive();
      });
      button.addEventListener("click", () => executePaletteItem(state.palette.items[Number(button.dataset.paletteIndex)]));
    });
  }

  function updatePaletteActive() {
    $$("[data-palette-index]").forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.paletteIndex) === state.palette.index);
    });
  }

  function executePaletteItem(item) {
    if (!item) return;
    closePalette();
    setTimeout(() => item.run(), 20);
  }

  function closePalette() {
    state.palette.open = false;
    $("#palette-root").innerHTML = "";
  }

  function openGoalDialog() {
    if (!state.overview) return;
    const current = Number(state.overview.daily_goal || state.settings?.workspace?.daily_goal || 500);
    $("#modal-root").innerHTML = `<div class="modal-backdrop" data-action="close-modal"><div class="modal" style="width:min(450px,94vw)" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="eyebrow">DAILY TARGET</div><h2>修改每日目标</h2><p>目标只影响进度展示与节奏，不会改变模型或队列容量。</p></div><button class="drawer-close" data-action="close-modal">${icon("x")}</button></div><div class="modal-body"><div class="field"><label>每天计划完成的音频数</label><input id="daily-goal-input" type="number" min="1" max="10000" value="${current}" autofocus></div><div class="tag-row" style="margin-top:10px">${[100, 300, 500, 800, 1000].map((n) => `<button class="tag" data-action="set-goal-preset" data-goal="${n}" style="cursor:pointer">${n} 首</button>`).join("")}</div><p class="route-note" style="margin-top:12px">${icon("clock")}单卡实际产能取决于模型、音频长度与端点冷启动；目标不是承诺。</p></div><div class="modal-footer"><button class="btn" data-action="close-modal">取消</button><button class="btn primary" data-action="save-goal">${icon("check")}保存目标</button></div></div></div>`;
    setTimeout(() => $("#daily-goal-input")?.select(), 50);
  }

  async function saveGoal() {
    const value = Number($("#daily-goal-input")?.value || 0);
    if (!Number.isInteger(value) || value < 1 || value > 10000) {
      toast("请输入 1–10000 之间的整数。", { type: "warn", title: "目标无效" });
      return;
    }
    try {
      const data = await api("/workspace", { method: "PATCH", body: { daily_goal: value } });
      if (state.settings?.workspace) state.settings.workspace.daily_goal = value;
      if (state.overview) state.overview.daily_goal = value;
      closeModal();
      await refreshOverview();
      if (state.route.name === "overview") renderOverview();
      toast(`每日目标已改为 ${num(value)} 首。`, { title: "目标已更新" });
    } catch (error) {
      toast(error.message, { type: "error", title: "保存目标失败" });
    }
  }

  async function seedDemo() {
    try {
      const data = await api("/demo/seed", { method: "POST" });
      await refreshOverview();
      await refreshSidebarBatches();
      closeModal();
      toast("演示批次已创建。结果为明确标记的示例数据。", { title: "演示已载入" });
      nav(`#/batch/${data.batch.id}`);
    } catch (error) {
      toast(error.message, { type: "error", title: "载入演示失败" });
    }
  }

  // ------------------------------------------------------------------- events
  function bindGlobalEvents() {
    document.addEventListener("click", async (event) => {
      const paletteItem = event.target.closest("[data-palette-index]");
      if (paletteItem) return;
      const actionEl = event.target.closest("[data-action]");
      if (!actionEl) {
        const openBatchRow = event.target.closest("[data-open-batch]");
        if (openBatchRow) nav(`#/batch/${openBatchRow.dataset.openBatch}`);
        return;
      }
      const action = actionEl.dataset.action;
      if (action === "close-modal" && event.target !== actionEl && !actionEl.classList.contains("drawer-close")) return;
      if (action === "close-drawer" && event.target !== actionEl && !actionEl.classList.contains("drawer-close")) return;
      if (action === "close-palette" && event.target !== actionEl) return;
      if (action === "open-batch") {
        const id = actionEl.dataset.id || event.target.closest("[data-id]")?.dataset.id;
        if (id) nav(`#/batch/${id}`);
        return;
      }
      if (action === "open-item") {
        if (event.target.closest("input, button, a, [data-item-select]")) return;
        event.stopPropagation();
        const id = actionEl.dataset.id;
        if (id) openItem(id);
        return;
      }
      if (action === "select-all") {
        state.selected = event.target.checked ? new Set(state.items.map((item) => item.id)) : new Set();
        $$("[data-item-select]").forEach((box) => {
          box.checked = event.target.checked;
        });
        return;
      }
      switch (action) {
        case "toggle-theme":
          toggleTheme();
          return;
        case "reload":
          location.reload();
          return;
        case "new-batch":
          openNewBatch();
          return;
        case "close-modal":
          closeModal();
          return;
        case "close-drawer":
          closeDrawer();
          return;
        case "close-palette":
          closePalette();
          return;
        case "open-sidebar":
          $("#sidebar").classList.add("open");
          return;
        case "close-sidebar":
          $("#sidebar").classList.remove("open");
          return;
        case "command":
          openPalette();
          return;
        case "open-settings":
          nav("#/settings");
          return;
        case "refresh-overview":
          await refreshOverview();
          renderOverview();
          toast("总览已刷新。", { duration: 1500 });
          return;
        case "refresh-batches":
          await refreshBatches();
          renderBatchesPage();
          return;
        case "refresh-batch":
          await reloadBatchData();
          toast("批次已刷新。", { duration: 1500 });
          return;
        case "refresh-activity":
          await refreshActivity();
          renderActivityPage();
          return;
        case "seed-demo":
          await seedDemo();
          return;
        case "edit-goal":
          openGoalDialog();
          return;
        case "set-goal-preset": {
          const input = $("#daily-goal-input");
          if (input) input.value = actionEl.dataset.goal;
          return;
        }
        case "save-goal":
          await saveGoal();
          return;
        case "apply-hardware-profile":
          applyHardwareProfile(actionEl.dataset.id);
          return;
        case "tax-expand-all": {
          const all = (state.taxonomy?.tags || []).filter((tag) => tag.category === "Genre");
          state.tax.expanded = new Set(all.filter((tag) => all.some((child) => child.genre_parent_id === tag.id)).map((tag) => tag.id));
          renderTaxonomyRows();
          return;
        }
        case "tax-collapse-all":
          state.tax.expanded = new Set();
          renderTaxonomyRows();
          return;
        case "endpoint-panel":
          await openEndpointPanel();
          return;
        case "endpoint-quick-resume": {
          const route = state.settings?.inference.routes.find((r) => r.id === state.settings.inference.active_route_id);
          if (!route) return;
          const op = state.endpoint?.state === "running" ? "pause" : "resume";
          await endpointAction(route.id, op);
          return;
        }
        case "endpoint-action":
          await endpointAction(actionEl.dataset.id, actionEl.dataset.op);
          return;
        case "test-endpoint":
          await testEndpoint(actionEl.dataset.id);
          return;
        case "test-hf":
          await testHfToken();
          return;
        case "test-llm":
          await testLlm(actionEl.dataset.id);
          return;
        case "batch-pause":
        case "batch-resume":
        case "batch-start":
        case "batch-retry":
        case "batch-cancel":
        case "batch-delete":
        case "batch-rename":
        case "batch-refresh":
          await doBatchAction(action);
          return;
        case "batch-menu":
          openBatchMenu();
          return;
        case "batch-export":
          openExportDialog();
          return;
        case "download-export":
          downloadExport(actionEl.dataset.format);
          return;
        case "load-more-items":
          await loadMoreItems();
          return;
        case "item-retry":
          await retryItem(actionEl.dataset.id || state.drawer?.id, actionEl.dataset.mode || "full");
          return;
        case "review-item":
          await reviewItem(actionEl.dataset.value);
          return;
        case "item-download":
          if (state.drawer) window.location.href = `/api/items/${encodeURIComponent(state.drawer.id)}/export?format=${actionEl.dataset.format || "json"}`;
          return;
        case "toggle-play": {
          const audio = state.drawer?.audio;
          if (!audio) return;
          if (audio.paused) audio.play().catch(() => toast("浏览器无法播放这个音频格式。", { type: "warn" }));
          else audio.pause();
          return;
        }
        case "seek-audio":
          return;
        case "drawer-tab":
          if (!state.drawer) return;
          state.drawer.tab = actionEl.dataset.tab;
          $$(".drawer-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === state.drawer.tab));
          const body = $("#drawer-body");
          if (body) body.innerHTML = renderDrawerBody();
          return;
        case "copy-code": {
          const pre = actionEl.closest(".code-block")?.querySelector("pre");
          if (!pre) return;
          await copyText(pre.textContent || "");
          return;
        }
        case "settings-tab":
          state.settingsTab = actionEl.dataset.tab;
          renderSettingsPage();
          return;
        case "toggle-setting": {
          const path = actionEl.dataset.path;
          const current = Boolean(getPath(state.settingsDraft, path));
          setPath(state.settingsDraft, path, !current);
          state.settingsDirty = true;
          actionEl.classList.toggle("on", !current);
          actionEl.setAttribute("aria-pressed", String(!current));
          $("#save-bar")?.classList.remove("hidden");
          return;
        }
        case "save-settings":
          await saveSettings();
          return;
        case "reset-settings":
          state.settingsDraft = deepClone(state.settings);
          state.settingsDirty = false;
          renderSettingsPage();
          toast("未保存的更改已重置。", { duration: 1600 });
          return;
        case "add-inference-route":
          addRoute("inference");
          return;
        case "add-llm-route":
          addRoute("llm");
          return;
        case "remove-inference-route":
          await removeRoute("inference", actionEl.dataset.id);
          return;
        case "remove-llm-route":
          await removeRoute("llm", actionEl.dataset.id);
          return;
        case "activate-inference-route":
          state.settingsDraft.inference.active_route_id = actionEl.dataset.id;
          state.settingsDirty = true;
          renderSettingsPage();
          return;
        case "activate-llm-route":
          state.settingsDraft.llm.active_route_id = actionEl.dataset.id;
          state.settingsDirty = true;
          renderSettingsPage();
          return;
        case "backup-db":
          await backupDatabase();
          return;
        case "submit-batch":
          await submitBatch();
          return;
        case "toggle-advanced":
          return;
        default:
          break;
      }
    });

    document.addEventListener("input", (event) => {
      const target = event.target;
      if (target.matches("[data-route-kind], [data-path]")) {
        updateDraftFromInput(event);
        $("#save-bar")?.classList.remove("hidden");
      }
      if (target.matches("[data-item-select]")) {
        if (target.checked) state.selected.add(target.dataset.itemSelect);
        else state.selected.delete(target.dataset.itemSelect);
      }
    });

    document.addEventListener("change", (event) => {
      const target = event.target;
      if (target.matches("[data-route-kind], [data-path]")) updateDraftFromInput(event);
    });

    window.addEventListener("hashchange", route);

    document.addEventListener("keydown", (event) => {
      const tag = (event.target.tagName || "").toLowerCase();
      const typing = ["input", "textarea", "select"].includes(tag);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (state.palette.open) closePalette();
        else openPalette();
        return;
      }
      if (event.key === "Escape") {
        if (state.palette.open) closePalette();
        else if ($("#modal-root").innerHTML) closeModal();
        else if (state.drawer) closeDrawer();
        else $("#sidebar").classList.remove("open");
        return;
      }
      if (typing) return;
      if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        openNewBatch();
      } else if (event.key === "/") {
        event.preventDefault();
        openPalette();
      }
    });

    document.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types?.includes("Files")) {
        event.preventDefault();
        $("#drop-overlay").classList.add("visible");
      }
    });
    document.addEventListener("dragleave", (event) => {
      if (!event.relatedTarget) $("#drop-overlay").classList.remove("visible");
    });
    document.addEventListener("drop", (event) => {
      event.preventDefault();
      $("#drop-overlay").classList.remove("visible");
      const files = event.dataTransfer?.files;
      if (!files || !files.length) return;
      if ($("#modal-root .modal")) {
        setUploadFiles(files);
      } else {
        openNewBatch(files);
      }
    });

  }

  async function endpointAction(routeId, op) {
    if (!routeId || !op) return;
    try {
      toast(op === "resume" ? "正在请求 Hugging Face 恢复端点…" : op === "pause" ? "正在暂停端点…" : "正在请求缩容…", { title: "端点操作", duration: 2600 });
      await api(`/inference/${encodeURIComponent(routeId)}/${op}`, { method: "POST" });
      await refreshEndpointStatus(true);
      if ($("#endpoint-panel-body")) await openEndpointPanel();
      renderShell();
      toast("云端已接受请求。状态可能需要几秒才更新。", { title: "端点已更新" });
    } catch (error) {
      toast(error.message, { type: "error", title: "端点操作失败" });
    }
  }

  async function testEndpoint(routeId) {
    try {
      const data = await api(`/inference/${encodeURIComponent(routeId)}/test`, { method: "POST" });
      state.endpoint = { ...data, route_id: routeId, state: data.state, state_label: data.state_label };
      updateEndpointUI();
      toast(data.ok ? `端点可访问 · ${data.state_label}` : data.message || "端点不可访问", { type: data.ok ? "success" : "warn", title: "端点检查" });
    } catch (error) {
      toast(error.message, { type: "error", title: "端点不可用" });
    }
  }

  async function testHfToken() {
    try {
      const data = await api("/settings/test/hf", { method: "POST" });
      toast(`已连接 Hugging Face：${data.name || data.fullname || "已验证"}`, { title: "令牌有效" });
    } catch (error) {
      toast(error.message, { type: "error", title: "令牌验证失败" });
    }
  }

  async function testLlm(routeId) {
    try {
      const data = await api("/settings/test/llm", { method: "POST", body: { route_id: routeId || null } });
      toast(`模型响应正常 · ${data.latency_ms} ms`, { title: "文字模型可用" });
    } catch (error) {
      toast(error.message, { type: "error", title: "文字模型测试失败" });
    }
  }

  function addRoute(kind) {
    if (!state.settingsDraft) return;
    const stamp = Date.now().toString(36).slice(-5);
    if (kind === "inference") {
      const id = `endpoint-${stamp}`;
      state.settingsDraft.inference.routes.push({
        id,
        name: "新推理端点",
        provider: "huggingface",
        adapter: "cadence",
        model: "",
        base_url: "",
        hf_namespace: "",
        hf_endpoint_name: "",
        health_path: "/health",
        infer_path: "/v1/annotate",
        api_key_secret: "hf_token",
        hardware_profile: "custom",
        max_concurrency: 1,
        timeout_seconds: 900,
        max_audio_seconds: 1200,
        max_new_tokens: 900,
        enabled: true,
        notes: "",
      });
      state.settingsDraft.inference.active_route_id = id;
    } else {
      const id = `llm-${stamp}`;
      state.settingsDraft.llm.routes.push({
        id,
        name: "新文字模型",
        provider: "openai_compatible",
        base_url: "https://api.deepseek.com",
        model: "deepseek-flash",
        api_key_secret: `llm_${stamp}_key`,
        temperature: 0.1,
        max_tokens: 4096,
        timeout_seconds: 240,
        json_mode: true,
        thinking_mode: "disabled",
        enabled: true,
      });
      state.settingsDraft.llm.active_route_id = id;
    }
    state.settingsDirty = true;
    renderSettingsPage();
  }

  async function removeRoute(kind, id) {
    if (!state.settingsDraft) return;
    const collection = kind === "inference" ? state.settingsDraft.inference.routes : state.settingsDraft.llm.routes;
    if (collection.length <= 1) {
      toast("至少保留一个路由。", { type: "warn" });
      return;
    }
    const ok = await confirmDialog("删除这个路由？", "该操作会移除当前表单中的路由，保存后生效。已存在的批次仍保留其快照。", "删除");
    if (!ok) return;
    const index = collection.findIndex((route) => route.id === id);
    collection.splice(index, 1);
    if (kind === "inference" && state.settingsDraft.inference.active_route_id === id) {
      state.settingsDraft.inference.active_route_id = collection[0].id;
    }
    if (kind === "llm" && state.settingsDraft.llm.active_route_id === id) {
      state.settingsDraft.llm.active_route_id = collection[0].id;
    }
    state.settingsDirty = true;
    renderSettingsPage();
  }

  async function backupDatabase() {
    try {
      const data = await api("/system/backup", { method: "POST" });
      toast(data.path ? `备份已写入 ${data.path}` : "数据库尚未创建，无需备份。", { title: "备份完成" });
    } catch (error) {
      toast(error.message, { type: "error", title: "备份失败" });
    }
  }

  async function loadMoreItems() {
    if (!state.batch) return;
    try {
      const offset = state.items.length;
      const params = new URLSearchParams({ limit: "200", offset: String(offset), sort: state.filters.itemSort });
      if (state.filters.itemQuery) params.set("query", state.filters.itemQuery);
      if (state.filters.itemStatus) params.set("status", state.filters.itemStatus);
      const data = await api(`/batches/${state.batch.id}/items?${params}`);
      state.items = [...state.items, ...(data.items || [])];
      state.itemsTotal = data.total || state.itemsTotal;
      renderBatchPage();
    } catch (error) {
      toast(error.message, { type: "error" });
    }
  }

  async function retryItem(itemId, mode) {
    if (!itemId) return;
    try {
      await api(`/items/${encodeURIComponent(itemId)}/retry`, {
        method: "POST",
        body: { normalize_only: mode === "normalize" },
      });
      toast(mode === "normalize" ? "已仅重新运行规范化，复用音频模型原始输出。" : "已重新加入完整处理队列。", { title: "重试已排队" });
      closeDrawer();
      await reloadBatchData();
      await refreshOverview();
    } catch (error) {
      toast(error.message, { type: "error", title: "重试失败" });
    }
  }

  async function reviewItem(value) {
    if (!state.drawer) return;
    try {
      const item = await api(`/items/${encodeURIComponent(state.drawer.id)}`, {
        method: "PATCH",
        body: { review_status: value },
      });
      state.drawer.item = item;
      renderDrawer();
      toast(value === "approved" ? "已标记为人工通过。" : "已标记为需要修改。", { title: "复核已记录" });
    } catch (error) {
      toast(error.message, { type: "error", title: "复核失败" });
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("已复制到剪贴板。", { duration: 1600 });
    } catch (error) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
      toast("已复制到剪贴板。", { duration: 1600 });
    }
  }

  // --------------------------------------------------------------------- SSE
  function connectSSE() {
    if (!window.EventSource) return;
    const source = new EventSource(`/api/events/stream?since_id=${state.lastEventId}`);
    let reconnectTimer = null;
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        state.lastEventId = Math.max(state.lastEventId, data.id || 0);
        handleLiveEvent(data);
      } catch (error) {}
    };
    source.onerror = () => {
      setServerHealth(false);
      source.close();
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connectSSE();
        }, 4000);
      }
    };
    source.onopen = () => setServerHealth(true);
  }

  function handleLiveEvent(event) {
    if (state.route.name === "activity") {
      if (!state.activity.some((item) => item.id === event.id)) {
        state.activity.unshift(event);
        if (state.activity.length > 250) state.activity.pop();
        renderActivityPage();
      }
    }
    if (state.route.name === "batch" && event.batch_id === state.batch?.id) {
      scheduleLiveRefresh();
    }
    if (["item_failed", "batch_state", "endpoint_auto_paused", "endpoint_pause_failed"].includes(event.kind)) {
      // Keep failures visible without flooding the user for every track.
      if (event.level === "error") toast(event.message, { type: "error", title: "任务失败", duration: 6000 });
    }
    if (event.kind === "endpoint_auto_paused" || event.kind === "endpoint_ready") {
      refreshEndpointStatus(true);
    }
    if (state.route.name === "overview" && ["item_completed", "batch_created", "batch_started"].includes(event.kind)) {
      refreshOverview().then(() => {
        if (state.route.name === "overview") renderOverview();
      });
    }
  }

  function scheduleLiveRefresh() {
    if (state.liveTimer) return;
    state.liveTimer = setTimeout(async () => {
      state.liveTimer = null;
      try {
        await reloadBatchData(true);
      } catch (error) {}
    }, 900);
  }

  function debounce(fn, wait) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  // --------------------------------------------------------------------- start
  window.addEventListener("DOMContentLoaded", boot);
})();
