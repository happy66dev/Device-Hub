/* device-hub 控制台前端：原生 JS，无任何第三方依赖喵 */
"use strict";

// 口令在浏览器本地的存储键喵
const TOKEN_KEY = "devicehub.token";

// 自动刷新开关的存储键喵
const AUTO_REFRESH_KEY = "devicehub.autoRefresh";

// 自动刷新间隔（毫秒）喵
const REFRESH_MS = 30000;

// 当前状态喵
const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  autoRefresh: localStorage.getItem(AUTO_REFRESH_KEY) !== "false",
  tab: "overview",
  hours: 24,
  devices: [],
  rankings: [],
  // 排行口径：all 总排行 / device 按设备 / group 按设备组喵
  rankingScope: "all",
  // 排行榜限定设备范围（截图时由命令参数传入，空数组表示全部设备）喵
  rankingDevices: [],
  // 分组排行的每组数据，服务端按口径算好喵
  rankingGroups: [],
  selectedId: null,
  detail: null,
  timelineDate: "",
  timelineDeviceId: null,
  // 当前时间轴是不是合并视图（组 / 所有设备），合并视图里泳道始终标设备名喵
  timelineMerged: false,
  // 时间轴缩放倍数与当天的标题区间喵
  timelineZoom: 1,
  timelineTitles: [],
  // 时间轴这一屏每个应用最终用的颜色（图标混合色或原配色），悬浮提示共用喵
  timelineColors: new Map(),
  // 时间轴这一屏「应用 → 该应用出现过的设备名」，深浅只按应用自己的清单算喵
  timelineAppDevices: new Map(),
  // 时间轴数据的指纹，静默刷新时用来判断要不要重画喵
  timelineSignature: "",
  // 时间轴拖动状态喵
  timelineDrag: null,
  // 刻度补画的动画句柄喵
  timelineAxisFrame: 0,
  // 服务端时间与本机的差值（毫秒），所有「现在」都按它校正喵
  clockOffsetMs: 0,
  // 授时来源，设置页会显示出来喵
  clockSource: "",
  // 时间轴用的时区偏移（分钟），跟服务端保持一致喵
  tzOffsetMinutes: 480,
  timeline: null,
  // 统计页：热力图回溯天数、设备筛选（空串表示全部）与数据喵
  statsDays: 90,
  statsDeviceId: "",
  stats: null,
  // 统计页的全量设备清单，切到单台设备后按钮仍要靠它喵
  statsDeviceList: [],
  people: [],
  peopleDraft: [],
  // 配置页：可编辑字段与它们的初始值喵
  configFields: [],
  configOriginal: {},
  timer: null,
  // 时间轴增量刷新定时器喵
  timelineTimer: null,
  // 截图挂起的定位请求，等时间轴画完再执行喵
  pendingShotFocus: null,
  loading: false,
};

// 常用元素引用喵
const el = {
  nav: document.getElementById("nav"),
  live: document.getElementById("live-indicator"),
  liveText: document.getElementById("live-text"),
  refresh: document.getElementById("refresh-btn"),
  tokenBtn: document.getElementById("token-btn"),
  kpiRow: document.getElementById("kpi-row"),
  overviewGrid: document.getElementById("overview-grid"),
  deviceTable: document.getElementById("device-table-wrap"),
  deviceDetail: document.getElementById("device-detail"),
  rankingBody: document.getElementById("ranking-body"),
  rankingSummary: document.getElementById("ranking-summary"),
  rangeSwitch: document.getElementById("range-switch"),
  rankScopeSwitch: document.getElementById("rank-scope-switch"),
  statsKpi: document.getElementById("stats-kpi"),
  statsSummary: document.getElementById("stats-summary"),
  statsRangeSwitch: document.getElementById("stats-range-switch"),
  statsDeviceSwitch: document.getElementById("stats-device-switch"),
  statsDevices: document.getElementById("stats-devices"),
  heatmapBody: document.getElementById("heatmap-body"),
  heatmapLegend: document.getElementById("heatmap-legend"),
  trendBody: document.getElementById("trend-body"),
  trendSummary: document.getElementById("trend-summary"),
  tlDevice: document.getElementById("tl-device"),
  tlDate: document.getElementById("tl-date"),
  tlPrev: document.getElementById("tl-prev"),
  tlNext: document.getElementById("tl-next"),
  tlToday: document.getElementById("tl-today"),
  tlSummary: document.getElementById("tl-summary"),
  tlAxis: document.getElementById("tl-axis"),
  tlTrack: document.getElementById("tl-track"),
  tlLanes: document.getElementById("tl-lanes"),
  tlLegend: document.getElementById("tl-legend"),
  tlScroll: document.getElementById("tl-scroll"),
  tlInner: document.getElementById("tl-inner"),
  tlNow: document.getElementById("tl-now"),
  tlPointer: document.getElementById("tl-pointer"),
  tlTip: document.getElementById("tl-tip"),
  tlZoomIn: document.getElementById("tl-zoom-in"),
  tlZoomOut: document.getElementById("tl-zoom-out"),
  tlZoomReset: document.getElementById("tl-zoom-reset"),
  tlZoomLabel: document.getElementById("tl-zoom-label"),
  tlPeople: document.getElementById("tl-people"),
  peopleModal: document.getElementById("people-modal"),
  peopleEditor: document.getElementById("people-editor"),
  peopleAdd: document.getElementById("people-add"),
  peopleSave: document.getElementById("people-save"),
  peopleCancel: document.getElementById("people-cancel"),
  botInput: document.getElementById("bot-input"),
  botSend: document.getElementById("bot-send"),
  botChips: document.getElementById("bot-chips"),
  botGroup: document.getElementById("bot-group"),
  botUser: document.getElementById("bot-user"),
  botChannel: document.getElementById("bot-channel"),
  botMention: document.getElementById("bot-mention"),
  botStatus: document.getElementById("bot-status"),
  botConn: document.getElementById("bot-conn"),
  botReply: document.getElementById("bot-reply"),
  botImage: document.getElementById("bot-image"),
  botCopy: document.getElementById("bot-copy"),
  settingsToken: document.getElementById("settings-token"),
  settingsSave: document.getElementById("settings-save"),
  settingsClear: document.getElementById("settings-clear"),
  autoRefresh: document.getElementById("auto-refresh"),
  // 配置页元素喵
  configFields: document.getElementById("config-fields"),
  configPath: document.getElementById("config-path"),
  configStatus: document.getElementById("config-status"),
  configSave: document.getElementById("config-save"),
  configTestNapcat: document.getElementById("config-test-napcat"),
  configTestQqbot: document.getElementById("config-test-qqbot"),
  configRestart: document.getElementById("config-restart"),
  // 黑名单元素喵
  blocklistChannel: document.getElementById("blocklist-channel"),
  blocklistTarget: document.getElementById("blocklist-target"),
  blocklistNote: document.getElementById("blocklist-note"),
  blocklistAdd: document.getElementById("blocklist-add"),
  blocklistStatus: document.getElementById("blocklist-status"),
  blocklistList: document.getElementById("blocklist-list"),
  // 最近发言元素喵
  seenUsersList: document.getElementById("seen-users-list"),
  modal: document.getElementById("token-modal"),
  modalInput: document.getElementById("modal-token"),
  modalSave: document.getElementById("modal-save"),
  modalCancel: document.getElementById("modal-cancel"),
  toast: document.getElementById("toast"),
};

/** 把 HTML 特殊字符转义，避免设备名里的尖括号破坏页面喵。 */
function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 把秒数格式化成中文时长喵。 */
function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours} 小时 ${restMinutes} 分` : `${hours} 小时`;
}

/** 把 ISO 时间格式化成 HH:mm 喵。 */
function formatClock(isoText) {
  const moment = isoText instanceof Date ? isoText : new Date(isoText);
  if (!isoText || Number.isNaN(moment.getTime())) return "--:--";
  const pad = (value) => String(value).padStart(2, "0");
  // 按服务端时区取时分，浏览器时区改了也不影响显示喵
  const shifted = inServerZone(moment);
  // 放大到分钟以下时把秒也带上，方便看清秒级刻度喵
  if (state.timelineZoom && state.timelineZoom >= 60) {
    return `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`;
  }
  return `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`;
}

/** 顶部状态灯：ok / error / 空喵。 */
function setLive(kind, text) {
  el.live.className = `live${kind ? ` ${kind}` : ""}`;
  el.liveText.textContent = text;
}

/** 弹出轻提示喵。 */
let toastTimer = null;
function showToast(message, kind) {
  el.toast.textContent = message;
  el.toast.className = `toast ${kind || ""}`;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.toast.classList.add("hidden"), 2400);
}

/** 带口令请求接口，非 2xx 时抛出可读错误喵。 */
async function api(path, options) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "X-Ingest-Token": state.token,
      "Content-Type": "application/json",
      ...(options && options.headers ? options.headers : {}),
    },
  });
  if (response.status === 401) {
    const error = new Error("口令不正确或已失效");
    error.unauthorized = true;
    throw error;
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch (ignored) {
      // 喵~防御：响应不是 JSON 时保留状态码提示喵
    }
    throw new Error(detail);
  }
  return response.json();
}

/** 电量进度条颜色：低于 20% 用警示色喵。 */
function batteryClass(percent) {
  return percent != null && percent < 20 ? "battery-fill low" : "battery-fill";
}

/* ==================== 概览 ==================== */

/** 渲染四个 KPI 卡片喵。 */
function renderKpi() {
  const devices = state.devices;
  const online = devices.filter((item) => item.online).length;
  const paused = devices.filter((item) => item.stats_paused_reason).length;
  const totalSeconds = devices.reduce((sum, item) => sum + (item.usage_total_seconds || 0), 0);
  const servers = devices.filter((item) => item.role === "server").length;
  el.kpiRow.innerHTML = `
    <div class="kpi">
      <div class="kpi-label">设备总数</div>
      <div class="kpi-value accent">${devices.length}</div>
      <div class="kpi-hint">其中服务器 ${servers} 台</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">在线设备</div>
      <div class="kpi-value success">${online}</div>
      <div class="kpi-hint">90 秒内有上报</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">统计暂停</div>
      <div class="kpi-value warning">${paused}</div>
      <div class="kpi-hint">RDP 未连接或投屏门控</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">近 24 小时合计</div>
      <div class="kpi-value">${formatDuration(totalSeconds)}</div>
      <div class="kpi-hint">所有设备累加</div>
    </div>`;
}

/** 渲染一张设备卡片喵。 */
function renderCard(device) {
  const activeClass = device.device_id === state.selectedId ? " active" : "";
  const onlineBadge = device.online
    ? '<span class="badge online" title="在线 = 最近几分钟有心跳上报"><span class="dot"></span>在线</span>'
    : '<span class="badge offline" title="离线 = 没有心跳，采集端没在运行"><span class="dot"></span>离线</span>';
  const roleBadge = device.role === "server" ? '<span class="badge server">服务器</span>' : "";
  const pausedBadge = device.stats_paused_reason ? '<span class="badge paused">统计暂停</span>' : "";
  const pausedNote = device.stats_paused_reason && device.stats_paused_text
    ? `<p class="paused-note">${escapeHtml(device.stats_paused_text)}</p>`
    : "";
  const battery = device.battery;
  const batteryBlock = battery
    ? `<div class="stat-label">电量</div>
       <div class="stat-value">${battery.percent}%${battery.charging ? " · 充电中" : ""}</div>
       <div class="battery-bar"><div class="${batteryClass(battery.percent)}" style="width:${Math.min(100, Math.max(0, battery.percent))}%"></div></div>`
    : '<div class="stat-label">电量</div><div class="stat-value">--</div>';
  const currentApp = device.current_app ? escapeHtml(device.current_app.name) : "未知";
  const topItems = (device.usage_top || [])
    .slice(0, 3)
    .map((item) => {
      const max = Math.max(1, ...(device.usage_top || []).map((entry) => entry.seconds));
      const width = Math.round((item.seconds / max) * 100);
      return `<li class="mini-item">
        <span>${escapeHtml(item.app)}</span><span>${formatDuration(item.seconds)}</span>
        <span class="mini-bar"><span style="width:${width}%"></span></span>
      </li>`;
    })
    .join("");

  return `<article class="card${activeClass}" data-device-id="${escapeHtml(device.device_id)}" tabindex="0">
    <div class="card-head">
      <div>
        <h3 class="card-title">${escapeHtml(device.display_name)}</h3>
        <p class="card-id">${escapeHtml(device.device_id)}</p>
      </div>
    </div>
    <div class="badges">${onlineBadge}${roleBadge}${pausedBadge}
      <span class="badge">${escapeHtml(device.platform === "android" ? "Android" : "Windows")}</span>
    </div>
    ${pausedNote}
    <div class="card-stats">
      <div>${batteryBlock}</div>
      <div>
        <div class="stat-label">当前应用</div>
        <div class="stat-value">${currentApp}</div>
        <div class="stat-label" style="margin-top:8px">近 24 小时</div>
        <div class="stat-value">${formatDuration(device.usage_total_seconds)}</div>
      </div>
    </div>
    ${topItems ? `<ul class="mini-list">${topItems}</ul>` : ""}
  </article>`;
}

/** 渲染概览卡片网格喵。 */
function renderOverview() {
  renderKpi();
  if (!state.devices.length) {
    el.overviewGrid.innerHTML = '<p class="empty">还没有任何设备上报数据</p>';
    return;
  }
  el.overviewGrid.innerHTML = state.devices.map(renderCard).join("");
  el.overviewGrid.querySelectorAll(".card").forEach((card) => {
    const open = () => {
      state.selectedId = card.dataset.deviceId;
      switchTab("devices");
    };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
}

/* ==================== 设备 ==================== */

/** 渲染设备表格喵。 */
function renderDeviceTable() {
  if (!state.devices.length) {
    el.deviceTable.innerHTML = '<p class="empty">还没有任何设备上报数据</p>';
    return;
  }
  const rows = state.devices
    .map((device) => {
      const active = device.device_id === state.selectedId ? " active" : "";
      const status = device.online
        ? '<span class="badge online" title="在线 = 最近几分钟有心跳上报"><span class="dot"></span>在线</span>'
        : '<span class="badge offline" title="离线 = 没有心跳，采集端没在运行"><span class="dot"></span>离线</span>';
      const paused = device.stats_paused_reason ? ' <span class="badge paused">暂停</span>' : "";
      const role = device.role === "server" ? '<span class="badge server">服务器</span>' : "工作站";
      const battery = device.battery ? `${device.battery.percent}%${device.battery.charging ? " ⚡" : ""}` : "--";
      const currentApp = device.current_app ? escapeHtml(device.current_app.name) : "未知";
      return `<tr class="${active}" data-device-id="${escapeHtml(device.device_id)}">
        <td><div class="cell-name"><strong>${escapeHtml(device.display_name)}</strong><small>${escapeHtml(device.device_id)}</small></div></td>
        <td>${escapeHtml(device.platform === "android" ? "Android" : "Windows")}</td>
        <td>${status}${paused}</td>
        <td>${role}</td>
        <td>${battery}</td>
        <td>${currentApp}</td>
        <td>${formatDuration(device.usage_total_seconds)}</td>
      </tr>`;
    })
    .join("");
  el.deviceTable.innerHTML = `<table class="devices">
    <thead><tr>
      <th>设备</th><th>平台</th><th>状态</th><th>角色</th><th>电量</th><th>当前应用</th><th>近 24 小时</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  el.deviceTable.querySelectorAll("tbody tr").forEach((row) => {
    row.addEventListener("click", () => selectDevice(row.dataset.deviceId));
  });
}

/** 选中设备并加载详情喵。 */
async function selectDevice(deviceId) {
  state.selectedId = deviceId;
  // 详情放在设备页下方，切过去才看得到喵
  if (state.tab !== "devices") {
    switchTab("devices");
    return;
  }
  renderDeviceTable();
  el.deviceDetail.innerHTML = '<div class="panel detail"><p class="empty">加载中…</p></div>';
  try {
    state.detail = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}`);
    el.deviceDetail.innerHTML = renderDetail(state.detail);
    bindDetailActions(deviceId);
    // 窗口列表单独拉，避免详情接口变慢喵
    await loadDeviceWindows(deviceId);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.deviceDetail.innerHTML = `<div class="panel detail"><p class="empty">加载失败：${escapeHtml(error.message)}</p></div>`;
  }
}

/** 拉取并渲染某台设备当前打开的窗口喵。 */
async function loadDeviceWindows(deviceId) {
  const container = document.getElementById("detail-windows");
  if (!container) return;
  try {
    const body = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}/windows`);
    const windows = body.windows || [];
    if (!windows.length) {
      container.innerHTML = '<p class="empty">没有窗口数据（安卓端不上报窗口）</p>';
      return;
    }
    container.innerHTML = windows
      .map(
        (item) => `<div class="window-row${item.foreground ? " fg" : ""}${item.minimized ? " min" : ""}">
          ${appIconHtml(item, "#c9cdd4")}
          <span class="window-app" title="${escapeHtml(item.package)}">${escapeHtml(item.app)}</span>
          <span class="window-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title || "（无标题）")}</span>
          <span>${item.foreground ? '<span class="badge online">前台</span>' : ""}${item.minimized ? '<span class="badge">最小化</span>' : ""}</span>
        </div>`
      )
      .join("");
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    container.innerHTML = `<p class="empty">窗口加载失败：${escapeHtml(error.message)}</p>`;
  }
}

/** 拉取并渲染存储占用喵。 */
async function loadStorage() {
  const container = document.getElementById("storage-stats");
  if (!container) return;
  try {
    const stats = await api("/api/v1/storage");
    container.innerHTML = renderStorageStats(stats);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    container.innerHTML = `<p class="empty">读取失败：${escapeHtml(error.message)}</p>`;
  }
}

/** 把存储统计渲染成几行文字喵。 */
function renderStorageStats(stats) {
  const rows = (stats.tables || [])
    .map(
      (table) => `<div class="storage-row"><span>${escapeHtml(table.name)}</span><span>${table.rows} 行</span></div>`
    )
    .join("");
  return `<div class="storage-total">${formatBytes(stats.total_bytes)}</div>
    <div class="storage-row"><span>库文件</span><span>${formatBytes(stats.db_bytes)}</span></div>
    <div class="storage-row"><span>WAL 日志</span><span>${formatBytes(stats.wal_bytes)}</span></div>
    <div class="storage-row"><span>总行数</span><span>${stats.total_rows}</span></div>
    ${rows}`;
}

/** 把字节数格式化成可读文本喵。 */
function formatBytes(value) {
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(value) || 0;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return index === 0 ? `${Math.round(size)} B` : `${size.toFixed(1)} ${units[index]}`;
}

/** 按天数清理历史数据喵。 */
async function cleanupStorage() {
  const daysInput = document.getElementById("storage-days");
  const days = Number(daysInput && daysInput.value) || 30;
  // 喵~防御：删数据前必须让主人确认一次喵
  if (!window.confirm(`确定删除 ${days} 天以前的历史记录吗？删掉就找不回来了。`)) return;
  try {
    const body = await api("/api/v1/storage/cleanup", {
      method: "POST",
      body: JSON.stringify({ before_days: days }),
    });
    const container = document.getElementById("storage-stats");
    if (container && body.stats) container.innerHTML = renderStorageStats(body.stats);
    showToast(`已清理 ${body.deleted_total} 行历史数据`, "ok");
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    showToast(`清理失败：${error.message}`, "error");
  }
}

/** 渲染详情面板喵。 */
function renderDetail(detail) {
  const nextRole = detail.role === "server" ? "workstation" : "server";
  const roleButtonLabel = detail.role === "server" ? "取消服务器标记" : "标记为服务器";
  const pausedBanner = detail.stats_paused_reason
    ? `<div class="banner">${escapeHtml(detail.stats_paused_text || "统计已暂停")}</div>`
    : "";
  const rdpBadge = detail.role === "server"
    ? `<span class="badge ${detail.rdp_connected ? "online" : "paused"}">RDP ${detail.rdp_connected ? "已连接" : "未连接"}</span>`
    : "";
  const mirrored = (detail.mirrored_tags || []).length
    ? `<p class="muted" style="margin-top:8px">正在投屏：${detail.mirrored_tags.map(escapeHtml).join("、")}</p>`
    : "";
  const ranking = detail.usage_ranking || [];
  const maxSeconds = Math.max(1, ranking.length ? ranking[0].seconds : 1);
  const rankingRows = ranking
    .slice(0, 15)
    .map((item, index) => `<tr>
      <td>${index + 1}</td>
      <td><span class="rank-app">${appIconHtml(item, appColor(item.app))}${escapeHtml(item.app)}</span><div class="pkg">${escapeHtml(item.package || "未知包名")}</div></td>
      <td>${formatDuration(item.seconds)}</td>
      <td><div class="rank-bar"><span style="width:${Math.round((item.seconds / maxSeconds) * 100)}%"></span></div></td>
    </tr>`)
    .join("");
  const hardwareRows = Object.entries(detail.hardware || {})
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
  const batteryText = detail.battery
    ? `${detail.battery.percent}%${detail.battery.charging ? " · 充电中" : ""}`
    : "该设备不上报电量";

  return `<div class="panel detail">
    <div class="detail-head">
      <div>
        <h3 class="detail-title">${escapeHtml(detail.display_name)}</h3>
        <p class="detail-sub">${escapeHtml(detail.device_id)} · ${escapeHtml(detail.os_version || "系统未知")}</p>
        <div class="badges">
          <span class="badge ${detail.online ? "online" : "offline"}" title="${detail.online ? "在线 = 最近几分钟有心跳上报" : "离线 = 没有心跳，采集端没在运行"}"><span class="dot"></span>${detail.online ? "在线" : "离线"}</span>
          ${detail.role === "server" ? '<span class="badge server">服务器</span>' : ""}
          ${rdpBadge}
          ${detail.stats_paused_reason ? '<span class="badge paused">统计暂停</span>' : ""}
          <span class="badge">${escapeHtml(detail.platform === "android" ? "Android" : "Windows")}</span>
          ${detail.tag ? `<span class="badge">标签：${escapeHtml(detail.tag)}</span>` : ""}
        </div>
      </div>
      <div class="detail-actions">
        <button class="btn ghost" id="toggle-role" data-role="${nextRole}" type="button">${roleButtonLabel}</button>
        <button class="btn ghost" id="close-detail" type="button">收起</button>
      </div>
    </div>
    ${pausedBanner}
    ${mirrored}
    <div class="detail-grid">
      <div class="block">
        <h4>近 24 小时电量曲线</h4>
        ${batteryChart(detail.battery_series)}
      </div>
      <div class="block">
        <h4>近 24 小时使用时间轴</h4>
        ${usageChart(detail.usage_timeline)}
      </div>
      <div class="block">
        <h4>当前打开的窗口</h4>
        <div id="detail-windows" class="windows-list"><p class="empty">加载中…</p></div>
      </div>
      <div class="block">
        <h4>应用使用排行（近 24 小时）</h4>
        ${rankingRows
          ? `<table class="rank"><thead><tr><th>#</th><th>应用 / 包名</th><th>时长</th><th>占比</th></tr></thead><tbody>${rankingRows}</tbody></table>`
          : '<p class="empty">暂无使用数据</p>'}
      </div>
      <div class="block">
        <h4>设备信息</h4>
        <dl class="kv">
          <dt>电量</dt><dd>${escapeHtml(batteryText)}</dd>
          <dt>当前应用</dt><dd>${escapeHtml(detail.current_app ? detail.current_app.name : "未知")}</dd>
          <dt>近 24 小时合计</dt><dd>${formatDuration(detail.usage_total_seconds)}</dd>
          ${hardwareRows}
        </dl>
      </div>
    </div>
  </div>`;
}

/** 绑定详情里的按钮喵。 */
function bindDetailActions(deviceId) {
  const roleButton = document.getElementById("toggle-role");
  if (roleButton) {
    roleButton.addEventListener("click", () => toggleRole(deviceId, roleButton.dataset.role));
  }
  const closeButton = document.getElementById("close-detail");
  if (closeButton) {
    closeButton.addEventListener("click", () => {
      state.selectedId = null;
      state.detail = null;
      el.deviceDetail.innerHTML = "";
      renderDeviceTable();
      updateHash();
    });
  }
}

/** 切换设备角色喵。 */
async function toggleRole(deviceId, role) {
  try {
    await api(`/api/v1/devices/${encodeURIComponent(deviceId)}/role`, {
      method: "POST",
      body: JSON.stringify({ role }),
    });
    showToast(role === "server" ? "已标记为服务器" : "已标记为工作站", "ok");
    await loadDashboard();
    await fetchPeople();
    await selectDevice(deviceId);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    showToast(`操作失败：${error.message}`, "error");
  }
}

/* ==================== 图表 ==================== */

/** 生成电量曲线 SVG 喵。 */
function batteryChart(points) {
  if (!points || !points.length) {
    return '<p class="empty">近 24 小时没有电量数据</p>';
  }
  const width = 320;
  const height = 120;
  const pad = 20;
  const innerWidth = width - pad * 2;
  const innerHeight = height - pad * 2;
  const xs = points.map((point, index) =>
    points.length === 1 ? pad + innerWidth / 2 : pad + (index * innerWidth) / (points.length - 1)
  );
  const ys = points.map((point) => pad + (1 - Math.min(100, Math.max(0, point.percent)) / 100) * innerHeight);
  const linePoints = xs.map((x, index) => `${x.toFixed(1)},${ys[index].toFixed(1)}`).join(" ");
  const areaPoints = `${pad},${height - pad} ${linePoints} ${xs[xs.length - 1].toFixed(1)},${height - pad}`;
  const dots = xs
    .map((x, index) => `<circle class="point" cx="${x.toFixed(1)}" cy="${ys[index].toFixed(1)}" r="2.6"></circle>`)
    .join("");
  const gridLines = [0, 25, 50, 75, 100]
    .map((percent) => {
      const y = pad + (1 - percent / 100) * innerHeight;
      return `<line class="grid-line" x1="${pad}" y1="${y.toFixed(1)}" x2="${width - pad}" y2="${y.toFixed(1)}"></line>
        <text x="2" y="${(y + 3).toFixed(1)}">${percent}</text>`;
    })
    .join("");
  const firstLabel = `<text x="${pad}" y="${height - 4}">${formatClock(points[0].sampled_at)}</text>`;
  const lastLabel = `<text x="${width - pad - 26}" y="${height - 4}">${formatClock(points[points.length - 1].sampled_at)}</text>`;

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 24 小时电量曲线">
    <defs>
      <linearGradient id="batteryGradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#165dff" stop-opacity="0.18"></stop>
        <stop offset="100%" stop-color="#165dff" stop-opacity="0"></stop>
      </linearGradient>
    </defs>
    ${gridLines}
    <polygon class="area" points="${areaPoints}"></polygon>
    <polyline class="line" points="${linePoints}"></polyline>
    ${dots}
    ${firstLabel}${lastLabel}
  </svg>`;
}

/** 生成近 24 小时使用时长柱状图 SVG 喵。 */
function usageChart(timeline) {
  const hours = 24;
  const now = serverNow();
  now.setMinutes(0, 0, 0);
  const bucketMap = new Map();
  (timeline || []).forEach((bucket) => {
    const moment = new Date(bucket.bucket_start);
    if (!Number.isNaN(moment.getTime())) bucketMap.set(moment.getTime(), bucket.seconds);
  });
  const slots = [];
  for (let offset = hours - 1; offset >= 0; offset -= 1) {
    const moment = new Date(now.getTime() - offset * 3600 * 1000);
    slots.push({ moment, seconds: bucketMap.get(moment.getTime()) || 0 });
  }
  const maxSeconds = Math.max(1, ...slots.map((slot) => slot.seconds));
  const width = 320;
  const height = 120;
  const pad = 18;
  const innerWidth = width - pad * 2;
  const innerHeight = height - pad * 2 - 10;
  const slotWidth = innerWidth / slots.length;
  const barWidth = Math.max(2, slotWidth - 3);
  const bars = slots
    .map((slot, index) => {
      const barHeight = slot.seconds === 0 ? 0 : Math.max(1.5, (slot.seconds / maxSeconds) * innerHeight);
      const x = pad + index * slotWidth + (slotWidth - barWidth) / 2;
      const y = pad + innerHeight - barHeight;
      return `<rect class="bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="2">
        <title>${formatClock(slot.moment)} · ${formatDuration(slot.seconds)}</title>
      </rect>`;
    })
    .join("");
  const labels = slots
    .map((slot, index) => {
      if (index % 6 !== 0) return "";
      const x = pad + index * slotWidth;
      return `<text x="${x.toFixed(1)}" y="${height - 4}">${formatClock(slot.moment)}</text>`;
    })
    .join("");
  const baseLine = `<line class="grid-line" x1="${pad}" y1="${pad + innerHeight}" x2="${width - pad}" y2="${pad + innerHeight}"></line>`;

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 24 小时使用时长">
    ${baseLine}${bars}${labels}
  </svg>`;
}

/* ==================== 时间轴 ==================== */

// 一天有多少分钟喵
const DAY_MINUTES = 1440;

// 一天有多少秒，秒级刻度要用喵
const DAY_SECONDS = 86400;

// 时间轴最大放大倍数，够看清秒级刻度喵
const TIMELINE_MAX_ZOOM = 8640;

// 刻度阶梯（秒），按放大倍数自动挑一档，最小精确到秒喵
const TICK_STEPS = [86400, 43200, 21600, 10800, 7200, 3600, 1800, 900, 600, 300, 120, 60, 30, 15, 10, 5, 2, 1];

// 应用色板，按名字哈希取色，保证同一应用每次颜色一致喵
const APP_COLORS = [
  "#165dff", "#00b42a", "#ff7d00", "#f53f3f", "#722ed1", "#0fc6c2",
  "#eb2f96", "#fa8c16", "#13c2c2", "#2f54eb", "#a0d911", "#d4380d",
];

// 图标取色的采样尺寸（像素）：24×24 足够代表主色，又不用读整张大图喵
const ICON_SAMPLE_SIZE = 24;

// 图标取色结果缓存：键是图标键，值是 "rgb(r, g, b)"；null 表示取色失败喵
const iconColorCache = new Map();

// 正在取色的图标任务：同一个图标只发一次图片请求，结果回来再刷新时间轴喵
const iconColorTasks = new Map();

// 取色完成后的重画是否已排队：多个图标同时回来时只重画一次喵
let iconColorRefreshQueued = false;

/** 记录服务端时间与本机的差值，之后所有「现在」都按它校正喵。 */
function applyServerClock(isoText) {
  // 喵~防御：服务端没给时间就保持原样喵
  if (!isoText) return;
  const parsed = Date.parse(isoText);
  // 喵~防御：解析失败说明字段格式不对，直接忽略喵
  if (Number.isNaN(parsed)) return;
  state.clockOffsetMs = parsed - Date.now();
}

/** 取服务端口径的「现在」，不信任浏览器时钟喵。 */
function serverNow() {
  return new Date(Date.now() + state.clockOffsetMs);
}

/** 把任意时刻换算到服务端时区，返回各字段可直接读的 Date 喵。 */
function inServerZone(moment) {
  // 按服务端时区偏移平移，再用 UTC 取值，浏览器时区就不影响了喵
  return new Date(moment.getTime() + state.tzOffsetMinutes * 60000);
}

/** 拉一次服务端时间，页面加载与每次刷新都校准喵。 */
async function syncServerClock() {
  try {
    const body = await api("/api/v1/time");
    applyServerClock(body.server_now);
    state.clockSource = body.source || "";
  } catch (error) {
    // 喵~防御：取不到就沿用上次的偏移，界面不能因此报错喵
  }
}

/** 取服务端口径的日期文本 YYYY-MM-DD 喵。 */
function localDateText(moment) {
  const pad = (value) => String(value).padStart(2, "0");
  const shifted = inServerZone(moment);
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
}

/** 拉取设备组（存在服务端 data/people.json）喵。 */
async function fetchPeople() {
  try {
    const body = await api("/api/v1/people");
    state.people = body.groups || [];
    // 设备组是异步来的，回来之后要把下拉补全喵
    if (state.devices.length) renderTimelineControls();
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    // 喵~防御：读不到就当没分组，页面照常能用喵
    state.people = [];
  }
}

/** 保存设备组到服务端喵。 */
async function persistPeople(groups) {
  const body = await api("/api/v1/people", { method: "PUT", body: JSON.stringify({ groups }) });
  state.people = body.groups || [];
  return state.people;
}

/** 打开设备组编辑弹窗喵。 */
function openPeopleEditor() {
  // 复制一份草稿，取消时不污染已保存的数据喵
  state.peopleDraft = state.people.map((group) => ({ name: group.name, devices: [...group.devices] }));
  renderPeopleEditor();
  el.peopleModal.classList.remove("hidden");
}

/** 关闭设备组编辑弹窗喵。 */
function closePeopleEditor() {
  el.peopleModal.classList.add("hidden");
  state.peopleDraft = [];
}

/** 渲染设备组草稿喵。 */
function renderPeopleEditor() {
  const draft = state.peopleDraft;
  if (!draft.length) {
    el.peopleEditor.innerHTML = '<p class="people-empty">还没有设备组，点下面的「新增设备组」建一个。</p>';
    return;
  }
  el.peopleEditor.innerHTML = draft
    .map((group, groupIndex) => {
      // 组内已有的设备按优先级顺序列成芯片喵
      const chips = group.devices.length
        ? group.devices
            .map((deviceId, deviceIndex) => {
              const device = state.devices.find((item) => item.device_id === deviceId);
              const label = device ? device.display_name : deviceId;
              return `<span class="people-chip" title="${escapeHtml(deviceId)}">
                <b>${deviceIndex + 1}</b>${escapeHtml(label)}
                <button type="button" data-action="up" data-group="${groupIndex}" data-device="${deviceIndex}" title="提高优先级">↑</button>
                <button type="button" data-action="down" data-group="${groupIndex}" data-device="${deviceIndex}" title="降低优先级">↓</button>
                <button type="button" data-action="remove" data-group="${groupIndex}" data-device="${deviceIndex}" title="移出本组">×</button>
              </span>`;
            })
            .join("")
        : '<span class="people-empty">还没加设备</span>';
      // 可选设备：还没进本组的设备喵
      const options = state.devices
        .filter((device) => !group.devices.includes(device.device_id))
        .map((device) => `<option value="${escapeHtml(device.device_id)}">${escapeHtml(device.display_name)}（${escapeHtml(device.device_id)}）</option>`)
        .join("");
      return `<div class="people-group">
        <div class="people-group-head">
          <input type="text" data-role="name" data-group="${groupIndex}" value="${escapeHtml(group.name)}" placeholder="人名 / 组名" maxlength="64">
          <button class="btn ghost" type="button" data-action="delete-group" data-group="${groupIndex}">删除组</button>
        </div>
        <div class="people-devices">
          ${chips}
          <select data-role="add" data-group="${groupIndex}">
            <option value="">添加设备…</option>
            ${options}
          </select>
        </div>
      </div>`;
    })
    .join("");
}

/** 处理设备组编辑器里的点击与选择喵。 */
async function handlePeopleEditorEvent(event) {
  const target = event.target;
  const groupIndex = Number(target.dataset.group);
  // 名称输入喵
  if (target.dataset.role === "name") {
    state.peopleDraft[groupIndex].name = target.value;
    return;
  }
  // 添加设备下拉喵
  if (target.dataset.role === "add") {
    const deviceId = target.value;
    if (!deviceId) return;
    state.peopleDraft[groupIndex].devices.push(deviceId);
    renderPeopleEditor();
    return;
  }
  const action = target.dataset.action;
  if (!action) return;
  const deviceIndex = Number(target.dataset.device);
  const group = state.peopleDraft[groupIndex];
  if (!group) return;
  if (action === "delete-group") {
    state.peopleDraft.splice(groupIndex, 1);
  } else if (action === "remove") {
    group.devices.splice(deviceIndex, 1);
  } else if (action === "up" && deviceIndex > 0) {
    // 上移一位就是提高优先级喵
    [group.devices[deviceIndex - 1], group.devices[deviceIndex]] = [group.devices[deviceIndex], group.devices[deviceIndex - 1]];
  } else if (action === "down" && deviceIndex < group.devices.length - 1) {
    [group.devices[deviceIndex + 1], group.devices[deviceIndex]] = [group.devices[deviceIndex], group.devices[deviceIndex + 1]];
  }
  renderPeopleEditor();
}

/** 保存设备组草稿喵。 */
async function savePeopleEditor() {
  // 喵~防御：组名为空的先补个默认名，避免整次保存失败喵
  const groups = state.peopleDraft.map((group, index) => ({
    name: group.name.trim() || `设备组 ${index + 1}`,
    devices: group.devices,
  }));
  try {
    await persistPeople(groups);
    closePeopleEditor();
    renderTimelineControls();
    showToast("设备组已保存", "ok");
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    showToast(`保存失败：${error.message}`, "error");
  }
}
/** 拼应用图标的地址，<img> 带不了请求头所以口令放查询串喵。 */
function iconUrl(key) {
  return `/api/v1/icons/${encodeURIComponent(key)}?token=${encodeURIComponent(state.token)}`;
}

/** 应用名前面那个小图标，没有图标时退回色块喵。 */
function appIconHtml(entry, color) {
  if (entry && entry.icon_key) {
    return `<img class="app-icon" src="${iconUrl(entry.icon_key)}" alt="" loading="lazy" onerror="this.style.display='none'">`;
  }
  return `<i class="tl-dot" style="background:${color}"></i>`;
}

/** 按应用名取固定颜色喵。 */
function appColor(name) {
  let hash = 0;
  for (const char of String(name)) hash = (hash * 31 + char.codePointAt(0)) % 100003;
  return APP_COLORS[hash % APP_COLORS.length];
}

/** 给一组应用分配互不相同的颜色，撞色时往后顺延一格喵。 */
function buildColorMap(apps) {
  const used = new Set();
  const colors = new Map();
  for (const app of apps) {
    let index = 0;
    for (const char of String(app)) index = (index * 31 + char.codePointAt(0)) % 100003;
    index %= APP_COLORS.length;
    let probe = 0;
    while (used.has(index) && probe < APP_COLORS.length) {
      index = (index + 1) % APP_COLORS.length;
      probe += 1;
    }
    used.add(index);
    colors.set(app, APP_COLORS[index]);
  }
  return colors;
}

/* ==================== 多设备颜色区分 ==================== */

// 同一应用最多分几级深浅（第一台原色 + 后面 6 级）喵
const DEVICE_SHADE_STEPS = 6;

/** 取某台设备在渐变里的位置（0 = 原色，1 = 最远一级）喵。 */
function deviceShadeRatio(index, total) {
  // 喵~防御：非法序号一律按第一台设备算喵
  const safe = Number.isFinite(index) ? Math.max(0, Math.floor(index)) : 0;
  // 第一台设备用原色，比例是 0 喵
  if (safe === 0) return 0;
  // 知道本屏一共几台设备时按台数铺满，两台设备也能一眼看出深浅差别喵
  const count = Number.isFinite(total) ? Math.floor(total) : 0;
  // 喵~防御：两台以上才按台数算，否则仍按固定档位递进喵
  if (count >= 2) return Math.min(1, safe / (count - 1));
  // 超出级数的设备统一落在最远一级，不再越走越离谱喵
  return Math.min(1, safe / DEVICE_SHADE_STEPS);
}

/** 把 #rgb / #rrggbb / rgb() 解析成三元组，认不出来返回 null 喵。 */
function parseCssColor(text) {
  const value = String(text || "").trim();
  // 先试 rgb(r, g, b) 这种形式喵
  const rgbMatch = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/.exec(value);
  if (rgbMatch) {
    return { r: Number(rgbMatch[1]), g: Number(rgbMatch[2]), b: Number(rgbMatch[3]) };
  }
  // 再试十六进制，三位简写也认喵
  const hexMatch = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  // 喵~防御：认不出的格式返回 null，调用方原样保留颜色喵
  if (!hexMatch) return null;
  const hex = hexMatch[1];
  // 三位简写展开成六位，后面按两位一拆喵
  const full = hex.length === 3 ? hex.split("").map((ch) => ch + ch).join("") : hex;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

/** 按设备序号把应用色调成深浅色，认不出颜色时原样返回喵。
 *
 * 输入：基础色、设备序号（-1 表示认不出）、可选的设备总数。
 * 输出：同色相的深浅色；序号 0 或 -1 时原样返回基础色。
 * 边界：颜色格式不认识时也原样返回，绝不画脏色喵。
 */
function deviceShade(baseColor, index, total) {
  // 第一台设备不换算，省一次解析；查不到设备（-1）也按原色画喵
  if (!index || index < 0) return baseColor;
  // 解析基础色，认不出就不动它喵
  const parsed = parseCssColor(baseColor);
  // 喵~防御：格式不认识时宁可同色，也不要画出脏色喵
  if (!parsed) return baseColor;
  const hsl = rgbToHsl(parsed.r, parsed.g, parsed.b);
  // 起点先夹进 0.26–0.80，太浅太深的图标都能拉出一串看得见的深浅喵
  const start = Math.min(0.8, Math.max(0.26, hsl.l));
  // 亮色往深走、暗色往浅走，但都不许走到接近纯白/纯黑，白底上才一直看得清喵
  const target = start >= 0.3 ? 0.18 : 0.62;
  const ratio = deviceShadeRatio(index, total);
  const lightness = Math.min(0.92, Math.max(0.12, start + (target - start) * ratio));
  // 越靠后的设备彩度略增，一串泳道不至于灰成一团喵
  const saturation = Math.min(0.95, hsl.s + 0.05 * ratio);
  const shaded = hslToRgb(hsl.h, saturation, lightness);
  return `rgb(${shaded.r}, ${shaded.g}, ${shaded.b})`;
}

/** 算出某台设备在某个应用自己的设备清单里排第几：只有该应用真在多台设备上出现时才分深浅喵。
 *
 * 输入：应用名、设备名、应用 → 该应用出现的设备名列表。
 * 输出：{ index, total }；单设备应用固定 index = 0（原色）。
 * 边界：查不到应用或清单时按单设备处理，宁可原色也不无端压暗喵。
 */
function appDeviceShadeSpot(app, deviceKey, appDevices) {
  // 取这个应用自己的设备清单，拿不到就当空清单喵
  const devices = (appDevices && appDevices.get(app)) || [];
  // 喵~防御：清单不是数组时按空清单算，别让脏数据把颜色算成 NaN 喵
  const list = Array.isArray(devices) ? devices : [];
  // 这个应用一共出现在几台设备上，决定渐变的跨度喵
  const total = list.length;
  // 单设备应用（含查不到的应用）一律用原色，本屏有几台设备都不影响它喵
  if (total <= 1) return { index: 0, total };
  // 多设备应用按设备在自己清单里的序号取深浅，认不出的设备给 -1（原色）喵
  const index = deviceKey ? list.indexOf(deviceKey) : -1;
  return { index, total };
}

/** 悬浮色点的颜色：和时间轴色块用同一套「应用自己的设备清单」口径喵。 */
function tipShadeColor(app, device, colors, appDevices) {
  // 先取这一屏的基础色，空档 / 离线没有应用色就不画色点喵
  const base = app ? (colors || new Map()).get(app) : "";
  // 喵~防御：没有基础色时返回空串，调用方据此不画色点喵
  if (!base) return "";
  // 按这个应用自己的设备序位取深浅，单设备应用必然是原色喵
  const spot = appDeviceShadeSpot(app, device, appDevices);
  return deviceShade(base, spot.index, spot.total);
}

/** 按档位微调明度，用来给撞色的泳道让出区分度喵。 */
function shiftLightness(color, steps) {
  // 解析颜色，认不出就原样返回喵
  const parsed = parseCssColor(color);
  // 喵~防御：认不出的颜色不动，避免画出脏色喵
  if (!parsed) return color;
  const hsl = rgbToHsl(parsed.r, parsed.g, parsed.b);
  // 奇偶档交替加减，相邻两条泳道一眼能分开喵
  const direction = steps % 2 === 1 ? 1 : -1;
  const delta = direction * 0.06 * Math.ceil(steps / 2);
  const lightness = Math.min(0.92, Math.max(0.14, hsl.l + delta));
  const shifted = hslToRgb(hsl.h, hsl.s, lightness);
  // 微调后再走一遍对比度修正，避免为了区分颜色把色块调得太浅喵
  return readableColor(shifted.r, shifted.g, shifted.b);
}

/** 同屏撞色时按次序微调明度，避免两条泳道一个颜色喵。 */
function dedupeLaneColors(apps, colorOf) {
  // 已经用掉的颜色，存成 r,g,b 三元组，方便算色差喵
  const used = [];
  // 每个通道至少差这么多，肉眼看得出是两种颜色喵
  const MIN_GAP = 18;
  // 判断候选色和已用颜色是否拉得开喵
  const isDistinct = (value) => {
    const parsed = parseCssColor(value);
    // 喵~防御：解析不了就当撞色，别把坏值放进颜色表喵
    if (!parsed) return false;
    // 逐个已用颜色比，任一通道差太小都算撞色喵
    for (const other of used) {
      // 取三个通道里最大的差值，避免只差一个通道却看不出来喵
      const gap = Math.max(
        Math.abs(parsed.r - other.r),
        Math.abs(parsed.g - other.g),
        Math.abs(parsed.b - other.b),
      );
      // 差值不够大就继续换下一档喵
      if (gap < MIN_GAP) return false;
    }
    // 和所有已用颜色都拉得开喵
    return true;
  };
  // 应用 → 最终颜色喵
  const result = new Map();
  for (const app of apps) {
    let color = colorOf(app);
    // 喵~防御：最多试 6 档微调，都不行就认了，别死循环喵
    for (let attempt = 1; attempt <= 6 && !isDistinct(color); attempt += 1) {
      color = shiftLightness(colorOf(app), attempt);
    }
    // 记下最终颜色，后面的应用不能再撞喵
    const parsed = parseCssColor(color);
    if (parsed) used.push(parsed);
    result.set(app, color);
  }
  return result;
}

/* ==================== 应用图标取色 ==================== */

/** 把颜色通道夹到 0-255 的整数，脏数据也不会把颜色算崩喵。 */
function colorChannel(value) {
  // 先转成数字，字符串形式的通道值也能用喵
  const number = Number(value);
  // 喵~防御：NaN / Infinity 这类脏值统一归零，避免后面算出 NaN 颜色喵
  if (!Number.isFinite(number)) return 0;
  // 四舍五入并夹到合法区间喵
  return Math.min(255, Math.max(0, Math.round(number)));
}

/** 按人眼权重算 0-255 的亮度，用来判断颜色在白底上够不够清楚喵。 */
function colorLuminance(red, green, blue) {
  // 三个通道先夹到合法区间，防止调用方传进越界值喵
  const r = colorChannel(red);
  const g = colorChannel(green);
  const b = colorChannel(blue);
  // 0.299 / 0.587 / 0.114 是常用的感知亮度权重，绿色最亮、蓝色最暗喵
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

/** 把 RGB 转成 HSL（h 用度、s / l 用 0-1），亮度修正走 L 通道最直观喵。 */
function rgbToHsl(red, green, blue) {
  // 三个通道先夹到 0-255 再归一化到 0-1 喵
  const r = colorChannel(red) / 255;
  const g = colorChannel(green) / 255;
  const b = colorChannel(blue) / 255;
  // 最大值与最小值决定亮度和饱和度喵
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  // 亮度就是最大最小值的平均喵
  const lightness = (max + min) / 2;
  // 三个通道一样时是灰色，色相和饱和度都是 0 喵
  if (max === min) return { h: 0, s: 0, l: lightness };
  // 差值用来算饱和度和色相喵
  const delta = max - min;
  // 亮度超过一半时用另一套分母，保证饱和度落在 0-1 喵
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  // 色相按哪个通道最大分三种情况算喵
  let hue;
  if (max === r) {
    hue = ((g - b) / delta) % 6;
  } else if (max === g) {
    hue = (b - r) / delta + 2;
  } else {
    hue = (r - g) / delta + 4;
  }
  // 转成角度喵
  hue *= 60;
  // 喵~防御：JS 取模可能出负数，补一圈回到 0-360 喵
  if (hue < 0) hue += 360;
  return { h: hue, s: saturation, l: lightness };
}

/** 把 HSL 转回 RGB，返回 0-255 的整数三元组喵。 */
function hslToRgb(hue, saturation, lightness) {
  // 色相先归一到 0-360，调用方传负数也不会算歪喵
  const h = ((Number(hue) || 0) % 360 + 360) % 360;
  // 饱和度与亮度夹到 0-1，避免算出越界颜色喵
  const s = Math.min(1, Math.max(0, Number(saturation) || 0));
  const l = Math.min(1, Math.max(0, Number(lightness) || 0));
  // 色度：饱和度越高、亮度离 0.5 越远，色度越小喵
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  // 次分量，用来在相邻两个通道之间插值喵
  const second = chroma * (1 - Math.abs(((h / 60) % 2) - 1));
  // 亮度补正量，保证最终颜色落在正确亮度上喵
  const offset = l - chroma / 2;
  // 按色相所在的 60 度区间决定三个通道的排列喵
  let channels;
  // 0-60 度：红到黄，红通道最大喵
  if (h < 60) {
    channels = [chroma, second, 0];
  // 60-120 度：黄到绿，绿通道最大喵
  } else if (h < 120) {
    channels = [second, chroma, 0];
  // 120-180 度：绿到青，绿通道最大喵
  } else if (h < 180) {
    channels = [0, chroma, second];
  // 180-240 度：青到蓝，蓝通道最大喵
  } else if (h < 240) {
    channels = [0, second, chroma];
  // 240-300 度：蓝到品红，蓝通道最大喵
  } else if (h < 300) {
    channels = [second, 0, chroma];
  // 300-360 度：品红到红，红通道最大喵
  } else {
    channels = [chroma, 0, second];
  }
  // 加上亮度补正量再换算回 0-255 的整数喵
  return {
    r: colorChannel((channels[0] + offset) * 255),
    g: colorChannel((channels[1] + offset) * 255),
    b: colorChannel((channels[2] + offset) * 255),
  };
}

/** 按 WCAG 公式算相对亮度（0-1），对比度计算要用它喵。 */
function relativeLuminance(red, green, blue) {
  // 单个通道先归一化，再按 sRGB 曲线转成线性亮度喵
  const linear = (value) => {
    // 通道先夹到 0-255 再除以 255 喵
    const normalized = colorChannel(value) / 255;
    // 暗部用线性段，亮部用 2.4 次幂，这是 WCAG 的标准公式喵
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  // 0.2126 / 0.7152 / 0.0722 是 sRGB 的相对亮度权重喵
  return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
}

/** 算两个颜色的对比度（1-21），数字越大越清楚喵。 */
function contrastRatio(first, second) {
  // 喵~防御：颜色不是三元组时按黑色处理，别让对比度算出 NaN 喵
  const one = Array.isArray(first) ? first : [0, 0, 0];
  const two = Array.isArray(second) ? second : [0, 0, 0];
  // 分别算两边的相对亮度喵
  const firstLuminance = relativeLuminance(one[0], one[1], one[2]);
  const secondLuminance = relativeLuminance(two[0], two[1], two[2]);
  // 亮的一边做分子，暗的一边做分母喵
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  // WCAG 对比度公式，+0.05 是防止除零的偏移量喵
  return (lighter + 0.05) / (darker + 0.05);
}

/** 把混合色修到浅色底上看得清：太暗提亮，再按对比度强制压暗到 3:1 以上喵。 */
function readableColor(red, green, blue) {
  // 先算感知亮度，0-255 越大越接近白色喵
  const luminance = colorLuminance(red, green, blue);
  // 转成 HSL，亮度与饱和度修正都在这套坐标里做喵
  const hsl = rgbToHsl(red, green, blue);
  // 太暗（例如纯黑图标）：先把亮度提到 0.34，别跟正文黑字混在一起喵
  if (luminance < 26) {
    hsl.l = Math.max(hsl.l, 0.34);
    // 有一点彩度就补到 0.3，深色图标也能看出是哪个应用喵
    if (hsl.s > 0.05) hsl.s = Math.max(hsl.s, 0.3);
  }
  // 时间轴轨道的浅灰底色（#f2f3f5），色块至少要在这个底色上达到 3:1 对比度喵
  const background = [242, 243, 245];
  // 当前颜色已经够清楚就直接用，正常颜色不会被改暗喵
  const current = hslToRgb(hsl.h, hsl.s, hsl.l);
  // 对比度达到 3:1 就原样返回喵
  if (contrastRatio([current.r, current.g, current.b], background) >= 3) {
    return `rgb(${current.r}, ${current.g}, ${current.b})`;
  }
  // 二分亮度：在 0 到当前亮度之间找刚好达到 3:1 的最高亮度喵
  let low = 0;
  let high = hsl.l;
  // 20 次二分足够把误差压到肉眼看不出差别喵
  for (let step = 0; step < 20; step += 1) {
    // 取中间亮度试一档喵
    const middle = (low + high) / 2;
    // 中间亮度转回 RGB 算对比度喵
    const candidate = hslToRgb(hsl.h, hsl.s, middle);
    // 达到 3:1 说明还能再亮一点，往上半区找喵
    if (contrastRatio([candidate.r, candidate.g, candidate.b], background) >= 3) {
      low = middle;
    } else {
      // 不够清楚就继续往暗里找喵
      high = middle;
    }
  }
  // 取满足条件的最高亮度，保住原来的色相和彩度喵
  const fixed = hslToRgb(hsl.h, hsl.s, low);
  // 统一输出成 css 能直接用的 rgb() 字符串喵
  return `rgb(${fixed.r}, ${fixed.g}, ${fixed.b})`;
}

/** 把图标像素按 alpha 加权混成一个颜色，取不到有效像素时返回 null 喵。
 *
 * 输入：[[r, g, b, a], ...]，每个通道 0-255。
 * 输出："rgb(r, g, b)" 字符串；全透明 / 全是黑白 / 空输入返回 null。
 * 边界：alpha 小于 32、接近纯黑 / 纯白的像素直接跳过，避免底色和字形把主色拉灰喵。
 */
function mixIconPixels(pixels) {
  // 喵~防御：不是数组或空数组直接算取色失败喵
  if (!Array.isArray(pixels) || !pixels.length) return null;
  // 累计 alpha 权重与三个通道的加权和喵
  let alphaTotal = 0;
  let redTotal = 0;
  let greenTotal = 0;
  let blueTotal = 0;
  for (const pixel of pixels) {
    // 喵~防御：结构不对的像素跳过，别让一个脏值毁掉整张图喵
    if (!Array.isArray(pixel) || pixel.length < 4) continue;
    // alpha 先夹到 0-255，越界值也能安全参与计算喵
    const alpha = colorChannel(pixel[3]);
    // alpha 太小说明是透明边缘，直接跳过喵
    if (alpha < 32) continue;
    // 三个通道先夹到 0-255，后面判黑白和加权都要用喵
    const red = colorChannel(pixel[0]);
    const green = colorChannel(pixel[1]);
    const blue = colorChannel(pixel[2]);
    // 喵~注意：接近纯白多半是图标底色，混进去会把主色冲淡，直接跳过喵
    if (red >= 235 && green >= 235 && blue >= 235) continue;
    // 喵~注意：接近纯黑多半是字形或描边，混进去会把主色压灰，直接跳过喵
    if (red <= 24 && green <= 24 && blue <= 24) continue;
    // 三个通道按 alpha 加权累加，半透明像素的权重自然更小喵
    redTotal += red * alpha;
    greenTotal += green * alpha;
    blueTotal += blue * alpha;
    // 权重也跟着累加，最后做除法喵
    alphaTotal += alpha;
  }
  // 喵~防御：全透明图标没有有效像素，视为取色失败喵
  if (alphaTotal <= 0) return null;
  // 加权平均得到混合色，再交给可读性修正喵
  return readableColor(redTotal / alphaTotal, greenTotal / alphaTotal, blueTotal / alphaTotal);
}

/** 图标取色成功就用图标色，失败时退回原来的配色方案喵。 */
function pickAppColor(iconColor, fallbackColor) {
  // 只有拿到非空字符串才算取色成功，null / undefined 都走兜底喵
  if (typeof iconColor === "string" && iconColor) return iconColor;
  // 喵~防御：没取到色就原样返回色板色，保证色块永远有颜色喵
  return fallbackColor;
}

/** 读取一个图标的像素，返回 [[r, g, b, a], ...]；失败时返回 null 喵。 */
function sampleIconPixels(url) {
  // 包成 Promise，调用方不用关心图片加载的异步细节喵
  return new Promise((resolve) => {
    // 用 Image 加载同源图标，canvas 读像素不会被跨域污染喵
    const image = new Image();
    // 加载成功：缩到 24×24 画到离屏 canvas 上读像素喵
    image.onload = () => {
      // 喵~注意：canvas 读像素要求同源，图标换成跨域地址时会被安全策略拦住喵
      try {
        // 离屏 canvas 只用来取样，不挂到页面上喵
        const canvas = document.createElement("canvas");
        canvas.width = ICON_SAMPLE_SIZE;
        canvas.height = ICON_SAMPLE_SIZE;
        // 拿 2D 上下文，拿不到就当取色失败喵
        const context = canvas.getContext("2d", { willReadFrequently: true });
        // 喵~防御：浏览器禁用 canvas 时直接返回失败喵
        if (!context) {
          resolve(null);
          return;
        }
        // 先清空成全透明，避免画布默认底色混进平均色喵
        context.clearRect(0, 0, ICON_SAMPLE_SIZE, ICON_SAMPLE_SIZE);
        // 缩放到 24×24 采样，小图标也够代表主色喵
        context.drawImage(image, 0, 0, ICON_SAMPLE_SIZE, ICON_SAMPLE_SIZE);
        // 读回像素数据，RGBA 四个一组喵
        const data = context.getImageData(0, 0, ICON_SAMPLE_SIZE, ICON_SAMPLE_SIZE).data;
        // 拆成 [[r, g, b, a], ...] 交给纯函数，DOM 逻辑到这里为止喵
        const pixels = [];
        for (let index = 0; index < data.length; index += 4) {
          pixels.push([data[index], data[index + 1], data[index + 2], data[index + 3]]);
        }
        // 像素数组就是取样结果，交给 Promise 继续做纯计算喵
        resolve(pixels);
      } catch (error) {
        // 喵~防御：画布被污染或读像素被拒时按失败处理，退回原配色喵
        resolve(null);
      }
    };
    // 加载失败（图标被删、口令失效）同样按取色失败处理喵
    image.onerror = () => resolve(null);
    // 带上口令的图标地址，和页面上 <img> 用的是同一个喵
    image.src = url;
  });
}

/** 取应用对应的图标键，没有图标的应用返回空串喵。 */
function iconColorKey(entry) {
  // 喵~防御：entry 可能只有色块没有图标，空值直接返回喵
  if (!entry || !entry.icon_key) return "";
  // 统一成字符串，Map 的键类型不会飘喵
  return String(entry.icon_key);
}

/** 给一个图标键启动取色任务，算完把颜色写进缓存并刷新时间轴喵。 */
function startIconColorTask(iconKey) {
  // 图片地址和页面上的 <img> 完全一致，口令走查询串喵
  const task = sampleIconPixels(iconUrl(iconKey))
    .then((pixels) => {
      // 有像素就混合取色，没有像素（全透明 / 读失败）记成 null 喵
      iconColorCache.set(iconKey, pixels ? mixIconPixels(pixels) : null);
    })
    .catch(() => {
      // 喵~防御：任何异常都当取色失败，界面必须退回原配色喵
      iconColorCache.set(iconKey, null);
    })
    .then(() => {
      // 任务结束，从进行中的表里移除，缓存已经写好不会再重算喵
      iconColorTasks.delete(iconKey);
      // 颜色算出来了，排队重画时间轴，保留滚动位置喵
      queueTimelineColorRefresh();
    });
  // 记下进行中的任务，同一个图标不会重复请求喵
  iconColorTasks.set(iconKey, task);
}

/** 给这一屏所有带图标的应用安排取色，已经算过的直接跳过喵。 */
function ensureIconColors(entries) {
  for (const entry of entries) {
    // 每个应用用第一段记录的图标键，和泳道标题上的图标是同一个喵
    const iconKey = iconColorKey(entry.blocks[0]);
    // 没图标或已经有结果（包括算失败）就不再请求喵
    if (!iconKey || iconColorCache.has(iconKey)) continue;
    // 正在取色的图标交给原来的任务，别重复发请求喵
    if (iconColorTasks.has(iconKey)) continue;
    // 真正启动取色，结果回来会自己触发重画喵
    startIconColorTask(iconKey);
  }
}

/** 取色完成后重画时间轴：保留横向滚动位置，不整页闪喵。 */
function queueTimelineColorRefresh() {
  // 同一轮只排一次重画，多个图标同时回来时合并成一次喵
  if (iconColorRefreshQueued) return;
  iconColorRefreshQueued = true;
  // 真正重画的逻辑抽出来，rAF 和 setTimeout 都能复用喵
  const run = () => {
    iconColorRefreshQueued = false;
    // 喵~防御：数据或元素还没准备好就不重画，避免画出一个空轴喵
    if (!state.timeline || !el.tlScroll || !el.tlTrack) return;
    // 喵~防御：已经切到别的标签页就不用重画了，切回来会重新渲染喵
    if (state.tab !== "timeline") return;
    // 喵~防御：换设备 / 换日期时轨道已被清空，别把上一天的数据画回去喵
    if (!el.tlTrack.innerHTML) return;
    // 记下横向滚动位置，重画后原样还回去，用户正在看的那段不会跳走喵
    const scrollLeft = el.tlScroll.scrollLeft;
    // 喵~注意：只重画时间轴内部，不动页面其他部分，避免整页闪烁喵
    renderTimeline(state.timeline);
    // 恢复滚动位置喵
    if (scrollLeft > 0) el.tlScroll.scrollLeft = scrollLeft;
  };
  // 下一帧再画，几个图标接连回来时只重画一次喵
  if (typeof window !== "undefined" && window.requestAnimationFrame) {
    window.requestAnimationFrame(run);
  } else {
    // 喵~防御：没有 rAF 的环境（老浏览器）退回定时器喵
    setTimeout(run, 0);
  }
}

/** 把 ISO 时间换算成"当天第几分钟"喵。 */
function minutesOfDay(isoText) {
  const moment = new Date(isoText);
  // 按服务端时区换算成当天第几分钟，浏览器时区不参与喵
  const shifted = inServerZone(moment);
  return shifted.getUTCHours() * 60 + shifted.getUTCMinutes() + shifted.getUTCSeconds() / 60;
}

/** 取某个时刻在当天占的比例（0-1），按服务端时区算喵。 */
function dayRatioOf(moment) {
  const shifted = inServerZone(moment);
  const second =
    shifted.getUTCHours() * 3600 +
    shifted.getUTCMinutes() * 60 +
    shifted.getUTCSeconds() +
    shifted.getUTCMilliseconds() / 1000;
  return second / DAY_SECONDS;
}

/** 今天的时间轴最多画到「现在」；非今天的日期返回 1 表示整天都画喵。 */
function timelineNowRatio(body) {
  // 喵~防御：没有日期信息时按整天处理喵
  if (!body || !body.date) return 1;
  if (body.date !== localDateText(serverNow())) return 1;
  return Math.min(1, Math.max(0, dayRatioOf(serverNow())));
}

/** 时间轴数据的指纹，静默刷新时用它判断要不要重画喵。 */
function timelineSignature(body) {
  const segments = body.segments || [];
  const last = segments.length ? segments[segments.length - 1] : null;
  return [
    body.date || "",
    segments.length,
    last ? `${last.app}|${last.start}|${last.end}` : "",
    (body.states || []).length,
    (body.title_spans || []).length,
    Math.round(body.total_seconds || 0),
  ].join("#");
}

/** 渲染时间轴页的下拉框与日期输入喵。 */
function renderTimelineControls() {
  const current = state.timelineDeviceId || (state.devices[0] && state.devices[0].device_id) || "";
  // 自用时各设备时间不会重叠，合并成一条时间轴更好看喵
  const mergedOption = `<option value="__all__"${current === "__all__" ? " selected" : ""}>全部设备（合并成一条时间轴）</option>`;
  // 设备组存在 localStorage 里，前端可编辑，数组顺序就是优先级喵
  const groups = state.people;
  const groupOptions = groups.length
    ? `<optgroup label="设备组">${groups
        .map((group, index) => {
          const value = `group:${index}`;
          return `<option value="${value}"${current === value ? " selected" : ""}>${escapeHtml(group.name)}（${group.devices.length} 台，按优先级合并）</option>`;
        })
        .join("")}</optgroup>`
    : "";
  el.tlDevice.innerHTML = mergedOption + groupOptions + `<optgroup label="单台设备">` + state.devices
    .map((device) => {
      const label = `${device.display_name}（${device.device_id}）`;
      return `<option value="${escapeHtml(device.device_id)}"${device.device_id === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("") + `</optgroup>`;
  // 喵~防御：异步补全选项后把选中项设回去，否则会被第一个选项顶掉喵
  if (current) {
    el.tlDevice.value = current;
  }
  if (!state.timelineDate) state.timelineDate = localDateText(serverNow());
  el.tlDate.value = state.timelineDate;
}

/** 载入并渲染某天的时间轴喵。 */
async function loadTimeline(options = {}) {
  // 静默刷新：不闪「加载中」、不清空色块、保留横向滚动位置喵
  const silent = Boolean(options.silent);
  // 下拉框每次都重建，新设备才会及时出现在列表里（当前选中项会保留）喵
  renderTimelineControls();
  const deviceId = state.timelineDeviceId || el.tlDevice.value;
  // 喵~防御：一台设备都没有时不用发请求喵
  if (!deviceId) {
    el.tlSummary.textContent = "";
    el.tlTrack.innerHTML = '<p class="empty" style="margin:0">还没有任何设备</p>';
    el.tlLanes.innerHTML = "";
    el.tlLegend.innerHTML = "";
    // 喵~注意：这一页也算画完了，标记要置上，否则截图会白等到超时喵
    markShotReady("timeline");
    return;
  }
  state.timelineDeviceId = deviceId;
  const date = el.tlDate.value || localDateText(serverNow());
  state.timelineDate = date;
  if (!silent) {
    el.tlSummary.textContent = "加载中…";
    // 喵~注意：非静默刷新才清就绪标记——自动刷新和增量刷新都是 silent，
    // 它们不该把「已经画好了」的结论撤销，否则截图会一直等不到喵
    clearShotReady();
    // 喵~注意：换设备或换日期时先清空，否则旧色块会一直挂到新数据回来喵
    el.tlTrack.innerHTML = "";
    el.tlLanes.innerHTML = "";
    el.tlLegend.innerHTML = "";
    el.tlPointer.hidden = true;
    el.tlTip.hidden = true;
  }
  try {
    // 东八区是 +480，JS 的 getTimezoneOffset 符号相反喵
    // 时区偏移以服务端为准，浏览器时区不参与喵
    const tzOffset = state.tzOffsetMinutes;
    const query = `date=${encodeURIComponent(date)}&tz_offset_minutes=${tzOffset}`;
    const groupMatch = /^group:(\d+)$/.exec(deviceId);
    const group = groupMatch ? state.people[Number(groupMatch[1])] : null;
    // 喵~防御：组被删掉或还没加载完时退回「全部设备」，别把空设备列表发给服务端喵
    const groupDevices = group && group.devices.length ? group.devices : null;
    const isMerged = deviceId === "__all__" || groupMatch !== null;
    // 记下当前是不是合并视图，泳道标题要靠它决定标不标设备名喵
    state.timelineMerged = isMerged;
    const mergedIds = groupDevices || state.devices.map((device) => device.device_id);
    // 喵~防御：设备列表还没拉回来时 mergedIds 是空的，直接发请求会被服务端判 422，
    // 时间轴于是一直空着——这正是截图拍到空轨道的原因之一，这里先等等再走喵
    if (isMerged && !mergedIds.length) {
      el.tlSummary.textContent = "加载中…";
      // 稍后重试，设备列表回来后这次就能正常发请求喵
      window.setTimeout(() => {
        if (state.tab === "timeline") loadTimeline(options);
      }, 300);
      return;
    }
    const url = isMerged
        ? `/api/v1/timeline?devices=${encodeURIComponent(mergedIds.join(","))}&${query}`
        : `/api/v1/devices/${encodeURIComponent(deviceId)}/timeline?${query}`;
    const body = await api(url);
    // 时间轴响应带服务端"现在"，顺手校准浏览器时钟喵
    applyServerClock(body.server_now);
    // 时区以服务端为准，换个时区的电脑看也一致喵
    if (Number.isFinite(body.tz_offset_minutes)) state.tzOffsetMinutes = body.tz_offset_minutes;
    // 喵~防御：静默刷新且数据完全没变时只挪「现在」竖线，不重画色块，避免闪烁喵
    const signature = timelineSignature(body);
    if (silent && signature === state.timelineSignature) {
      state.timeline = body;
      updateTimelineNowLine();
      setLive("ok", `已更新 ${formatClock(serverNow())}`);
      return;
    }
    // 重画前记住横向滚动位置，放大后刷新不会跳回最左边喵
    const scrollLeft = el.tlScroll ? el.tlScroll.scrollLeft : 0;
    state.timelineSignature = signature;
    state.timeline = body;
    renderTimeline(body);
    // 恢复滚动位置喵
    if (el.tlScroll && scrollLeft > 0) el.tlScroll.scrollLeft = scrollLeft;
  } catch (error) {
    if (error.unauthorized) {
      // 喵~注意：口令无效时页面会弹遮罩，截图那边有专门的自检会拦下，这里照样置位
      // 免得后端白等到超时喵
      markShotReady("timeline");
      handleUnauthorized();
      return;
    }
    // 喵~防御：静默刷新失败时保留已有画面，只把错误说一声喵
    if (silent) {
      setLive("error", "时间轴刷新失败");
      // 静默刷新失败时旧画面还在，本来就已就绪，标记保持即可喵
      markShotReady("timeline");
      return;
    }
    el.tlSummary.textContent = "";
    el.tlTrack.innerHTML = `<p class="empty" style="margin:0">加载失败：${escapeHtml(error.message)}</p>`;
    // 喵~注意：加载失败也要置位，把错误画面截下来总比后端一直等到超时好喵
    markShotReady("timeline");
  }
}

/** 把空档区间画成顶层斜纹块；离线按主人要求直接留空喵。 */
function buildStateBlocks(body, nowRatio) {
  // 窗口起点，用来把绝对时间换算成当天第几分钟喵
  const windowStart = body.start ? new Date(body.start) : null;
  if (!windowStart) return [];
  // 喵~防御：空档也不许画到「现在」之后喵
  const limitMinute = nowRatio >= 1 ? DAY_MINUTES : nowRatio * DAY_MINUTES;
  const blocks = [];
  for (const interval of body.states || []) {
    // 喵~防御：离线不画任何东西，轴上空着就是没心跳喵
    if (interval.kind !== "afk") continue;
    const startMinute = (new Date(interval.start) - windowStart) / 60000;
    const endMinute = (new Date(interval.end) - windowStart) / 60000;
    // 喵~防御：跨出当天窗口的部分裁掉，避免色块画到轴外面喵
    const left = Math.max(0, Math.min(DAY_MINUTES, startMinute));
    const right = Math.max(0, Math.min(DAY_MINUTES, endMinute, limitMinute));
    if (right - left < 0.05) continue;
    const tip = `AFK ${formatClock(interval.start)}-${formatClock(interval.end)} · ${formatDuration(interval.seconds)}`;
    blocks.push(
      // 原生 title 会弹系统灰框，改成 role + aria-label，读屏软件照样能读到喵
      `<div class="tl-gap" role="img" aria-label="${escapeHtml(tip)}" style="left:${((left / DAY_MINUTES) * 100).toFixed(3)}%;width:${(((right - left) / DAY_MINUTES) * 100).toFixed(3)}%"></div>`
    );
  }
  return blocks;
}

/** 时间轴汇总行文案喵。 */
function timelineSummaryText(body, segmentCount) {
  // 喵~注意：服务端默认心跳超时是 60 秒，这里的兜底值要和它一致喵
  const timeout = Math.round((body.heartbeat_timeout_seconds || 60) / 60);
  return `${body.date} · 总计 ${formatDuration(body.total_seconds)} · AFK ${formatDuration(body.afk_seconds || 0)} · 离线 ${formatDuration(body.offline_seconds || 0)} · ${segmentCount} 段（离线留空，${timeout} 分钟没心跳算离线）`;
}

/** 时间轴图例里关于状态的说明喵。 */
function stateLegendHtml() {
  return `<span><i class="lg-gap"></i>AFK</span><span><i class="lg-blank"></i>离线（无心跳，留空）</span>`;
}

/** 时间轴泳道上的设备名后缀：合并视图（组 / 所有设备）始终标注，单设备视图不标喵。 */
function laneDeviceSuffix(devices, isMerged) {
  // 喵~注意：合并视图里即使只有一台设备也要标出来，否则看不出这个应用是哪台设备用的喵
  if (!isMerged) return "";
  const names = (devices || []).filter(Boolean);
  // 喵~防御：服务端没给设备名时保持原样，别显示空括号喵
  if (!names.length) return "";
  // 太多设备时只列前两台，避免泳道标题挤成一行字喵
  const shown = names.slice(0, 2).join("、");
  const suffix = names.length > 2 ? `${shown} 等 ${names.length} 台` : shown;
  return ` <span class="tl-lane-device">（${escapeHtml(suffix)}）</span>`;
}

/** 从刻度阶梯里挑一档，挑「刚好够用」的最小值喵。 */
function pickTickStep(target) {
  // 阶梯是从大到小排的，倒着找第一个够用的就是最细的喵
  for (let index = TICK_STEPS.length - 1; index >= 0; index -= 1) {
    if (TICK_STEPS[index] >= target) return TICK_STEPS[index];
  }
  // 喵~防御：比最小档还小就退回最小档喵
  return TICK_STEPS[TICK_STEPS.length - 1];
}

/** 把秒数格式化成刻度文字，越放大越精细喵。 */
function formatTickLabel(second, step) {
  const pad = (value) => String(value).padStart(2, "0");
  const hour = Math.floor(second / 3600);
  const minute = Math.floor((second % 3600) / 60);
  const rest = second % 60;
  // 小时级刻度只标到小时喵
  if (step >= 3600) return `${pad(hour)}:00`;
  // 分钟级刻度标到分钟喵
  if (step >= 60) return `${pad(hour)}:${pad(minute)}`;
  // 秒级刻度把秒也带上喵
  return `${pad(hour)}:${pad(minute)}:${pad(rest)}`;
}

/** 按当前可视范围渲染刻度，放大到秒级也不会生成上万个标签喵。 */
function renderTimelineAxis(zoom) {
  // 喵~防御：元素没准备好就跳过喵
  if (!el.tlAxis) return;
  const zoomValue = zoom || timelineZoom();
  // 一屏大概放 10 个刻度，放大越多分度值越细喵
  const step = pickTickStep(DAY_SECONDS / zoomValue / 10);
  const track = el.tlTrack;
  const scroll = el.tlScroll;
  const totalWidth = track ? track.getBoundingClientRect().width : 0;
  const viewWidth = scroll ? scroll.clientWidth : 0;
  const scrolled = scroll ? scroll.scrollLeft : 0;
  // 可视区间左右各留一屏余量，滚动时不用马上补画喵
  const ratioStart = totalWidth > 0 && viewWidth > 0 ? Math.max(0, (scrolled - viewWidth) / totalWidth) : 0;
  const ratioEnd = totalWidth > 0 && viewWidth > 0 ? Math.min(1, (scrolled + viewWidth * 2) / totalWidth) : 1;
  const from = Math.max(0, Math.floor((ratioStart * DAY_SECONDS) / step) * step);
  const to = Math.min(DAY_SECONDS, Math.ceil((ratioEnd * DAY_SECONDS) / step) * step);
  const parts = [];
  for (let second = from; second <= to; second += step) {
    const percent = (second / DAY_SECONDS) * 100;
    // 首尾两个刻度往里收，避免被滚动容器切掉半截喵
    const edge = percent <= 0.5 ? ' data-edge="start"' : percent >= 99.5 ? ' data-edge="end"' : "";
    parts.push(`<span${edge} style="left:${percent.toFixed(4)}%">${formatTickLabel(second, step)}</span>`);
  }
  el.tlAxis.innerHTML = parts.join("");
}

/** 按当前比例尺把相邻段聚成可视块，间隔不到一像素时合并，避免亚像素碎片喵。 */
function buildVisualBlocks(items, pxPerSecond) {
  const blocks = [];
  for (const item of items) {
    const startMs = new Date(item.start).getTime();
    const endMs = new Date(item.end).getTime();
    // 喵~防御：时间解析失败的段直接跳过，别把整天画歪喵
    if (Number.isNaN(startMs) || Number.isNaN(endMs)) continue;
    const last = blocks[blocks.length - 1];
    // 这台设备的名字，合并视图里要用它决定深浅喵
    const deviceKey = item.device_name || "";
    // 喵~注意：只有同一台设备、间隔不到一个像素才并进上一块，否则深浅会串色喵
    if (
      last &&
      last.app === item.app &&
      last.deviceKey === deviceKey &&
      ((startMs - last.endMs) / 1000) * pxPerSecond < 1
    ) {
      last.endMs = Math.max(last.endMs, endMs);
      last.seconds += item.seconds;
      last.count += 1;
      continue;
    }
    blocks.push({ app: item.app, deviceKey, startMs, endMs, seconds: item.seconds, count: 1 });
  }
  return blocks;
}

/** 把一个可视块渲染成色块，宽度严格等于块的起止时间喵。 */
function visualBlockHtml(block, color, nowRatio, appDevices) {
  const startMinute = minutesOfDay(new Date(block.startMs));
  const endMinute = Math.max(startMinute, minutesOfDay(new Date(block.endMs)));
  const left = (startMinute / DAY_MINUTES) * 100;
  // 喵~防御：今天的色块一律不画到「现在」之后，否则会出现未来帧喵
  const limit = nowRatio >= 1 ? 100 : nowRatio * 100;
  if (left >= limit) return "";
  const right = Math.min((endMinute / DAY_MINUTES) * 100, limit);
  // 宽度按真实时长算，短块靠 CSS 的 1px 下限保证看得见，但绝不会把空档涂成应用喵
  const width = Math.max(0, right - left);
  const range = `${formatClock(new Date(block.startMs))}-${formatClock(new Date(block.endMs))}`;
  // 只有这个应用真在多台设备上出现才调深浅，单设备应用保持原始图标色喵
  const spot = appDeviceShadeSpot(block.app, block.deviceKey, appDevices);
  // 按上面算出的「本应用设备序位」着色，跨度用该应用自己的设备数喵
  const fill = deviceShade(color, spot.index, spot.total);
  // 合并视图里色块自己说明设备，鼠标停在上面就知道是谁的喵
  const deviceText = block.deviceKey ? ` · ${block.deviceKey}` : "";
  // 合并过的块要在提示里说明段数，避免被当成一段连续使用喵
  const label = block.count > 1
    ? `${block.app}${deviceText} ${range} · ${block.count} 段合计 ${formatDuration(block.seconds)}`
    : `${block.app}${deviceText} ${range} · ${formatDuration(block.seconds)}`;
  // 原生 title 会弹浏览器灰框，统一挪到 aria-label，色块照样有可读文本喵
  return `<div class="tl-block" role="img" aria-label="${escapeHtml(label)}" style="left:${left.toFixed(4)}%;width:${width.toFixed(4)}%;background:${fill}"></div>`;
}

/** 渲染时间轴本体喵。 */
function renderTimeline(body) {
  // 缩放倍数越高刻度越密，最小精确到秒喵
  const zoom = timelineZoom();
  // 宽度按缩放倍数撑开，外层滚动条负责左右看喵
  el.tlInner.style.width = `${zoom * 100}%`;
  el.tlZoomLabel.textContent = `${zoom}×`;
  // 放大后外层可拖动，给个抓手光标喵
  el.tlScroll.classList.toggle("zoomed", zoom > 1);
  // 刻度按可视范围画，缩放后分度值自动变细喵
  renderTimelineAxis(zoom);
  // 标题区间与当天的段一起存起来，指针悬浮时要用喵
  state.timelineTitles = body.title_spans || [];
  const segments = (body.segments || []).slice().sort((left, right) => new Date(left.start) - new Date(right.start));
  // 状态区间：离线（没心跳）与空档（在线但无使用记录），先算好再决定怎么画喵
  const nowRatio = timelineNowRatio(body);
  const stateBlocks = buildStateBlocks(body, nowRatio);
  if (!segments.length) {
    el.tlSummary.textContent = timelineSummaryText(body, 0);
    el.tlTrack.innerHTML = stateBlocks.length
      ? stateBlocks.join("")
      : '<p class="empty" style="margin:0">这一天没有使用记录</p>';
    el.tlLanes.innerHTML = "";
    el.tlLegend.innerHTML = stateLegendHtml();
    // 没有应用泳道，清掉这一屏的颜色表，悬浮提示不会带出上一次的色点喵
    state.timelineColors = new Map();
    // 应用设备清单同样清空，别拿上一屏的清单算深浅喵
    state.timelineAppDevices = new Map();
    // 喵~注意：空数据也是画完了，标记必须置上，否则这一天没记录时截图会白等到超时喵
    markShotReady("timeline");
    // 没有使用记录时也要把「现在」竖线摆好喵
    updateTimelineNowLine();
    return;
  }
  // 按应用汇总出泳道，顺便定好颜色喵
  // 喵~注意：应用轴要用 lane_segments——它是每台设备的完整记录，不按优先级裁剪。
  // 顶层色块用 segments（裁剪过）才能不叠色，两者分工不同喵
  const laneSegments = (body.lane_segments && body.lane_segments.length ? body.lane_segments : segments)
    .slice()
    .sort((left, right) => new Date(left.start) - new Date(right.start));
  const byApp = new Map();
  for (const segment of laneSegments) {
    if (!byApp.has(segment.app)) byApp.set(segment.app, { app: segment.app, seconds: 0, blocks: [], devices: [] });
    const entry = byApp.get(segment.app);
    entry.seconds += segment.seconds;
    entry.blocks.push(segment);
    // 聚合视图要标出这条泳道来自哪几台设备喵
    if (segment.device_name && !entry.devices.includes(segment.device_name)) {
      entry.devices.push(segment.device_name);
    }
  }
  const lanes = [...byApp.values()].sort((left, right) => right.seconds - left.seconds).slice(0, 12);
  // 撞色的应用会自动顺延，保证同屏颜色不重复喵
  const colors = buildColorMap(lanes.map((entry) => entry.app));
  // 每个应用对应的图标键，取色和悬浮提示都用同一个键喵
  const iconKeys = new Map();
  for (const entry of byApp.values()) iconKeys.set(entry.app, iconColorKey(entry.blocks[0]));
  // 优先用图标混合色，没图标或取色失败时退回原来的配色方案喵
  const baseColorOf = (app) => pickAppColor(iconColorCache.get(iconKeys.get(app)), colors.get(app) || appColor(app));
  // 同屏撞色按次序微调一次，顶层色块 / 泳道 / 图例 / 提示统一用这一份颜色喵
  const colorMap = dedupeLaneColors([...byApp.keys()], baseColorOf);
  const colorOf = (app) => colorMap.get(app) || baseColorOf(app);
  // 记下所有应用最终用的颜色（不只前 12 条泳道），悬浮提示才能和顶层色块对上喵
  state.timelineColors = new Map([...byApp.keys()].map((app) => [app, colorOf(app)]));
  // 每个应用各自出现在哪几台设备上，深浅只按这个清单算，不跟本屏设备总数走喵
  const appDevices = new Map([...byApp.values()].map((entry) => [entry.app, entry.devices]));
  // 存一份给指针悬浮用，浮层色点要和色块用同一份清单喵
  state.timelineAppDevices = appDevices;
  // 找出真在多台设备上出现过的应用，图例的「深浅=设备」只对它们有意义喵
  const multiDeviceApps = [...byApp.values()].filter((entry) => entry.devices.length > 1);
  // 每秒占多少像素：窗口越窄、倍率越小，块就越该合并喵
  const viewportPx = el.tlScroll.clientWidth || 900;
  const pxPerSecond = (viewportPx * zoom) / DAY_SECONDS;
  // 顶层色块：先画离线与空档，再画应用，应用色块压在上面喵
  const topBlocks = buildVisualBlocks(segments, pxPerSecond);
  // 存一份给指针悬浮用，判断「色块覆盖但那一刻没记录」喵
  state.timelineBlocks = topBlocks;
  const blocks = stateBlocks.slice();
  for (const block of topBlocks) {
    blocks.push(visualBlockHtml(block, colorOf(block.app), nowRatio, appDevices));
  }
  el.tlTrack.innerHTML = blocks.join("");
  el.tlLanes.innerHTML = lanes
    .map((entry) => {
      const laneBlocks = buildVisualBlocks(entry.blocks, pxPerSecond)
        .map((block) => visualBlockHtml(block, colorOf(entry.app), nowRatio, appDevices))
        .join("");
      return `<div class="tl-lane">
        <div class="tl-lane-head">
          <span class="tl-lane-name">${appIconHtml(entry.blocks[0], colorOf(entry.app))}<span>${escapeHtml(entry.app)}</span>${laneDeviceSuffix(entry.devices, state.timelineMerged)}</span>
          <span class="tl-lane-total">${formatDuration(entry.seconds)}</span>
        </div>
        <div class="tl-lane-track">${laneBlocks}</div>
      </div>`;
    })
    .join("");
  // 只有确实存在多设备应用时才补设备深浅的说明，否则这一行没有意义喵
  // 喵~注意：同屏可能有多个跨设备应用，全部逐个列出，每个都带应用名避免混淆喵
  const deviceLegend = state.timelineMerged && multiDeviceApps.length
    ? multiDeviceApps
        .map((entry) => {
          // 这个应用的色点按它自己的设备清单取深浅，和它泳道里的色块完全一致喵
          const chips = entry.devices
            .map(
              (name, index) =>
                `<i class="tl-legend-chip" style="background:${deviceShade(colorOf(entry.app), index, entry.devices.length)}"></i>${escapeHtml(name)}`,
            )
            .join(" · ");
          // 多个应用时带上应用名，只有一个时省掉，图例更短喵
          const label = multiDeviceApps.length > 1 ? `${escapeHtml(entry.app)}：` : "";
          return `<span class="tl-legend-device">${label}${chips}</span>`;
        })
        .join("")
    : "";
  // 图例只放前 6 个，避免一行太长喵；后面再补设备深浅与状态说明喵
  el.tlLegend.innerHTML =
    lanes
      .slice(0, 6)
      .map((entry) => `<span><i style="background:${colorOf(entry.app)}"></i>${escapeHtml(entry.app)}</span>`)
      .join("") + deviceLegend + stateLegendHtml();
  // 所有带图标的应用都开始取色，顶层色块 / 泳道 / 图例 / 提示共用同一份颜色喵
  ensureIconColors([...byApp.values()]);
  // 汇总行喵
  el.tlSummary.textContent = timelineSummaryText(body, segments.length);
  // 今天的话画一条「现在」竖线喵
  updateTimelineNowLine();
  // 喵~注意：图标取色是异步的，取回来会再重画一次时间轴。这里先置上就绪标记，
  // 让截图不必干等取色；后端拿到标记后还会再等一小会儿（SHOT_READY_SETTLE），
  // 那点时间足够二次重绘落定喵
  markShotReady("timeline");
  // 截图时要定位到某个时刻，等宽度按缩放撑开之后再滚，否则算出来的是旧宽度喵
  applyPendingShotFocus();
}

/** 按天数偏移切换日期喵。 */
/** 取当前缩放倍数，越界时夹到 1–1440 倍喵。 */
function timelineZoom() {
  const value = Number(state.timelineZoom || 1);
  // 喵~防御：非法值一律当 1 倍，避免宽度算出 NaN 喵
  if (!Number.isFinite(value)) return 1;
  return Math.min(TIMELINE_MAX_ZOOM, Math.max(1, Math.round(value)));
}

/** 调整时间轴缩放倍数并重画喵。 */
/** 以某个横坐标为锚点缩放时间轴，保证指针下的时刻不动喵。 */
function zoomTimelineAt(factor, clientX) {
  const track = el.tlTrack;
  const scroll = el.tlScroll;
  const before = timelineZoom();
  const next = Math.min(TIMELINE_MAX_ZOOM, Math.max(1, Math.round(before * factor)));
  // 倍数没变就不动喵
  if (next === before) return;
  // 喵~防御：没有轨道就退化成普通缩放喵
  if (!track || !scroll) {
    setTimelineZoom(next);
    return;
  }
  // 记下锚点在轨道里的比例喵
  const rect = track.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
  state.timelineZoom = next;
  renderTimeline(state.timeline || {});
  // 重画后把锚点挪回原来的屏幕位置喵
  const after = el.tlTrack.getBoundingClientRect();
  scroll.scrollLeft += after.left + ratio * after.width - (rect.left + ratio * rect.width);
  updateTimelineNowLine();
}

/** 滚轮缩放：向上滚放大，向下滚缩小喵。 */
function handleTimelineWheel(event) {
  // 喵~防御：没有滚动量时不管喵
  if (!event.deltaY) return;
  // 交给时间轴自己处理，别让整页跟着滚喵
  event.preventDefault();
  // 滚轮一次翻一倍，从 1 倍一路放大到秒级也只要十几次喵
  zoomTimelineAt(event.deltaY < 0 ? 2 : 0.5, event.clientX);
}

/** 按住左键拖动时间轴左右平移喵。 */
function startTimelineDrag(event) {
  const scroll = el.tlScroll;
  // 喵~防御：只有内容比视口宽时才需要拖喵
  if (!scroll || scroll.scrollWidth <= scroll.clientWidth + 1) return;
  // 喵~防御：只认左键喵
  if (event.button !== 0) return;
  state.timelineDrag = { startX: event.clientX, startScroll: scroll.scrollLeft };
  el.tlInner.classList.add("dragging");
  // 拖动时收起指针浮层，避免跟手抖喵
  hideTimelinePointer();
}

/** 拖动过程中的平移喵。 */
function moveTimelineDrag(event) {
  const drag = state.timelineDrag;
  const scroll = el.tlScroll;
  // 喵~防御：没在拖就什么都不做喵
  if (!drag || !scroll) return;
  scroll.scrollLeft = drag.startScroll - (event.clientX - drag.startX);
}

/** 松开鼠标结束拖动喵。 */
function endTimelineDrag() {
  if (!state.timelineDrag) return;
  state.timelineDrag = null;
  el.tlInner.classList.remove("dragging");
}


function setTimelineZoom(next) {
  const clamped = Math.min(TIMELINE_MAX_ZOOM, Math.max(1, Math.round(next)));
  // 倍数没变就不用重画喵
  if (clamped === timelineZoom()) return;
  state.timelineZoom = clamped;
  // 尽量把视口中心留在原来的时刻上，缩放后不至于跳走喵
  const scroll = el.tlInner.parentElement;
  const before = scroll ? (scroll.scrollLeft + scroll.clientWidth / 2) / Math.max(1, scroll.scrollWidth) : 0.5;
  renderTimeline(state.timeline || {});
  if (scroll) {
    // 按新宽度把中心点挪回去喵
    scroll.scrollLeft = Math.max(0, before * scroll.scrollWidth - scroll.clientWidth / 2);
  }
  updateTimelineNowLine();
}

/** 把时刻格式化成 HH:MM:SS，给「现在」标签用喵。 */
function clockWithSeconds(moment) {
  const pad = (value) => String(value).padStart(2, "0");
  // 同样按服务端时区显示喵
  const shifted = inServerZone(moment);
  return `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`;
}

/** 「现在」竖线的动画句柄，0 表示还没启动喵。 */
let nowLineFrame = 0;

/** 让「现在」竖线随真实时间平滑右移，标签精确到秒喵。 */
function startTimelineNowTicker() {
  // 喵~防御：已经启动过就不要重复注册喵
  if (nowLineFrame) return;
  const step = () => {
    nowLineFrame = window.requestAnimationFrame(step);
    // 标签页在后台时不用白算喵
    if (document.hidden) return;
    updateTimelineNowLine();
  };
  nowLineFrame = window.requestAnimationFrame(step);
}

/** 把「当前时间」竖线摆到今天对应的位置喵。 */
function updateTimelineNowLine() {
  const body = state.timeline;
  // 喵~防御：没数据或不是今天就不画这条线喵
  if (!body || !body.date || !el.tlNow) {
    if (el.tlNow) el.tlNow.hidden = true;
    return;
  }
  const today = localDateText(serverNow());
  if (body.date !== today) {
    el.tlNow.hidden = true;
    return;
  }
  // 现在几点，连秒一起换算成百分比，这样线是一秒一秒挪的喵
  const now = serverNow();
  // 换算成服务端时区后再取时分秒，浏览器时区不参与喵
  const shifted = inServerZone(now);
  const second =
    shifted.getUTCHours() * 3600 +
    shifted.getUTCMinutes() * 60 +
    shifted.getUTCSeconds() +
    now.getMilliseconds() / 1000;
  el.tlNow.style.left = `${((second / DAY_SECONDS) * 100).toFixed(4)}%`;
  el.tlNow.title = `现在 ${clockWithSeconds(now)}`;
  // 顶部小标签直接写上时分秒，不用悬停也看得见喵
  el.tlNow.dataset.label = `现在 ${clockWithSeconds(now)}`;
  el.tlNow.hidden = false;
}

/** 找某个时刻的设备状态（afk / offline / online）喵。 */
function stateAt(moment) {
  const states = (state.timeline && state.timeline.states) || [];
  for (const item of states) {
    const from = new Date(item.start);
    const to = new Date(item.end);
    // 命中区间就返回状态类型喵
    if (moment >= from && moment < to) return item.kind;
  }
  return "";
}

/** 把状态类型翻成人话，用来解释「有颜色但没有使用记录」喵。 */
function stateLabel(kind) {
  // 喵~注意：主人要求前端只标 AFK，不再堆"在线但无使用记录"这类解释喵
  if (kind === "afk") return "AFK";
  if (kind === "offline") return "离线（无心跳）";
  return "无使用记录";
}

/** 找某个时刻某条泳道对应的窗口标题喵。 */
function titleAt(app, moment) {
  const spans = state.timelineTitles || [];
  // 同一应用里找覆盖这个时刻的区间，取不到就退回最近一段喵
  let fallback = "";
  for (const span of spans) {
    if (span.app !== app) continue;
    const start = new Date(span.start);
    const end = new Date(span.end);
    if (moment >= start && moment <= end) return span.title;
    // 记录这个时刻之前最近的一段，用来兜底喵
    if (end <= moment) fallback = span.title;
  }
  return fallback;
}

/** 指针悬浮时显示时刻、应用与那一刻的窗口标题喵。 */
function handleTimelinePointer(event) {
  const body = state.timeline;
  const track = el.tlTrack;
  // 喵~防御：没有数据或没有指针元素时什么都不做喵
  if (!body || !track || !el.tlPointer) return;
  // 喵~防御：正在拖动时不要跟手显示浮层喵
  if (state.timelineDrag) return;
  const rect = track.getBoundingClientRect();
  // 喵~防御：宽度为 0 时算不出比例，直接返回喵
  if (rect.width <= 0) return;
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  const minute = ratio * DAY_MINUTES;
  // 虚线轴线跟着指针走喵
  el.tlPointer.style.left = `${(ratio * 100).toFixed(3)}%`;
  el.tlPointer.hidden = false;
  // 换算成这一天的具体时刻喵
  const start = body.start ? new Date(body.start) : null;
  if (!start) return;
  const moment = new Date(start.getTime() + minute * 60000);
  // 找这个时刻正在用的应用喵
  const segment = (body.segments || []).find((item) => {
    const from = new Date(item.start);
    const to = new Date(item.end);
    return moment >= from && moment < to;
  });
  const clockText = formatClock(moment);
  const title = segment ? titleAt(segment.app, moment) : "";
  // 色块可能按比例尺合并过，落在空隙里时要说明是被合并显示的喵
  const covering = segment
    ? null
    : (state.timelineBlocks || []).find((item) => moment.getTime() >= item.startMs && moment.getTime() < item.endMs);
  // 喵~防御：这一刻没有使用记录时说明是空档、离线还是合并显示的间隙喵
  // 合并视图里同一条泳道混着多台设备，提示里必须说清是哪台喵
  const segmentDevice = segment && segment.device_name ? ` · ${segment.device_name}` : "";
  const coveringDevice = covering && covering.deviceKey ? ` · ${covering.deviceKey}` : "";
  // 第一行只放时刻 · 应用 · 设备，窗口标题单独换到第二行喵
  const firstLine = segment
    ? `${clockText} · ${segment.app}${segmentDevice}`
    : covering
      ? `${clockText} · ${covering.app}${coveringDevice} · 间隙（合并显示）`
      : `${clockText} · ${stateLabel(stateAt(moment))}`;
  // 只有命中了具体使用段才可能带窗口标题，没有标题就返回空串，不留空行喵
  const titleLine = segment && title ? String(title).trim() : "";
  // 悬浮提示前面带一个色点，颜色必须和指针下的色块完全一致喵
  const tipApp = segment ? segment.app : covering ? covering.app : "";
  // 指针落在哪台设备上，色点就要用那台设备的深浅色喵
  const tipDevice = segment ? segment.device_name || "" : covering ? covering.deviceKey || "" : "";
  // 色点改用「这个应用自己的设备清单」取深浅，单设备应用必然是原始图标色喵
  const tipColor = tipShadeColor(tipApp, tipDevice, state.timelineColors, state.timelineAppDevices);
  // 颜色块永远排最前面，标题换到第二行也不会挤掉它的位置喵
  const tipDot = tipColor ? `<i class="tl-tip-dot" style="background:${tipColor}"></i>` : "";
  // 标题非空时才追加块级 span，靠 CSS 的 display:block 换行，不留空行喵
  const titleHtml = titleLine ? `<span class="tl-tip-title">${escapeHtml(titleLine)}</span>` : "";
  // 颜色是我们自己算的 rgb() 或色板值，文本统一转义，拼 HTML 不会出问题喵
  el.tlTip.innerHTML = `${tipDot}<span>${escapeHtml(firstLine)}</span>${titleHtml}`;
  el.tlTip.hidden = false;
  // 浮层贴在指针上方，用视口坐标定位，滚动时也不会跑偏喵
  positionTimelineTip(event);
}

/** 把浮层贴到指针上方，滚动时也不会跑偏喵。 */
function positionTimelineTip(event) {
  // 取浮层尺寸，拿不到就给个默认高度喵
  const tipWidth = el.tlTip.offsetWidth || 0;
  const tipHeight = el.tlTip.offsetHeight || 24;
  // 水平方向不让浮层超出视口喵
  const left = Math.min(Math.max(8, event.clientX + 12), Math.max(8, window.innerWidth - tipWidth - 8));
  el.tlTip.style.left = `${left}px`;
  el.tlTip.style.top = `${Math.max(8, event.clientY - tipHeight - 12)}px`;
}

/** 泳道色块悬浮：复用同一个浮层，显示时间与设备喵。 */
function showLaneTip(event) {
  // 只认泳道里的色块喵
  const block = event.target.closest ? event.target.closest(".tl-block") : null;
  // 没停到色块上就收起浮层喵
  if (!block) {
    el.tlTip.hidden = true;
    return;
  }
  // 原生 title 已删掉，改写从 aria-label 取同一段文案喵
  const text = block.getAttribute("aria-label") || "";
  // 喵~防御：没有文案就不显示，免得出现空浮层喵
  if (!text) {
    el.tlTip.hidden = true;
    return;
  }
  // 色点用色块自己的背景色，和泳道完全一致喵
  el.tlTip.innerHTML = `<i class="tl-tip-dot" style="background:${block.style.background}"></i><span>${escapeHtml(text)}</span>`;
  el.tlTip.hidden = false;
  positionTimelineTip(event);
}

/** 指针离开时间轴时收起虚线与浮层喵。 */
function hideTimelinePointer() {
  if (el.tlPointer) el.tlPointer.hidden = true;
  if (el.tlTip) el.tlTip.hidden = true;
}

function shiftTimelineDate(days) {
  const base = el.tlDate.value ? new Date(`${el.tlDate.value}T00:00:00`) : new Date();
  base.setDate(base.getDate() + days);
  state.timelineDate = localDateText(base);
  el.tlDate.value = state.timelineDate;
  loadTimeline();
}

/* ==================== 应用排行 ==================== */

/** 聚合页面在应用名后面补上设备名，例如「Code.exe（本机 Windows）」；跨设备排行始终标注，哪怕只有一台设备用过喵。 */
function rankingDeviceSuffix(entry) {
  // 设备名列表由服务端算好，单设备也要标，免得看不出这个应用是哪台设备用的喵
  const names = Array.isArray(entry.devices) ? entry.devices.filter(Boolean) : [];
  // 喵~防御：拿不到设备名时保持原样，别显示空括号喵
  if (!names.length) return "";
  // 设备太多时只列前三台，剩下的用「等 N 台」收尾喵
  const shown = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? `${shown} 等 ${names.length} 台` : shown;
  return `<span class="rank-device">（${escapeHtml(suffix)}）</span>`;
}

/** 把同名应用的多条排行合并成一行，多台设备共用一条条形喵。 */
function mergeRankingEntries(entries) {
  // 合并键用应用名（去首尾空格、转小写），同一个软件在不同平台包名不同也能并起来喵
  const merged = new Map();
  for (const entry of Array.isArray(entries) ? entries : []) {
    // 喵~防御：没有应用名的脏条目直接跳过，别画出一行空白喵
    const name = String((entry && entry.app) || "").trim();
    if (!name) continue;
    // 小写名当键，大小写不同的同名应用也要合并喵
    const key = name.toLowerCase();
    // 第一次见到这个应用就建一行喵
    let row = merged.get(key);
    if (!row) {
      row = { app: name, seconds: 0, devices: [], packages: [], deviceSeconds: new Map(), icon_key: "" };
      merged.set(key, row);
    }
    // 喵~注意：图标键要跟着合并带走，否则排行榜永远只画彩色圆点、
    // 明明库里有图标也显示不出来（服务端每行都给了 icon_key）喵
    const iconKey = String((entry && entry.icon_key) || "").trim();
    if (iconKey && !row.icon_key) row.icon_key = iconKey;
    // 秒数累加，合并后的条形长度就是所有设备加起来的总时长喵
    const seconds = Math.max(0, Number(entry.seconds) || 0);
    row.seconds += seconds;
    // 包名去重保序，副标题按这个顺序把各平台的包名列出来喵
    for (const item of [entry.package, ...(Array.isArray(entry.packages) ? entry.packages : [])]) {
      const text = String(item || "").trim();
      if (text && !row.packages.includes(text)) row.packages.push(text);
    }
    // 设备名同样去重保序，标题里的「（A、B）」和条形左右顺序都用它喵
    for (const item of Array.isArray(entry.devices) ? entry.devices : []) {
      const text = String(item || "").trim();
      if (text && !row.devices.includes(text)) row.devices.push(text);
    }
    // 服务端给了按设备拆分的秒数就直接累加喵
    const breakdown = Array.isArray(entry.device_seconds) ? entry.device_seconds : [];
    for (const item of breakdown) {
      // 喵~防御：缺设备名的脏数据跳过，不然会画出一段没有归属的颜色喵
      const device = String((item && item.device) || "").trim();
      if (!device) continue;
      const value = Math.max(0, Number(item.seconds) || 0);
      row.deviceSeconds.set(device, (row.deviceSeconds.get(device) || 0) + value);
      if (!row.devices.includes(device)) row.devices.push(device);
    }
    // 老接口没有拆分时退化成「整条时长算给这条记录唯一的那台设备」喵
    if (!breakdown.length && Array.isArray(entry.devices) && entry.devices.length === 1) {
      const device = String(entry.devices[0] || "").trim();
      if (device) row.deviceSeconds.set(device, (row.deviceSeconds.get(device) || 0) + seconds);
    }
  }
  // 按总时长倒序、同长按应用名排，保证每次渲染顺序稳定喵
  return [...merged.values()]
    .filter((row) => row.seconds > 0)
    .sort((left, right) => right.seconds - left.seconds || left.app.localeCompare(right.app));
}

/** 画一行排行里的条形：多设备时按设备切成几段，每段一种深浅喵。
 *
 * 输入：合并后的行、本列表第一名秒数、应用取色函数。
 * 输出：单设备时一条纯色填充，多设备时按设备占比切段的 HTML。
 * 边界：设备秒数取不到时退回单色，绝不画空条喵。
 */
function rankBarHtml(row, maxSeconds, colorOf) {
  // 条形总宽度按本列表第一名归一化，最短留 2% 免得看不见喵
  const width = Math.max(2, Math.round((row.seconds / Math.max(1, maxSeconds)) * 100));
  // 按标题里的设备顺序取每段，保证「（A、B）」和「左到右」一一对应喵
  const ordered = row.devices
    .map((device) => [device, row.deviceSeconds.get(device) || 0])
    .filter((item) => item[1] > 0);
  // 只有一台设备就整条上色，和以前的样式完全一致喵
  if (ordered.length <= 1) {
    return `<div class="rank-bar"><span style="width:${width}%"></span></div>`;
  }
  // 多设备：每段按这台设备占本行总时长的比例分宽度喵
  const total = ordered.reduce((sum, item) => sum + item[1], 0) || 1;
  const base = colorOf(row.app);
  const segments = ordered
    .map(([device, seconds], index) => {
      // 这个应用自己的设备序位与台数，和时间轴「深浅=设备」完全同一套口径喵
      const color = deviceShade(base, index, ordered.length);
      // 悬停写清应用、设备、时长与占比，主人一眼看出这段是谁喵
      const title = `${row.app} · ${device} · ${formatDuration(seconds)}（${Math.round((seconds / total) * 100)}%）`;
      return `<span style="width:${(seconds / total) * 100}%;background:${color}" title="${escapeHtml(title)}"></span>`;
    })
    .join("");
  return `<div class="rank-bar"><span class="rank-bar-stack" style="width:${width}%">${segments}</span></div>`;
}

/** 渲染一份排行列表，总排行与分组排行共用同一套行样式喵。 */
function rankingListHtml(entries) {
  // 同名应用先合并，同一个软件在多台设备上只占一行喵
  const rows = mergeRankingEntries(entries);
  // 条形宽度按本列表第一名归一化，分组视图里各组也能撑满喵
  const maxSeconds = Math.max(1, rows.length ? rows[0].seconds : 1);
  return `<div class="rank-list">${rows
    .map((row, index) => {
      // 副标题把合并进来的包名都列出来，主人能看到这行合了哪些平台喵
      const packages = row.packages.length ? row.packages.join(" · ") : "未知包名";
      return `<div class="rank-row">
        <div class="rank-index${index < 3 ? " top" : ""}">${index + 1}</div>
        <div class="rank-name">
          <strong>${appIconHtml(row, appColor(row.app))}${escapeHtml(row.app)}${rankingDeviceSuffix(row)}</strong>
          <small>${escapeHtml(packages)} · ${row.devices.length || 1} 台设备</small>
        </div>
        ${rankBarHtml(row, maxSeconds, appColor)}
        <div class="rank-seconds">${formatDuration(row.seconds)}</div>
      </div>`;
    })
    .join("")}</div>`;
}

/** 渲染跨设备应用排行：总排行 / 按设备 / 按组喵。 */
function renderRankings() {
  const entries = state.rankings || [];
  // 只有选了按设备 / 按组才有分组数据，总排行走扁平列表喵
  const groups = state.rankingScope === "all" ? [] : state.rankingGroups || [];
  if (!entries.length && !groups.length) {
    el.rankingSummary.textContent = "";
    el.rankingBody.innerHTML = '<p class="empty">这个时间窗口内还没有使用数据</p>';
    // 喵~注意：空数据也是画完了，标记要置上，否则空窗口截图会白等到超时喵
    markShotReady("rankings");
    return;
  }
  // 同名应用先合并，摘要里的「N 个应用」才不会被同一软件的多台设备重复计数喵
  const mergedEntries = mergeRankingEntries(entries);
  const totalSeconds = mergedEntries.reduce((sum, row) => sum + row.seconds, 0);
  el.rankingSummary.textContent = groups.length
    ? `共 ${groups.length} 组 · 合计 ${formatDuration(totalSeconds)}`
    : `共 ${mergedEntries.length} 个应用 · 合计 ${formatDuration(totalSeconds)}`;
  // 没有分组数据时退回总排行，避免接口没跟上就白屏喵
  if (!groups.length) {
    el.rankingBody.innerHTML = rankingListHtml(entries);
    markShotReady("rankings");
    return;
  }
  el.rankingBody.innerHTML = groups
    .map(
      (group) => `<section class="rank-group">
        <div class="rank-group-head">
          <strong>${escapeHtml(group.label || group.key || "未命名分组")}</strong>
          <span class="muted">${group.entries.length} 个应用 · ${formatDuration(group.seconds)}</span>
        </div>
        ${rankingListHtml(group.entries)}
      </section>`,
    )
    .join("");
  // 排行行都插进 DOM 了，这一页就算画完喵
  markShotReady("rankings");
}

/* ==================== 统计 ==================== */

/** 热力图的五个色阶，由浅到深喵。
 *
 * 喵~注意：用绿色而不是主题蓝——主人要的是 GitHub 那种观感，
 * 蓝色深浅在白底上分档不明显，绿色四档一眼就能看出差别喵。
 */
const HEATMAP_LEVELS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"];

/** 把秒数换算成热力图的色阶下标喵。 */
function heatmapLevel(seconds, peak) {
  // 没有记录就是最浅的那格喵
  if (!seconds || seconds <= 0) return 0;
  // 喵~防御：峰值缺失时按「有数据就算一级」处理，避免除零喵
  if (!peak || peak <= 0) return 1;
  // 按相对峰值的比例分四档，和 GitHub 的观感接近喵
  const ratio = seconds / peak;
  if (ratio >= 0.75) return 4;
  if (ratio >= 0.5) return 3;
  if (ratio >= 0.25) return 2;
  return 1;
}

/** 把日期补成两位喵。 */
function pad2(value) {
  return String(value).padStart(2, "0");
}

/** 把 Date 转成本地 YYYY-MM-DD 文本喵。 */
function dateText(moment) {
  // 喵~注意：日期一律按服务端时区取，不能读浏览器本地字段——
  // 浏览器时区不是东八区时，热力图与折线图的日期轴会整体偏一天喵
  const shifted = inServerZone(moment);
  return `${shifted.getUTCFullYear()}-${pad2(shifted.getUTCMonth() + 1)}-${pad2(shifted.getUTCDate())}`;
}

/**
 * 造出热力图要画的所有格子（含未来留白）喵。
 *
 * 输入：天数。
 * 输出：从「起始周周日」到「本周周六」的 {date, text, blank} 数组。
 * 边界：起点对齐到周日、终点补到周六，保证 7 行网格整齐喵。
 */
function heatmapCells(days) {
  // 喵~注意：起点与终点都按服务端时区的「今天」推，不用浏览器本地日期喵
  const todayText = localDateText(serverNow());
  // 把「今天」换成服务端时区的零点，后续加减天数都在这个口径里喵
  const today = new Date(`${todayText}T00:00:00Z`);
  // 起点：往前推 days 天，再对齐到所在周的周日喵
  const start = new Date(today);
  start.setUTCDate(start.getUTCDate() - Math.max(1, Number(days) || 90) + 1);
  start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  // 终点：补到本周周六喵
  const end = new Date(today);
  end.setUTCDate(end.getUTCDate() + (6 - end.getUTCDay()));
  // 逐天铺格子喵
  const cells = [];
  const cursor = new Date(start);
  while (cursor <= end) {
    // 喵~注意：今天之后的格子留白，不然会画出一片「零使用」的假平地喵
    cells.push({
      // 这个时刻本身就是「服务端零点」的表示，取 UTC 字段即为该日喵
      date: `${cursor.getUTCFullYear()}-${pad2(cursor.getUTCMonth() + 1)}-${pad2(cursor.getUTCDate())}`,
      blank: cursor > today,
    });
    // 喵~注意：必须用 setUTCDate，用 setDate 会把浏览器时区混进来喵
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return cells;
}

/** 渲染热力图本体喵。 */
function renderHeatmap(payload) {
  // 没有容器时直接返回（截图以外的老页面可能没有这块）喵
  if (!el.heatmapBody) return;
  // 天数与今天的格子喵
  const cells = heatmapCells(state.statsDays);
  // 秒数索引，日期查不到就是 0 喵
  const secondsByDate = new Map();
  for (const item of (payload && payload.days) || []) {
    secondsByDate.set(String(item.date), Number(item.seconds) || 0);
  }
  // 峰值用来定色阶喵
  let peak = 0;
  for (const value of secondsByDate.values()) peak = Math.max(peak, value);
  // 格子矩阵，按周分列喵
  const cellHtml = cells
    .map((cell) => {
      // 未来日期画成透明占位喵
      if (cell.blank) return '<i class="heatmap-cell blank"></i>';
      const seconds = secondsByDate.get(cell.date) || 0;
      const level = heatmapLevel(seconds, peak);
      // 悬浮提示写清日期与时长，没记录就明说喵
      const tip = seconds > 0 ? `${cell.date} · ${formatDuration(seconds)}` : `${cell.date} · 没有记录`;
      return `<i class="heatmap-cell" style="background:${HEATMAP_LEVELS[level]}" title="${escapeHtml(tip)}"></i>`;
    })
    .join("");
  // 月份标签：在每月第一次出现的那一列上写月份喵
  const monthLabels = [];
  let lastMonth = -1;
  let weekIndex = 0;
  for (let index = 0; index < cells.length; index += 7) {
    // 取这一周第一天的月份喵
    const first = cells[index];
    if (first && !first.blank) {
      const month = Number(first.date.slice(5, 7));
      // 月份变了才打标签，避免挤在一起喵
      if (month !== lastMonth) {
        monthLabels.push(`<span class="heatmap-month" style="left:${weekIndex * 16}px">${month} 月</span>`);
        lastMonth = month;
      }
    }
    weekIndex += 1;
  }
  // 星期标签只写一、三、五，位置和 7 行网格对齐喵
  const weekdays = ["", "一", "", "三", "", "五", ""]
    .map((text) => `<span>${text}</span>`)
    .join("");
  // 拼成完整结构喵
  el.heatmapBody.innerHTML = `<div class="heatmap-grid">
    <div class="heatmap-weekdays">${weekdays}</div>
    <div class="heatmap-main">
      <div class="heatmap-months">${monthLabels.join("")}</div>
      <div class="heatmap-cells">${cellHtml}</div>
    </div>
  </div>`;
  // 图例：少 → 多喵
  if (el.heatmapLegend) {
    el.heatmapLegend.innerHTML = `<span>少</span>${HEATMAP_LEVELS.map(
      (color) => `<i class="heatmap-cell" style="background:${color}"></i>`,
    ).join("")}<span>多</span>`;
  }
}

/** 折线图要画的固定天数喵。 */
const TREND_DAYS = 30;

/**
 * 生成最近 N 天的完整日期序列（含没有记录的日子）喵。
 *
 * 输入：天数。
 * 输出：YYYY-MM-DD 文本数组，从最早到今天。
 * 边界：天数小于 1 时按 1 处理喵。
 *
 * 喵~注意：折线图必须把「零使用的日子」也画成 0，
 * 直接拿有数据的日期连起来会把空档抹平，看起来像连着一整段喵。
 */
function trendDates(days) {
  // 喵~注意：今天按服务端时区算，和热力图保持同一口径喵
  const todayText = localDateText(serverNow());
  const today = new Date(`${todayText}T00:00:00Z`);
  // 喵~防御：天数传 0、负数或非数字时按 1 天处理，
  // 这里不能用 `|| TREND_DAYS`——0 也是 falsy，会被悄悄放大成 30 天喵
  const requested = Number(days);
  const total = Number.isFinite(requested) && requested >= 1 ? Math.floor(requested) : 1;
  const dates = [];
  for (let offset = total - 1; offset >= 0; offset -= 1) {
    const day = new Date(today);
    // 同样用 UTC 运算，避免浏览器时区参与喵
    day.setUTCDate(day.getUTCDate() - offset);
    dates.push(
      `${day.getUTCFullYear()}-${pad2(day.getUTCMonth() + 1)}-${pad2(day.getUTCDate())}`,
    );
  }
  return dates;
}

/**
 * 把逐天秒数整理成折线图用的点喵。
 *
 * 输入：服务端的 days 列表、天数。
 * 输出：{date, seconds} 数组，长度恰好等于天数，缺的日子补 0。
 * 边界：没有数据时返回全 0 的点，图会画成一条贴底的线喵。
 */
function trendPoints(daysList, days) {
  // 秒数索引喵
  const secondsByDate = new Map();
  for (const item of Array.isArray(daysList) ? daysList : []) {
    const date = String((item && item.date) || "");
    if (!date) continue;
    secondsByDate.set(date, Math.max(0, Number(item.seconds) || 0));
  }
  // 按完整日期序列铺点，缺的补 0喵
  return trendDates(days).map((date) => ({ date, seconds: secondsByDate.get(date) || 0 }));
}

/** 把秒数说成「X 小时 Y 分」这种紧凑刻度文本喵。 */
function trendTickText(seconds) {
  // 满一小时就说小时，否则说分钟喵
  if (seconds >= 3600) {
    const hours = seconds / 3600;
    return Number.isInteger(hours) ? `${hours} 小时` : `${hours.toFixed(1)} 小时`;
  }
  return `${Math.round(seconds / 60)} 分`;
}

/**
 * 把折线点转成单调三次贝塞尔路径（平滑但不会冲过头）喵。
 *
 * 输入：点的数组 [{x, y}]，已按 x 升序。
 * 输出：SVG 路径字符串，形如 M... C... C...
 * 边界：点数小于 2 时返回空串；点数为 2 时退化成一条直线。
 *
 * 喵~注意：这里用的是「单调三次插值」（Fritsch–Carlson），不是普通平滑。
 * 普通 Catmull-Rom / 贝塞尔平滑会让曲线在数据拐点处冲过头——
 * 比如连续两天都是 0、第三天有值，曲线会在 0 那段下方画出负值，
 * 面积填充还会翻到基线以下，看着像「那天用了负的时间」喵。
 * 单调插值给每个控制点加了斜率限制，保证曲线始终落在相邻数据点之间，
 * 0 值那段就老老实实贴住基线喵。
 */
function monotoneCubicPath(nodeList) {
  // 点数不够画曲线喵
  if (!Array.isArray(nodeList) || nodeList.length < 2) return "";
  // 只有两个点时直接连线，斜率约束没有意义喵
  if (nodeList.length === 2) {
    const [first, second] = nodeList;
    return `M${first.x.toFixed(1)},${first.y.toFixed(1)} L${second.x.toFixed(1)},${second.y.toFixed(1)}`;
  }
  // 相邻段的横向差，横轴等距时都一样，但仍然按实际值算以防将来改成不等距喵
  const deltas = [];
  const slopes = [];
  for (let index = 0; index < nodeList.length - 1; index += 1) {
    const dx = nodeList[index + 1].x - nodeList[index].x;
    const dy = nodeList[index + 1].y - nodeList[index].y;
    // 喵~防御：横向差为 0 时无法算斜率，跳过这一段喵
    deltas.push(dx);
    slopes.push(dx === 0 ? 0 : dy / dx);
  }
  // 每个点上的切线斜率，起点和终点直接取相邻段的斜率喵
  const tangents = new Array(nodeList.length);
  tangents[0] = slopes[0];
  tangents[nodeList.length - 1] = slopes[slopes.length - 1];
  // 中间点用相邻两段斜率的加权平均喵
  for (let index = 1; index < nodeList.length - 1; index += 1) {
    const before = slopes[index - 1];
    const after = slopes[index];
    // 喵~注意：两段方向相反（一个上升一个下降）时把切线压成 0，
    // 这样极值点会变成真正的圆滑峰顶，而不是斜着冲过去喵
    if (before * after <= 0) {
      tangents[index] = 0;
    } else {
      // 加权调和平均，权重取两段的长度喵
      const dx1 = deltas[index - 1];
      const dx2 = deltas[index];
      const weight1 = 2 * dx2 + dx1;
      const weight2 = dx2 + 2 * dx1;
      tangents[index] = (weight1 + weight2) / (weight1 / before + weight2 / after);
    }
  }
  // 喵~防御：Fritsch–Carlson 限制，保证曲线不越过相邻点喵
  for (let index = 0; index < slopes.length; index += 1) {
    const slope = slopes[index];
    // 水平段要把两端切线都压平，否则曲线会鼓起来喵
    if (slope === 0) {
      tangents[index] = 0;
      tangents[index + 1] = 0;
      continue;
    }
    // 切线斜率与段斜率之比，超过 3 就会冲过头喵
    const a = tangents[index] / slope;
    const b = tangents[index + 1] / slope;
    // 平方和超过 9 时需要按比例缩小喵
    const magnitude = Math.hypot(a, b);
    if (magnitude > 3) {
      const scale = 3 / magnitude;
      tangents[index] = scale * a * slope;
      tangents[index + 1] = scale * b * slope;
    }
  }
  // 逐段拼三次贝塞尔曲线喵
  let path = `M${nodeList[0].x.toFixed(1)},${nodeList[0].y.toFixed(1)}`;
  for (let index = 0; index < nodeList.length - 1; index += 1) {
    const from = nodeList[index];
    const to = nodeList[index + 1];
    // 控制点取在三分之一与三分之二处，用切线斜率定高度喵
    const third = deltas[index] / 3;
    const control1x = from.x + third;
    const control1y = from.y + tangents[index] * third;
    const control2x = to.x - third;
    const control2y = to.y - tangents[index + 1] * third;
    path += ` C${control1x.toFixed(1)},${control1y.toFixed(1)} ${control2x.toFixed(1)},${control2y.toFixed(
      1,
    )} ${to.x.toFixed(1)},${to.y.toFixed(1)}`;
  }
  return path;
}

/** 渲染最近 30 天的每日使用时长折线图喵。 */
function renderTrend(payload) {
  // 没有容器时跳过喵
  if (!el.trendBody) return;
  // 整理成完整的 30 天点喵
  const points = trendPoints(payload && payload.days, TREND_DAYS);
  // 喵~防御：一条记录都没有时给空态，别画一条贴底的假线喵
  const totalSeconds = points.reduce((sum, point) => sum + point.seconds, 0);
  if (!totalSeconds) {
    el.trendBody.innerHTML = '<p class="empty">最近 30 天还没有使用记录</p>';
    if (el.trendSummary) el.trendSummary.textContent = "";
    return;
  }
  // 画布尺寸：宽固定，高固定，靠 viewBox 缩放喵
  const width = 720;
  const height = 220;
  // 四周留白，左边留给刻度、下边留给日期喵
  const padLeft = 56;
  const padRight = 12;
  const padTop = 12;
  const padBottom = 26;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  // 纵轴上限取「最忙那天」向上取整到整小时，图顶不会顶到边框喵
  const peak = Math.max(...points.map((point) => point.seconds));
  const niceMax = Math.max(3600, Math.ceil(peak / 3600) * 3600);
  // 横轴：每天一个位置喵
  const stepX = plotWidth / Math.max(1, points.length - 1);
  const pointX = (index) => padLeft + index * stepX;
  const pointY = (seconds) => padTop + plotHeight - (seconds / niceMax) * plotHeight;
  // 折线路径：平滑曲线，但保证不越过相邻数据点喵
  const linePath = monotoneCubicPath(
    points.map((point, index) => ({ x: pointX(index), y: pointY(point.seconds) })),
  );
  // 面积路径：曲线下方一直填到基线喵
  const baseline = (padTop + plotHeight).toFixed(1);
  const areaPath = `${linePath} L${pointX(points.length - 1).toFixed(1)},${baseline} L${pointX(0).toFixed(
    1,
  )},${baseline} Z`;
  // 纵向刻度：0、1/2、满额三档就够读喵
  const gridLines = [0, 0.5, 1]
    .map((ratio) => {
      const y = padTop + plotHeight - ratio * plotHeight;
      const label = trendTickText(niceMax * ratio);
      return `<line class="trend-grid-line" x1="${padLeft}" y1="${y.toFixed(1)}" x2="${width - padRight}" y2="${y.toFixed(1)}"/>
        <text class="trend-axis-text" x="${padLeft - 8}" y="${(y + 3).toFixed(1)}" text-anchor="end">${label}</text>`;
    })
    .join("");
  // 横轴日期：只标首、中、尾三个，标多了会糊成一团喵
  const dateTicks = [0, Math.floor((points.length - 1) / 2), points.length - 1]
    .filter((index, position, list) => list.indexOf(index) === position)
    .map((index) => {
      // 只写「月-日」，年份在标题里已经有了喵
      const text = points[index].date.slice(5);
      return `<text class="trend-axis-text" x="${pointX(index).toFixed(1)}" y="${height - 8}" text-anchor="middle">${text}</text>`;
    })
    .join("");
  // 数据点与悬浮热区喵
  const dots = points
    .map((point, index) => {
      const x = pointX(index);
      const y = pointY(point.seconds);
      const tip = `${point.date} · ${formatDuration(point.seconds)}`;
      // 喵~注意：0 值不画圆点——连续 28 天都为 0 时圆点会在基线上挤成一条虚线，
      // 看着像「有数据」的噪点，其实那天什么都没用喵
      const dot = point.seconds > 0
        ? `<circle class="trend-dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5"/>`
        : "";
      // 热区是整列，鼠标停在任意高度都能看到对应的那天的数值喵
      return `${dot}
        <rect class="trend-hit" x="${(x - stepX / 2).toFixed(1)}" y="${padTop}" width="${stepX.toFixed(
        1,
      )}" height="${plotHeight}"><title>${escapeHtml(tip)}</title></rect>`;
    })
    .join("");
  // 拼成完整 SVG喵
  el.trendBody.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="最近 30 天每日使用时长">
    ${gridLines}
    <path class="trend-area" d="${areaPath}"/>
    <path class="trend-line" d="${linePath}"/>
    ${dots}
    ${dateTicks}
  </svg>`;
  // 摘要写清这段时间的总量与峰值喵
  if (el.trendSummary) {
    el.trendSummary.textContent = `合计 ${formatDuration(totalSeconds)} · 单日最高 ${formatDuration(peak)}`;
  }
}

/** 渲染统计页顶部的四个数字喵。 */
function renderStatsKpi(payload) {
  // 没有容器时跳过喵
  if (!el.statsKpi) return;
  const totals = (payload && payload.totals) || {};
  // 四项指标：总时长、有记录天数、日均、最忙的一天喵
  const cards = [
    { label: "累计使用", value: formatDuration(totals.seconds || 0), cls: "accent" },
    { label: "有记录天数", value: `${totals.active_days || 0} 天` },
    { label: "日均使用", value: formatDuration(totals.average_seconds || 0) },
    {
      label: "最忙的一天",
      value: totals.busiest_date ? formatDuration(totals.busiest_seconds || 0) : "—",
      hint: totals.busiest_date || "",
    },
  ];
  // 逐张卡片拼出来喵
  el.statsKpi.innerHTML = cards
    .map(
      (card) => `<div class="kpi">
        <div class="kpi-label">${escapeHtml(card.label)}</div>
        <div class="kpi-value${card.cls ? ` ${card.cls}` : ""}">${escapeHtml(String(card.value))}</div>
        ${card.hint ? `<div class="kpi-hint">${escapeHtml(card.hint)}</div>` : ""}
      </div>`,
    )
    .join("");
}

/** 渲染统计页的设备分布喵。 */
function renderStatsDevices(payload) {
  // 没有容器时跳过喵
  if (!el.statsDevices) return;
  const devices = (payload && payload.devices) || [];
  // 喵~防御：一台设备都没有时给一句空态喵
  if (!devices.length) {
    el.statsDevices.innerHTML = '<p class="empty">这个时间窗口内还没有设备数据</p>';
    return;
  }
  // 条形按第一名归一化喵
  const maxSeconds = Math.max(1, Number(devices[0].seconds) || 1);
  // 逐台设备一行喵
  el.statsDevices.innerHTML = devices
    .map((device) => {
      const seconds = Number(device.seconds) || 0;
      const width = Math.max(2, (seconds / maxSeconds) * 100);
      return `<div class="stats-device-row">
        <div class="stats-device-name">${escapeHtml(String(device.name || device.device_id || ""))}</div>
        <div class="stats-device-bar"><span style="width:${width.toFixed(1)}%"></span></div>
        <div class="stats-device-seconds">${formatDuration(seconds)}</div>
      </div>`;
    })
    .join("");
}

/** 渲染整页统计喵。 */
function renderStats() {
  // 数据还没回来时给个占位喵
  const payload = state.stats;
  renderStatsKpi(payload);
  renderHeatmap(payload);
  renderTrend(payload);
  renderStatsDevices(payload);
  // 摘要写清当前口径喵
  if (el.statsSummary) {
    const current = state.statsDeviceId ? "当前设备" : "全部设备";
    el.statsSummary.textContent = `${current} · 近 ${state.statsDays} 天`;
  }
  // 设备筛选按钮跟着数据重建喵
  renderStatsDeviceSwitch(payload);
  // 统计页也画完了，允许截图喵
  markShotReady("stats");
}

/** 重建统计页的设备筛选按钮喵。 */
function renderStatsDeviceSwitch(payload) {
  // 没有容器时跳过喵
  if (!el.statsDeviceSwitch) return;
  // 喵~注意：按钮清单要用「全量设备」，不能用当前筛选后的明细，
  // 否则选中一台之后按钮只剩那一台，再也换不回去了喵
  const devices = state.statsDeviceList || (payload && payload.devices) || [];
  const items = [{ id: "", label: "全部设备" }].concat(
    devices.map((device) => ({ id: String(device.device_id || ""), label: String(device.name || "") })),
  );
  // 逐项渲染，选中态跟着 state 走喵
  el.statsDeviceSwitch.innerHTML = items
    .map(
      (item) =>
        `<button class="seg-item${item.id === state.statsDeviceId ? " active" : ""}" data-device="${escapeHtml(
          item.id,
        )}" type="button">${escapeHtml(item.label)}</button>`,
    )
    .join("");
}

/** 拉取热力图数据并渲染喵。 */
async function loadStats() {
  try {
    // 设备筛选走服务端，热力图与汇总都只算那一台喵
    let query = `days=${state.statsDays}&tz_offset_minutes=${state.tzOffsetMinutes}`;
    if (state.statsDeviceId) query += `&devices=${encodeURIComponent(state.statsDeviceId)}`;
    const body = await api(`/api/v1/stats/heatmap?${query}`);
    // 喵~注意：筛了设备时服务端只返回那一台的明细，
    // 但切换按钮需要完整清单，所以记下上一次的全量清单复用喵
    if (!state.statsDeviceId) state.statsDeviceList = body.devices || [];
    state.stats = body;
    renderStats();
  } catch (error) {
    // 喵~防御：口令失效走统一处理喵
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    // 出错时给一句可读提示喵
    if (el.heatmapBody) {
      el.heatmapBody.innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
    }
    // 喵~注意：失败也要置就绪标记，否则截图会一直等到超时喵
    markShotReady("stats");
  }
}

/* ==================== 命令测试 ==================== */

/** 读取机器人连接状态，给命令测试页加个提示喵。 */
async function loadBotStatus() {
  try {
    const body = await api("/api/v1/bot/status");
    renderBotStatus(body);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.botConn.className = "conn-note error";
    el.botConn.textContent = `读取机器人状态失败：${error.message}`;
  }
}

/** 渲染机器人状态提示喵。 */
function renderBotStatus(status) {
  const channels = Array.isArray(status.channels) ? status.channels : [];
  const isEnabled = (name) => channels.some((item) => item.name === name);
  const isConnected = (name) => channels.some((item) => item.name === name && item.connected);
  const qqbot = status.qqbot || {};
  const lines = [];
  // NapCat 段喵
  if (isEnabled("napcat")) {
    lines.push(isConnected("napcat") ? "NapCat 已连接" : `NapCat 未连接（${status.ws_url || "未知地址"}）`);
  }
  // 官方通道段喵
  if (qqbot.enabled) {
    lines.push(isConnected("qqbot") ? `官方 QQ Bot 已就绪（${qqbot.app_id || "未填 AppID"}）` : "官方 QQ Bot 连接中");
  }
  // 两个通道都关着时直接说明原因喵
  if (!lines.length) {
    el.botConn.className = "conn-note warn";
    el.botConn.textContent = "两个机器人通道都没启用（napcat.enabled 与 qqbot.enabled 都是 false），QQ 群里的命令不会响应；下面的测试照常可用。";
    return;
  }
  const napcatGroups = (status.whitelist_groups || []).map(String).join("、");
  const qqbotGroups = (qqbot.whitelist_group_openids || []).join("、");
  // 白名单为空是最常见的「没反应」原因，单独点名喵
  const missing = [];
  if (isEnabled("napcat") && !napcatGroups) missing.push("acl.whitelist_groups");
  if (qqbot.enabled && !qqbotGroups) missing.push("acl.whitelist_group_openids");
  if (missing.length) {
    el.botConn.className = "conn-note warn";
    el.botConn.textContent = `${lines.join("；")}，并且 ${missing.join(" 与 ")} 为空，对应通道不会响应任何群。`;
    return;
  }
  const detail = [];
  if (napcatGroups) detail.push(`NapCat 白名单群：${napcatGroups}`);
  if (qqbotGroups) detail.push(`官方白名单群：${qqbotGroups}`);
  el.botConn.className = "conn-note ok";
  el.botConn.textContent = `${lines.join("；")}，${detail.join("；")}`;
}

/** 生成常用命令的快捷按钮喵。 */
function renderBotChips() {
  const chips = [
    { text: "/happy帮助" },
    { text: "/happy在干嘛" },
    { text: "/happy干了什么" },
    { text: "/happy设备" },
    { text: "/看看happy 全部 排行榜" },
    { text: "/foobar" },
  ];
  el.botChips.innerHTML = chips
    .map((chip) => `<button class="chip" type="button" data-text="${escapeHtml(chip.text)}">${escapeHtml(chip.text)}</button>`)
    .join("");
}

/** 发送一条测试命令喵。 */
async function sendBotCommand() {
  const text = el.botInput.value.trim();
  // 喵~防御：空命令不发请求，省得白跑一趟喵
  if (!text) {
    showToast("先输入一条命令", "error");
    return;
  }
  const payload = { text };
  // 选中的通道决定群标识是整数还是 openid 字符串喵
  const channel = el.botChannel ? el.botChannel.value : "napcat";
  payload.channel = channel;
  // 填了群标识才做白名单模拟喵
  const groupText = el.botGroup.value.trim();
  const userText = el.botUser.value.trim();
  if (groupText) {
    // NapCat 只认整数群号，填错就别发请求了喵
    if (channel === "napcat" && !/^\d+$/.test(groupText)) {
      showToast("NapCat 通道的群号必须是整数", "error");
      return;
    }
    payload.group_id = channel === "qqbot" ? groupText : Number(groupText);
  }
  if (userText) payload.user_id = channel === "qqbot" ? userText : Number(userText);
  // 官方免 @ 群可以取消勾选，看消息会不会被忽略喵
  if (el.botMention) payload.mention = el.botMention.checked;
  el.botSend.disabled = true;
  el.botStatus.className = "bot-status muted";
  el.botStatus.textContent = "发送中…";
  try {
    const body = await api("/api/v1/bot/command", { method: "POST", body: JSON.stringify(payload) });
    renderBotResult(body);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.botStatus.className = "bot-status error";
    el.botStatus.textContent = `请求失败：${error.message}`;
  } finally {
    el.botSend.disabled = false;
  }
}

/** 展示一次命令测试的结果喵。 */
function renderBotResult(body) {
  const replied = Boolean(body.replied);
  const commandName = body.command_name ? `命中命令：${body.command_name}` : "没有解析出命令";
  el.botStatus.className = `bot-status ${replied ? "ok" : "warn"}`;
  // 通道名放在最前面，免得两个通道的测试结果看串喵
  const channelName = body.channel === "qqbot" ? "官方" : "NapCat";
  el.botStatus.textContent = `[${channelName}] ${replied ? "会回复" : "不会回复"} · ${body.reason_text || body.reason} · ${commandName} · ${body.elapsed_ms} ms`;
  el.botReply.textContent = replied
    ? body.text || (body.image_data_uri ? "（本次回复只有图片，见下方预览）" : "（空回复）")
    : `（机器人不会回复：${body.reason_text || body.reason}）`;
  // 图片命令直接把 PNG 塞进页面喵
  el.botImage.innerHTML = body.image_data_uri
    ? `<img src="${body.image_data_uri}" alt="使用排行图片">`
    : "";
}

/* ==================== 设置 ==================== */

/** 把当前状态同步到设置面板喵。 */
function renderSettings() {
  el.settingsToken.value = state.token;
  el.autoRefresh.checked = state.autoRefresh;
}

/* ==================== 配置（写回 config.yaml） ==================== */

// 配置段的显示顺序与中文标题喵
const CONFIG_SECTIONS = [
  ["bot", "happy 命令"],
  ["napcat", "NapCat（OneBot 11）"],
  ["qqbot", "官方 QQ Bot"],
  ["acl", "访问控制"],
];

/** 拉取可编辑的配置项并渲染表单喵。 */
async function loadConfig() {
  if (!el.configFields) return;
  // 喵~注意：先记下用户还没保存的输入，重绘之后原样还回去，别让刷新把填的内容冲掉喵
  const typed = snapshotConfigInputs();
  const baseline = { ...state.configOriginal };
  el.configPath.textContent = "加载中…";
  if (!state.configFields.length) el.configFields.innerHTML = '<p class="empty">加载中…</p>';
  try {
    const body = await api("/api/v1/settings");
    el.configPath.textContent = `配置文件：${body.config_path}`;
    state.configFields = body.fields || [];
    renderConfigFields();
    // 重绘完成后恢复未保存的编辑喵
    restoreConfigInputs(typed, baseline);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.configPath.textContent = "";
    el.configFields.innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
  }
}

/** 把表单当前的输入抓成快照，供重绘后恢复喵。 */
function snapshotConfigInputs() {
  const snapshot = {};
  if (!el.configFields) return snapshot;
  el.configFields.querySelectorAll("[data-name]").forEach((node) => {
    // 布尔存勾选状态，其它存文本喵
    snapshot[node.dataset.name] = node.dataset.kind === "bool" ? node.checked : node.value;
  });
  return snapshot;
}

/** 把用户改过但还没保存的输入恢复回表单喵。 */
function restoreConfigInputs(snapshot, baseline) {
  if (!el.configFields) return;
  el.configFields.querySelectorAll("[data-name]").forEach((node) => {
    const name = node.dataset.name;
    // 喵~防御：新出现的字段没有快照，保持服务端值喵
    if (!(name in snapshot)) return;
    // 喵~注意：密钥框永远显示服务端占位符，避免把刚保存的明文又塞回页面喵
    if (node.dataset.kind === "secret") return;
    const typed = snapshot[name];
    const before = baseline[name];
    // 布尔比较勾选状态喵
    if (node.dataset.kind === "bool") {
      const was = before === "true" || before === true;
      if (typed !== was) node.checked = typed;
      return;
    }
    // 只恢复「和旧值不同」的项，也就是用户真的改过的那部分喵
    if (typed !== (before ?? "")) node.value = typed;
  });
}

/** 按段把配置项渲染成表单控件喵。 */
function renderConfigFields() {
  // 记下初始值，保存时只提交改动过的项喵
  state.configOriginal = {};
  for (const field of state.configFields) {
    state.configOriginal[field.name] = Array.isArray(field.value) ? field.value.join("\n") : field.value;
  }
  const html = CONFIG_SECTIONS.map(([section, title]) => {
    const items = state.configFields.filter((field) => field.section === section);
    if (!items.length) return "";
    const rows = items.map((field) => configFieldHtml(field)).join("");
    return `<div class="config-section">
      <h3>${escapeHtml(title)}</h3>
      <div class="config-grid">${rows}</div>
    </div>`;
  }).join("");
  el.configFields.innerHTML = html || '<p class="empty">没有可编辑的配置项</p>';
}

/** 单个配置项的控件 HTML 喵。 */
function configFieldHtml(field) {
  const name = escapeHtml(field.name);
  const label = escapeHtml(field.label);
  const hint = field.hint ? `<span class="config-hint">${escapeHtml(field.hint)}</span>` : "";
  // 布尔用开关喵
  if (field.kind === "bool") {
    return `<label class="config-item config-switch">
      <input type="checkbox" data-name="${name}" data-kind="bool"${field.value ? " checked" : ""}>
      <span>${label}</span>
    </label>`;
  }
  // 列表用多行文本框，一行一项喵
  if (field.kind === "str_list" || field.kind === "int_list") {
    const text = (field.value || []).join("\n");
    return `<label class="config-item">
      <span class="config-label">${label}${hint}</span>
      <textarea data-name="${name}" data-kind="${field.kind}" rows="3" spellcheck="false">${escapeHtml(text)}</textarea>
    </label>`;
  }
  // 整数用 number，密钥用 password 喵
  const type = field.kind === "int" ? "number" : field.kind === "secret" ? "password" : "text";
  const placeholder = field.kind === "secret" ? "留空表示不修改" : "";
  return `<label class="config-item">
    <span class="config-label">${label}${hint}</span>
    <input type="${type}" data-name="${name}" data-kind="${field.kind}" value="${escapeHtml(String(field.value ?? ""))}" placeholder="${placeholder}" spellcheck="false" autocomplete="off">
  </label>`;
}

/** 收集表单里改动过的配置项喵。 */
function collectConfigChanges() {
  const changes = {};
  el.configFields.querySelectorAll("[data-name]").forEach((node) => {
    const name = node.dataset.name;
    const kind = node.dataset.kind;
    // 喵~防御：布尔取勾选状态，其它取文本喵
    if (kind === "bool") {
      const before = state.configOriginal[name] === "true" || state.configOriginal[name] === true;
      if (node.checked !== before) changes[name] = node.checked;
      return;
    }
    const value = node.value;
    if (value === state.configOriginal[name]) return;
    // 密钥占位符没动过就不用提交喵
    if (kind === "secret" && value === "********") return;
    changes[name] = kind === "str_list" || kind === "int_list" ? value.split(/\r?\n/) : value;
  });
  return changes;
}

/** 保存配置喵。 */
async function saveConfig() {
  if (!el.configSave) return;
  const changes = collectConfigChanges();
  if (!Object.keys(changes).length) {
    showToast("没有改动", "ok");
    return;
  }
  el.configSave.disabled = true;
  el.configStatus.textContent = "保存中…";
  try {
    const body = await api("/api/v1/settings", {
      method: "PATCH",
      body: JSON.stringify({ changes }),
    });
    const changed = body.changed || [];
    if (!changed.length) {
      showToast("没有改动", "ok");
      el.configStatus.textContent = "配置未变化";
    } else if (body.restart_required) {
      // 端口/数据库路径这类绑在进程上的项才需要重启喵
      const fields = (body.restart_fields || []).join("、") || "部分配置";
      showToast(`已保存 ${changed.length} 项，${fields} 需重启服务后生效`, "warn");
      el.configStatus.textContent = `已保存：${changed.join("、")}；${fields} 需重启服务后生效`;
    } else {
      showToast(`已保存 ${changed.length} 项，已热更新生效`, "ok");
      el.configStatus.textContent = `已保存并生效：${changed.join("、")}`;
    }
    await loadConfig();
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.configStatus.textContent = `保存失败：${error.message}`;
    showToast(`保存失败：${error.message}`, "error");
  } finally {
    el.configSave.disabled = false;
  }
}

/** 拉取黑名单并渲染喵。 */
async function loadBlocklist() {
  if (!el.blocklistList) return;
  try {
    const body = await api("/api/v1/acl/blocklist");
    renderBlocklist(body.entries || []);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.blocklistList.innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
  }
}

/** 把黑名单渲染成表格喵。 */
function renderBlocklist(entries) {
  if (!el.blocklistList) return;
  if (!entries.length) {
    el.blocklistList.innerHTML = '<p class="empty">还没有人进黑名单。</p>';
    return;
  }
  const rows = entries.map((entry) => {
    const fromConfig = entry.source === "config";
    // 喵~注意：配置里写死的条目在这里删不掉，按钮置灰并说明原因喵
    const action = fromConfig
      ? '<span class="muted">改 config.yaml</span>'
      : `<button class="btn ghost small" type="button" data-action="unblock"
           data-channel="${escapeHtml(entry.channel)}" data-target="${escapeHtml(entry.target)}">解除</button>`;
    const channelText = entry.channel === "qqbot" ? "官方通道" : "NapCat";
    const sourceTag = fromConfig
      ? '<span class="tag warn">配置</span>'
      : '<span class="tag ok">运行中</span>';
    // 喵~注意：拉黑时间同样要带日期，否则「昨天拉的」和「今天拉的」看起来一样喵
    const created = entry.created_at ? formatRecentTime(entry.created_at) : "—";
    return `<tr>
      <td>${escapeHtml(channelText)}</td>
      <td><code>${escapeHtml(entry.target)}</code></td>
      <td>${escapeHtml(entry.note || "—")}</td>
      <td>${sourceTag}</td>
      <td>${escapeHtml(created)}</td>
      <td>${action}</td>
    </tr>`;
  }).join("");
  el.blocklistList.innerHTML = `<table class="rules blocklist-table">
    <thead><tr><th>通道</th><th>标识</th><th>备注</th><th>来源</th><th>拉黑时间</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

/** 新增一条黑名单喵。 */
async function addBlocklistEntry() {
  if (!el.blocklistAdd) return;
  const target = (el.blocklistTarget.value || "").trim();
  if (!target) {
    showToast("标识不能为空", "warn");
    return;
  }
  el.blocklistAdd.disabled = true;
  el.blocklistStatus.textContent = "添加中…";
  try {
    const body = await api("/api/v1/acl/blocklist", {
      method: "POST",
      body: JSON.stringify({
        channel: el.blocklistChannel.value,
        target,
        note: (el.blocklistNote.value || "").trim(),
      }),
    });
    // 喵~注意：added 为 false 说明这人本来就在名单里，提示要说清楚喵
    if (body.added) {
      el.blocklistStatus.textContent = `已拉黑 ${target}，立刻生效`;
      showToast("已拉黑，立刻生效", "ok");
    } else {
      el.blocklistStatus.textContent = `${target} 已经在黑名单里了`;
      showToast("已经在名单里", "warn");
    }
    // 清空输入框方便连续拉黑喵
    el.blocklistTarget.value = "";
    el.blocklistNote.value = "";
    await loadBlocklist();
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.blocklistStatus.textContent = `添加失败：${error.message}`;
    showToast(`添加失败：${error.message}`, "error");
  } finally {
    el.blocklistAdd.disabled = false;
  }
}

/** 解除一条黑名单喵。 */
async function removeBlocklistEntry(channel, target) {
  el.blocklistStatus.textContent = "解除中…";
  try {
    const body = await api(
      `/api/v1/acl/blocklist/${encodeURIComponent(channel)}/${encodeURIComponent(target)}`,
      { method: "DELETE" }
    );
    if (body.removed) {
      el.blocklistStatus.textContent = `已解除 ${target}`;
      showToast("已解除，立刻生效", "ok");
    } else {
      el.blocklistStatus.textContent = `运行时名单里没有 ${target}（可能来自配置文件）`;
      showToast("没有可删的运行时条目", "warn");
    }
    await loadBlocklist();
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.blocklistStatus.textContent = `解除失败：${error.message}`;
    showToast(`解除失败：${error.message}`, "error");
  }
}

/** 拉取最近发言的人并渲染喵。 */
async function loadSeenUsers() {
  if (!el.seenUsersList) return;
  try {
    const body = await api("/api/v1/acl/seen-users");
    // 喵~注意：基准时刻在这里取一次，整张表的「今天」口径就统一了喵
    renderSeenUsers(body.users || [], serverNow());
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.seenUsersList.innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
  }
}

/**
 * 把一个「最近时刻」格式化成带跨天提示的文本喵。
 *
 * 输入：时间（ISO 文本或 Date）、可选的基准时刻（默认取服务端现在）。
 * 输出：今天「22:30」、昨天「昨天 22:30」、同年「10-30 22:30」、跨年「2025-12-31 22:30」。
 * 边界：空值或解析失败返回「—」；基准时刻可注入，测试才能把「今天」钉死喵。
 *
 * 喵~注意：这里必须带日期，不能只给时分。列表按最近活跃倒序排，
 * 跨过零点以后「昨天 23:50」和「今天 23:50」只写时分是一模一样的，
 * 而且昨天那条看起来像未来时间（比现在还晚），排在最上面最容易看错喵。
 */
function formatRecentTime(isoText, now) {
  // 喵~防御：没有时间就给占位符，别渲染出 Invalid Date喵
  if (!isoText) return "—";
  // Date 直接用，字符串先解析喵
  const moment = isoText instanceof Date ? isoText : new Date(isoText);
  // 喵~防御：解析失败说明字段格式不对，退回占位符喵
  if (Number.isNaN(moment.getTime())) return "—";
  // 基准时刻默认用服务端现在，测试可以传进来钉死喵
  const base = now instanceof Date ? now : serverNow();
  // 时分按服务端时区取，浏览器时区改了也不影响喵
  const shifted = inServerZone(moment);
  // 拼出 HH:mm喵
  const clock = `${pad2(shifted.getUTCHours())}:${pad2(shifted.getUTCMinutes())}`;
  // 这一条落在哪一天（服务端口径）喵
  const dayText = localDateText(moment);
  // 「今天」也按服务端口径算喵
  const todayText = localDateText(base);
  // 今天之内只写时分就够，不啰嗦喵
  if (dayText === todayText) return clock;
  // 喵~注意：服务端时区是固定偏移（东八区），减 24 小时就是昨天，不用管夏令时喵
  const yesterdayText = localDateText(new Date(base.getTime() - 86400000));
  // 昨天单独写成「昨天」，比写日期好认喵
  if (dayText === yesterdayText) return `昨天 ${clock}`;
  // 同一年里写「月-日 时分」喵
  const monthDay = dayText.slice(5);
  // 同年就不用重复写年份喵
  if (dayText.slice(0, 4) === todayText.slice(0, 4)) return `${monthDay} ${clock}`;
  // 跨年了才写完整日期，避免和今年的同月同日混淆喵
  return `${dayText} ${clock}`;
}

/** 把最近发言的人渲染成表格，每行带一键拉黑喵。 */
function renderSeenUsers(users, now) {
  if (!el.seenUsersList) return;
  if (!users.length) {
    el.seenUsersList.innerHTML =
      '<p class="empty">还没有人执行过命令。等群里有人 @ 机器人发一条命令就会出现。</p>';
    return;
  }
  const rows = users.map((user) => {
    const channelText = user.channel === "qqbot" ? "官方通道" : "NapCat";
    // 喵~注意：没有昵称时明确标出来，提醒主人只能靠 openid 前 8 位认人喵
    const nameCell = user.display_name
      ? escapeHtml(user.display_name)
      : `<span class="muted">无昵称</span> <code>${escapeHtml(user.label)}</code>`;
    return `<tr>
      <td>${escapeHtml(channelText)}</td>
      <td>${nameCell}</td>
      <td><code title="${escapeHtml(user.user_key)}">${escapeHtml(user.user_key)}</code></td>
      <td>${escapeHtml(user.command_count)}</td>
      <td>${escapeHtml(formatRecentTime(user.last_seen_at, now))}</td>
      <td><button class="btn ghost small" type="button" data-action="block-seen"
            data-channel="${escapeHtml(user.channel)}"
            data-target="${escapeHtml(user.user_key)}">拉黑</button></td>
    </tr>`;
  }).join("");
  el.seenUsersList.innerHTML = `<table class="rules seen-users-table">
    <thead><tr><th>通道</th><th>昵称</th><th>openid / QQ</th><th>命令数</th><th>最近活跃</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

/** 从最近发言列表里直接拉黑一个人喵。 */
async function blockSeenUser(channel, target) {
  try {
    const body = await api("/api/v1/acl/blocklist", {
      method: "POST",
      body: JSON.stringify({ channel, target }),
    });
    if (body.added) {
      showToast("已拉黑，立刻生效", "ok");
      if (el.blocklistStatus) el.blocklistStatus.textContent = `已拉黑 ${target}`;
    } else {
      showToast("已经在黑名单里", "warn");
    }
    // 两边都刷新，让状态保持同步喵
    await Promise.all([loadBlocklist(), loadSeenUsers()]);
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    showToast(`拉黑失败：${error.message}`, "error");
  }
}

/** 测试某个机器人通道能不能连上喵。 */
async function testBotChannel(channel) {
  if (!el.configStatus) return;
  el.configStatus.textContent = `正在测试 ${channel === "qqbot" ? "官方通道" : "NapCat"}…`;
  try {
    const body = await api("/api/v1/bot/test", {
      method: "POST",
      body: JSON.stringify({ channel }),
    });
    if (body.connected) {
      const detail = body.detail ? `（${body.detail}）` : "";
      el.configStatus.textContent = `连接正常，耗时 ${body.latency_ms} ms${detail}`;
      showToast("连接正常", "ok");
    } else {
      el.configStatus.textContent = `连接失败：${body.error || "未知原因"}`;
      showToast("连接失败", "error");
    }
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    el.configStatus.textContent = `测试失败：${error.message}`;
    showToast(`测试失败：${error.message}`, "error");
  }
}

/** 重启服务端并等它回来喵。 */
async function restartServer() {
  if (!el.configRestart) return;
  if (!window.confirm("确定重启服务端？重启期间看板会短暂断开。")) return;
  el.configRestart.disabled = true;
  el.configStatus.textContent = "正在重启…";
  try {
    await api("/api/v1/server/restart", { method: "POST", body: "{}" });
  } catch (error) {
    // 喵~注意：服务退出瞬间连接会被掐断，这里不当成失败喵
    if (error.unauthorized) {
      handleUnauthorized();
      el.configRestart.disabled = false;
      return;
    }
  }
  // 轮询健康检查，等到服务回来再刷新页面喵
  const deadline = Date.now() + 40000;
  let back = false;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    try {
      const response = await fetch("/healthz", { cache: "no-store" });
      if (response.ok) {
        back = true;
        break;
      }
    } catch (error) {
      // 还没起来，继续等喵
    }
  }
  el.configRestart.disabled = false;
  if (back) {
    el.configStatus.textContent = "服务已重启，正在刷新…";
    window.location.reload();
  } else {
    el.configStatus.textContent = "服务没有在 40 秒内回来，请到服务器上看日志";
    showToast("重启超时，请检查服务日志", "error");
  }
}

/* ==================== 标签页路由 ==================== */

/** 标记这一页的数据已经画完，供无头浏览器截图时等待喵。 */
function markShotReady(tab) {
  // 喵~注意：机器人截图会轮询这个属性，只有数据和配色都落定后才有意义喵
  document.body.dataset.shotReady = tab;
  // 带一个时间戳，后端读到标记后可以判断「是不是刚画的」喵
  document.body.dataset.shotReadyAt = String(Date.now());
}

/** 清掉就绪标记，截图内容即将变化时调用喵。 */
function clearShotReady() {
  // 喵~注意：换页签 / 换日期 / 换设备之后，旧标记代表的画面已经不成立了喵
  delete document.body.dataset.shotReady;
  delete document.body.dataset.shotReadyAt;
}

/** 执行挂起的截图定位请求，时间轴画完之后才有正确的宽度喵。 */
function applyPendingShotFocus() {
  // 没有挂起请求时什么也不做喵
  const pending = state.pendingShotFocus;
  if (!pending) return;
  // 喵~注意：先清掉再定位，避免二次重绘时又滚一次把位置弄乱喵
  state.pendingShotFocus = null;
  if (pending.mode === "window") {
    focusTimelineWindow(pending.from, pending.to);
  } else if (pending.mode === "at") {
    focusTimelineAt(pending.at);
  }
}

/** 切换标签页并按需加载数据喵。 */
function switchTab(tab) {
  state.tab = tab;
  // 喵~注意：换页签等于换画面，先把旧的就绪标记清掉，别让截图等到上一页的喵
  clearShotReady();
  // 顶部导航高亮喵
  el.nav.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.tab === tab);
  });
  // 面板显隐喵
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${tab}`);
  });
  // 按标签页渲染喵
  if (tab === "overview") renderOverview();
  if (tab === "devices") {
    renderDeviceTable();
    if (state.selectedId) selectDevice(state.selectedId);
  }
  if (tab === "rankings") loadRankings();
  if (tab === "stats") loadStats();
  if (tab === "timeline") loadTimeline();
  if (tab === "bot") {
    renderBotChips();
    loadBotStatus();
  }
  if (tab === "settings") {
    renderSettings();
    loadStorage();
  }
  if (tab === "config") {
    loadConfig();
    loadBlocklist();
    loadSeenUsers();
  }
  // 时间轴的增量刷新跟着标签页走喵
  syncTimelineTicker();
  updateHash();
}

/** 把当前标签页写进地址栏，刷新后能停在原地喵。 */
function updateHash() {  const suffix = state.tab === "devices" && state.selectedId ? `/${encodeURIComponent(state.selectedId)}` : "";
  const target = `#/${state.tab}${suffix}`;
  if (location.hash !== target) history.replaceState(null, "", target);
}

/** 解析地址栏里的标签页喵。 */
function readHash() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const [tab, deviceId] = raw.split("/");
  const allowed = ["overview", "devices", "timeline", "rankings", "stats", "bot", "config", "settings"];
  return {
    tab: allowed.includes(tab) ? tab : "overview",
    deviceId: deviceId ? decodeURIComponent(deviceId) : null,
  };
}

/**
 * 读取查询串里的截图参数喵。
 *
 * 为什么要有它：机器人发图时用无头浏览器截这张看板，需要能指定
 * 「哪个页签、多长时间窗口、哪些设备」，而这些在页面上是按钮和下拉框，
 * 只能靠 URL 传进来，否则截出来永远是默认的 24 小时与全部设备喵。
 */
function readShotParams() {
  const params = new URLSearchParams(location.search || "");
  // 只认这三种口径，写错一律总排行喵
  const scope = params.get("scope");
  // 排行窗口小时数，尽量夹到看板已有的档位喵
  const hoursText = params.get("hours");
  const hours = hoursText === null ? NaN : Number(hoursText);
  // 时间轴缩放倍数，没给或不合法时按 1 倍处理喵
  const zoomText = params.get("zoom");
  const zoomValue = zoomText === null ? NaN : Number(zoomText);
  return {
    // 时间轴用：起始与终止日期（YYYY-MM-DD）喵
    from: params.get("from") || "",
    to: params.get("to") || "",
    // 时间轴用：单台设备 ID 或 group:<序号>喵
    device: params.get("device") || "",
    // 排行榜用：窗口小时数与口径喵
    hours: Number.isFinite(hours) && hours > 0 ? Math.min(24 * 30, Math.round(hours)) : null,
    scope: ["all", "device", "group"].includes(scope) ? scope : "",
    // 排行榜用：逗号分隔的设备 ID，限定后图里只出现这些设备喵
    devices: (params.get("devices") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    // 时间轴用：缩放倍数，1 表示整天空看，越大越细喵
    zoom: Number.isFinite(zoomValue) && zoomValue > 0 ? Math.min(TIMELINE_MAX_ZOOM, Math.round(zoomValue)) : null,
    // 时间轴用：要定位到哪个时刻（HH:MM），配合 zoom 看某一段喵
    at: /^\d{1,2}:\d{2}$/.test(params.get("at") || "") ? params.get("at") : "",
    // 时间轴用：自定义窗口起止（HH:MM），给了就把这一段居中铺满喵
    from_time: /^\d{1,2}:\d{2}$/.test(params.get("from_time") || "") ? params.get("from_time") : "",
    to_time: /^\d{1,2}:\d{2}$/.test(params.get("to_time") || "") ? params.get("to_time") : "",
  };
}

/** 把截图参数套到当前状态上喵。 */
function applyShotParams() {
  const shot = readShotParams();
  // 排行榜窗口喵
  if (shot.hours) state.hours = shot.hours;
  // 排行榜口径喵
  if (shot.scope) state.rankingScope = shot.scope;
  // 排行榜设备范围：只认命令参数里指定的那几台喵
  if (shot.devices.length) state.rankingDevices = shot.devices;
  // 时间轴日期：给了 from 就用它喵
  if (shot.from) state.timelineDate = shot.from;
  // 时间轴设备选择喵
  if (shot.device) state.timelineDeviceId = shot.device;
  // 时间轴缩放倍数喵
  if (shot.zoom) state.timelineZoom = shot.zoom;
  return shot;
}

/** 截图时把时间轴滚到指定时刻，配合缩放看某一段喵。 */
function focusTimelineAt(atText) {
  // 喵~防御：没给时刻就保持默认位置喵
  if (!atText) return;
  const match = /^(\d{1,2}):(\d{2})$/.exec(atText);
  if (!match) return;
  // 换算成当天第几分钟喵
  const minutes = Number(match[1]) * 60 + Number(match[2]);
  // 喵~防御：超出 0-24 点的时刻没有意义喵
  if (!Number.isFinite(minutes) || minutes < 0 || minutes > 24 * 60) return;
  scrollTimelineToCenter(minutes / (24 * 60));
}

/** 把自定义时间窗口铺满视口并居中喵。 */
function focusTimelineWindow(fromText, toText) {
  // 解析两端时刻喵
  const parse = (text) => {
    const match = /^(\d{1,2}):(\d{2})$/.exec(text || "");
    if (!match) return null;
    return Number(match[1]) * 60 + Number(match[2]);
  };
  const startMinutes = parse(fromText);
  const endMinutes = parse(toText);
  // 喵~防御：两端都要合法且顺序正确喵
  if (startMinutes === null || endMinutes === null) return;
  if (!(endMinutes > startMinutes)) return;
  // 窗口中心落到视口正中喵
  scrollTimelineToCenter((startMinutes + endMinutes) / 2 / (24 * 60));
}

/** 按比例把某个位置滚到视口中间喵。 */
function scrollTimelineToCenter(ratio) {
  // 外层滚动容器的总宽度是按缩放倍数撑开的喵
  const scroll = el.tlInner.parentElement;
  if (!scroll) return;
  // 把这个位置摆到视口中间喵
  const target = ratio * scroll.scrollWidth - scroll.clientWidth / 2;
  scroll.scrollLeft = Math.max(0, target);
  // 缩放后重排可能把宽度又改一次，下一帧再校正一遍喵
  window.requestAnimationFrame(() => {
    const again = el.tlInner.parentElement;
    if (!again) return;
    again.scrollLeft = Math.max(0, ratio * again.scrollWidth - again.clientWidth / 2);
  });
}

/** 把参数对应的按钮高亮同步过去，免得图里显示的还是默认档位喵。 */
function syncShotButtons() {
  // 排行窗口按钮：按 data-hours 精确匹配喵
  if (el.rangeSwitch) {
    let matched = false;
    el.rangeSwitch.querySelectorAll(".seg-item").forEach((item) => {
      const same = Number(item.dataset.hours) === state.hours;
      item.classList.toggle("active", same);
      if (same) matched = true;
    });
    // 喵~注意：机器人支持任意窗口（例如 2 小时），看板只有三档按钮，
    // 匹配不到时补一个只读档位，否则图里高亮的会是错的档喵
    if (!matched) {
      const custom = document.createElement("button");
      custom.className = "seg-item active";
      custom.type = "button";
      custom.dataset.hours = String(state.hours);
      custom.textContent = `近 ${state.hours} 小时`;
      el.rangeSwitch.appendChild(custom);
    }
  }
  // 排行口径按钮喵
  if (el.rankScopeSwitch) {
    el.rankScopeSwitch.querySelectorAll(".seg-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.scope === state.rankingScope);
    });
  }
}

/* ==================== 数据加载 ==================== */

/** 拉取看板数据喵。 */
async function loadDashboard() {
  const body = await api("/api/v1/dashboard");
  state.devices = body.devices || [];
    setLive("ok", `已更新 ${formatClock(serverNow())}`);
}

/** 拉取跨设备应用排行喵。 */
async function loadRankings() {
  try {
    // 指定了设备范围时带上，图里就只出现这几台设备喵
    const deviceQuery = state.rankingDevices && state.rankingDevices.length
      ? `&devices=${encodeURIComponent(state.rankingDevices.join(","))}`
      : "";
    const body = await api(`/api/v1/rankings?hours=${state.hours}&limit=20&scope=${state.rankingScope}${deviceQuery}`);
    state.rankings = body.entries || [];
    // 分组数据可能没有（接口还没升级），渲染时会自动退回总排行喵
    state.rankingGroups = body.groups || [];
    renderRankings();
  } catch (error) {
    if (error.unauthorized) {
      // 喵~注意：口令失效的自检在截图脚本里有专门一条，这里照样置位免得白等喵
      markShotReady("rankings");
      handleUnauthorized();
      return;
    }
    el.rankingBody.innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
    // 喵~注意：加载失败也要置位，把错误画面截下来总比后端一直等到超时好喵
    markShotReady("rankings");
  }
}

/** 统一刷新入口喵。 */
async function refreshAll() {
  // 先校准服务端时间，后面所有"现在"都按它算喵
  if (state.token) await syncServerClock();
  if (!state.token) {
    openTokenModal();
    setLive("", "未连接");
    return;
  }
  if (state.loading) return;
  state.loading = true;
  try {
    await loadDashboard();
    await fetchPeople();
    if (state.tab === "overview") renderOverview();
    if (state.tab === "devices") {
      renderDeviceTable();
      if (state.selectedId) await selectDevice(state.selectedId);
    }
    if (state.tab === "rankings") await loadRankings();
    // 喵~注意：时间轴已经有数据时走静默刷新，避免整页刷新把色块清空再重画喵
    if (state.tab === "timeline") await loadTimeline({ silent: Boolean(state.timeline) });
    if (state.tab === "bot") {
      renderBotChips();
      await loadBotStatus();
    }
    if (state.tab === "settings") renderSettings();
  } catch (error) {
    if (error.unauthorized) {
      handleUnauthorized();
      return;
    }
    setLive("error", "加载失败");
    showToast(`加载失败：${error.message}`, "error");
  } finally {
    state.loading = false;
  }
}

/* ==================== 口令与弹窗 ==================== */

/** 打开口令弹窗喵。 */
function openTokenModal() {
  el.modalInput.value = state.token;
  el.modal.classList.remove("hidden");
  el.modalInput.focus();
}

/** 关闭口令弹窗喵。 */
function closeTokenModal() {
  el.modal.classList.add("hidden");
}

/** 保存口令并立即加载喵。 */
async function applyToken(rawToken) {
  const token = String(rawToken || "").trim();
  if (!token) {
    showToast("口令不能为空", "error");
    return;
  }
  state.token = token;
  localStorage.setItem(TOKEN_KEY, token);
  closeTokenModal();
  renderSettings();
  await refreshAll();
  showToast("口令已保存", "ok");
}

/** 口令失效时清掉本地口令并弹窗喵。 */
function handleUnauthorized() {
  state.token = "";
  localStorage.removeItem(TOKEN_KEY);
  // 喵~注意：口令失效后画面全换成「口令无效」，旧的就绪标记不再成立喵
  clearShotReady();
  state.devices = [];
  state.rankings = [];
  state.selectedId = null;
  state.detail = null;
  el.overviewGrid.innerHTML = '<p class="empty">口令无效，请重新填写</p>';
  el.deviceTable.innerHTML = '<p class="empty">口令无效，请重新填写</p>';
  el.deviceDetail.innerHTML = "";
  el.rankingBody.innerHTML = '<p class="empty">口令无效，请重新填写</p>';
  setLive("error", "口令无效");
  renderSettings();
  openTokenModal();
}

/* ==================== 自动刷新 ==================== */

/** 按开关状态启停定时刷新喵。 */
function syncAutoRefresh() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  if (state.autoRefresh) {
    state.timer = setInterval(refreshAll, REFRESH_MS);
  }
  // 时间轴有自己的增量刷新节奏喵
  syncTimelineTicker();
}

/* ==================== 时间轴增量刷新 ==================== */

/** 时间轴增量刷新间隔：比整页刷新快，且只在看板页可见时跑喵。 */
const TIMELINE_LIVE_MS = 15000;

/** 启停时间轴的增量刷新定时器喵。 */
function syncTimelineTicker() {
  if (state.timelineTimer) {
    clearInterval(state.timelineTimer);
    state.timelineTimer = null;
  }
  // 喵~防御：只在时间轴页、自动刷新开着时才轮询喵
  if (state.tab !== "timeline" || !state.autoRefresh || !state.token) return;
  state.timelineTimer = setInterval(() => {
    // 喵~防御：标签页在后台时不浪费请求喵
    if (document.hidden) return;
    if (state.tab !== "timeline") return;
    loadTimeline({ silent: true });
  }, TIMELINE_LIVE_MS);
}

/* ==================== 事件绑定 ==================== */

el.nav.addEventListener("click", (event) => {
  const button = event.target.closest(".nav-item");
  if (!button) return;
  switchTab(button.dataset.tab);
});

el.refresh.addEventListener("click", refreshAll);
el.tokenBtn.addEventListener("click", openTokenModal);
el.modalCancel.addEventListener("click", closeTokenModal);
el.modalSave.addEventListener("click", () => applyToken(el.modalInput.value));
el.modalInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") applyToken(el.modalInput.value);
  if (event.key === "Escape") closeTokenModal();
});
el.modal.addEventListener("click", (event) => {
  if (event.target === el.modal) closeTokenModal();
});

el.settingsSave.addEventListener("click", () => applyToken(el.settingsToken.value));
el.settingsClear.addEventListener("click", () => {
  state.token = "";
  localStorage.removeItem(TOKEN_KEY);
  renderSettings();
  setLive("", "未连接");
  showToast("口令已清除", "ok");
  openTokenModal();
});

// 配置页：保存、测试连接、重启喵
el.configSave.addEventListener("click", saveConfig);
el.configTestNapcat.addEventListener("click", () => testBotChannel("napcat"));
el.configTestQqbot.addEventListener("click", () => testBotChannel("qqbot"));
el.configRestart.addEventListener("click", restartServer);

// 黑名单：拉黑、解除喵
el.blocklistAdd.addEventListener("click", addBlocklistEntry);
// 喵~注意：解除按钮是动态渲染的，用事件委托挂在外层容器上喵
el.blocklistList.addEventListener("click", (event) => {
  const button = event.target.closest('[data-action="unblock"]');
  if (!button) return;
  removeBlocklistEntry(button.dataset.channel, button.dataset.target);
});
// 输入框里回车等于点「拉黑」喵
el.blocklistTarget.addEventListener("keydown", (event) => {
  if (event.key === "Enter") addBlocklistEntry();
});

// 最近发言列表里的一键拉黑，同样是动态渲染所以用委托喵
el.seenUsersList.addEventListener("click", (event) => {
  const button = event.target.closest('[data-action="block-seen"]');
  if (!button) return;
  blockSeenUser(button.dataset.channel, button.dataset.target);
});

el.autoRefresh.addEventListener("change", () => {
  state.autoRefresh = el.autoRefresh.checked;
  localStorage.setItem(AUTO_REFRESH_KEY, String(state.autoRefresh));
  syncAutoRefresh();
});

el.rankScopeSwitch.addEventListener("click", (event) => {
  const button = event.target.closest(".seg-item");
  if (!button) return;
  // 喵~防御：只认三种口径，写错的一律当总排行喵
  const scope = ["all", "device", "group"].includes(button.dataset.scope) ? button.dataset.scope : "all";
  state.rankingScope = scope;
  el.rankScopeSwitch.querySelectorAll(".seg-item").forEach((item) => {
    item.classList.toggle("active", item === button);
  });
  // 喵~注意：换口径等于换画面，先清掉就绪标记再重新加载喵
  clearShotReady();
  loadRankings();
});

el.tlLanes.addEventListener("pointermove", showLaneTip);
el.tlLanes.addEventListener("pointerleave", () => {
  // 离开泳道就把浮层收起来喵
  el.tlTip.hidden = true;
});

el.rangeSwitch.addEventListener("click", (event) => {
  const button = event.target.closest(".seg-item");
  if (!button) return;
  state.hours = Number(button.dataset.hours) || 24;
  el.rangeSwitch.querySelectorAll(".seg-item").forEach((item) => {
    item.classList.toggle("active", item === button);
  });
  // 喵~注意：换时间窗口等于换画面，先清掉就绪标记再重新加载喵
  clearShotReady();
  loadRankings();
});

el.tlPeople.addEventListener("click", openPeopleEditor);

// 统计页：切换回溯天数喵
if (el.statsRangeSwitch) {
  el.statsRangeSwitch.addEventListener("click", (event) => {
    const button = event.target.closest(".seg-item");
    if (!button) return;
    state.statsDays = Number(button.dataset.days) || 90;
    el.statsRangeSwitch.querySelectorAll(".seg-item").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    // 喵~注意：换窗口等于换画面，先清掉就绪标记再重新拉数据喵
    clearShotReady();
    loadStats();
  });
}

// 统计页：切换设备筛选喵
if (el.statsDeviceSwitch) {
  el.statsDeviceSwitch.addEventListener("click", (event) => {
    const button = event.target.closest(".seg-item");
    if (!button) return;
    state.statsDeviceId = button.dataset.device || "";
    el.statsDeviceSwitch.querySelectorAll(".seg-item").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    // 换了设备要重新拉数据，热力图与汇总都跟着那台走喵
    clearShotReady();
    loadStats();
  });
}

// 设置页的清理按钮喵
const storageCleanupButton = document.getElementById("storage-cleanup");
if (storageCleanupButton) storageCleanupButton.addEventListener("click", cleanupStorage);
el.peopleAdd.addEventListener("click", () => {
  state.peopleDraft.push({ name: `设备组 ${state.peopleDraft.length + 1}`, devices: [] });
  renderPeopleEditor();
});
el.peopleCancel.addEventListener("click", closePeopleEditor);
el.peopleSave.addEventListener("click", savePeopleEditor);
el.peopleEditor.addEventListener("click", handlePeopleEditorEvent);
el.peopleEditor.addEventListener("change", handlePeopleEditorEvent);
el.peopleEditor.addEventListener("input", handlePeopleEditorEvent);

el.tlDevice.addEventListener("change", () => {
  state.timelineDeviceId = el.tlDevice.value;
  loadTimeline();
});
el.tlDate.addEventListener("change", loadTimeline);
  // 缩放按钮：一次翻一倍，从 1 倍到秒级也就十几下喵
  el.tlZoomIn.addEventListener("click", () => setTimelineZoom(timelineZoom() * 2));
  el.tlZoomOut.addEventListener("click", () => setTimelineZoom(timelineZoom() / 2));
  el.tlZoomReset.addEventListener("click", () => setTimelineZoom(1));
  // 「现在」竖线按帧平滑右移，标签精确到秒喵
  startTimelineNowTicker();
  // 横向滚动时补画刻度，保证可视范围里始终有标签喵
  el.tlScroll.addEventListener("scroll", () => {
    // 喵~防御：一帧只补画一次，滚动再快也不卡喵
    if (state.timelineAxisFrame) return;
    state.timelineAxisFrame = window.requestAnimationFrame(() => {
      state.timelineAxisFrame = 0;
      renderTimelineAxis();
    });
  });
  // 指针：移入时显示虚线轴线与标题浮层，移出时收起喵
  el.tlTrack.addEventListener("mousemove", handleTimelinePointer);
  el.tlTrack.addEventListener("mouseleave", hideTimelinePointer);
  // 泳道区也支持悬停，鼠标落在应用行上同样能看到时刻与状态喵
  el.tlLanes.addEventListener("mousemove", handleTimelinePointer);
  el.tlLanes.addEventListener("mouseleave", hideTimelinePointer);
  // 滚轮缩放与拖拽平移喵
  // 浮层挂到 body 上，彻底躲开滚动容器的裁剪喵
  document.body.appendChild(el.tlTip);
  el.tlScroll.addEventListener("wheel", handleTimelineWheel, { passive: false });
  el.tlInner.addEventListener("pointerdown", startTimelineDrag);
  window.addEventListener("pointermove", moveTimelineDrag);
  window.addEventListener("pointerup", endTimelineDrag);
el.tlPrev.addEventListener("click", () => shiftTimelineDate(-1));
el.tlNext.addEventListener("click", () => shiftTimelineDate(1));
el.tlToday.addEventListener("click", () => {
  state.timelineDate = localDateText(serverNow());
  el.tlDate.value = state.timelineDate;
  loadTimeline();
});

el.botSend.addEventListener("click", sendBotCommand);
el.botInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendBotCommand();
});
el.botChips.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  el.botInput.value = chip.dataset.text || "";
  el.botInput.focus();
  sendBotCommand();
});
el.botCopy.addEventListener("click", async () => {
  const text = el.botReply.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    showToast("已复制到剪贴板", "ok");
  } catch (error) {
    showToast("复制失败，请手动选中复制", "error");
  }
});

window.addEventListener("hashchange", () => {
  const { tab, deviceId } = readHash();
  state.selectedId = deviceId;
  switchTab(tab);
});

// 喵~注意：标签页切回前台时立刻补一次增量刷新，别让时间轴停在旧画面喵
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (state.tab !== "timeline" || !state.token) return;
  loadTimeline({ silent: true });
});

/* ==================== 启动 ==================== */

/** 页面初始化喵。 */
function bootstrap() {
  const { tab, deviceId } = readHash();
  state.tab = tab;
  state.selectedId = deviceId;
  // 截图参数要在第一次渲染之前套上，否则会先画一遍默认值再闪一下喵
  applyShotParams();
  // 按钮高亮跟着参数走，图里才显示正确的档位喵
  syncShotButtons();
  syncAutoRefresh();
  switchTab(tab);
  // 截图时缩放到指定倍数后，再滚到指定时刻喵
  const shot = readShotParams();
  if (tab === "timeline") {
    if (shot.from_time && shot.to_time) {
      // 窗口模式：记下要居中的片段，等 renderTimeline 画完再滚喵
      state.pendingShotFocus = { mode: "window", from: shot.from_time, to: shot.to_time };
    } else if (shot.at) {
      // 单点模式：同上，靠渲染完成来触发喵
      state.pendingShotFocus = { mode: "at", at: shot.at };
    }
  }
  if (state.token) {
    refreshAll();
  } else {
    setLive("", "未连接");
    openTokenModal();
  }
}

bootstrap();