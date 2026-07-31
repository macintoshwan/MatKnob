/*
 * MegKnob Web Configurator - main thread UI logic.
 *
 * MVP scope (roadmap Issue B, tools/privateDocs/DevDiary.md):
 *   - Web Serial connect/disconnect, device status
 *   - Parse the existing protocol v3 62-byte frame (decoding happens in
 *     frame-worker.js, off the UI thread)
 *   - Real-time 24-channel waveform, channel enable/mV/min/max/avg/p2p
 *   - scan rate / RX fps / CRC errors / sequence loss
 *   - CSV export
 *
 * Deliberately NOT in this first pass (see Issue D, mid-term goals):
 *   - Any host-to-device command/write protocol (threshold config, save,
 *     restore defaults, start/stop streaming)
 *   - ZMK Studio integration
 */

const CHANNEL_COUNT = 24;

// Channel palettes: a bright set for dark editor themes and a more saturated
// set that stays readable on the light themes (vscode-light / arduino / cubemx).
const CHANNEL_COLORS_DARK = [
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#e8e8e8', '#72ffda',
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#e8e8e8', '#72ffda',
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#e8e8e8', '#72ffda',
];
const CHANNEL_COLORS_LIGHT = [
  '#b8860b', '#0077b6', '#c2185b', '#1e7e34', '#c7511f', '#6a3df0', '#5a5a5a', '#0f7b6c',
  '#b8860b', '#0077b6', '#c2185b', '#1e7e34', '#c7511f', '#6a3df0', '#5a5a5a', '#0f7b6c',
  '#b8860b', '#0077b6', '#c2185b', '#1e7e34', '#c7511f', '#6a3df0', '#5a5a5a', '#0f7b6c',
];
function channelColors() {
  return isLightTheme() ? CHANNEL_COLORS_LIGHT : CHANNEL_COLORS_DARK;
}

// --- VSCode-style panel switcher (activity bar <-> sidebar) ---
// To add a new tool panel later: add a <section class="panel-view"
// data-panel="<id>"> in the sidebar plus an activity-bar <button
// data-panel="<id>">, then list the id here. The switcher is generic.
const PANELS = ['monitor', 'calibrate', 'connect', 'settings'];

function activatePanel(id) {
  document.querySelectorAll('.activity-bar button').forEach((b) => {
    b.classList.toggle('active', b.dataset.panel === id);
  });
  document.querySelectorAll('.panel-view').forEach((s) => {
    s.classList.toggle('active', s.dataset.panel === id);
  });
}

function initPanels() {
  document.querySelectorAll('.activity-bar button').forEach((b) => {
    b.addEventListener('click', () => activatePanel(b.dataset.panel));
  });
}

// --- Themes (vscode-dark / vscode-light / arduino / cubemx) ---
const THEME_KEY = 'megknob-theme';
const LIGHT_THEMES = new Set(['vscode-light', 'arduino', 'cubemx']);

function isLightTheme() {
  return LIGHT_THEMES.has(document.body.dataset.theme);
}

function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  document.querySelectorAll('.theme-select').forEach((s) => { s.value = theme; });
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
  if (typeof buildChannelList === 'function') {
    buildChannelList(); // 刷新通道色块以匹配新主题
  }
}

function initTheme() {
  let saved = 'vscode-dark';
  try { saved = localStorage.getItem(THEME_KEY) || 'vscode-dark'; } catch (e) { /* ignore */ }
  applyTheme(saved);
  document.querySelectorAll('.theme-select').forEach((s) => {
    s.addEventListener('change', () => applyTheme(s.value));
  });
}
const CHANNEL_NAMES = (() => {
  const groups = ['U26', 'U27', 'U28'];
  const names = [];
  for (const g of groups) {
    for (let y = 0; y < 8; y++) {
      names.push(`${g}·Y${y}`);
    }
  }
  return names;
})();

// Bounded history: only keep slightly more than the current timebase needs,
// mirroring the "history retained ~110% of current timebase" fix from the
// 2026-07-20 dev log entry so long sessions do not grow memory unbounded.
class ChannelHistory {
  constructor() {
    this.maxSeconds = 20 * 1.2;
    this.points = []; // { tMs, values: Float32Array(24) }
  }

  push(tMs, values) {
    this.points.push({ tMs, values });
    const cutoff = tMs - this.maxSeconds * 1000;
    let i = 0;
    while (i < this.points.length && this.points[i].tMs < cutoff) {
      i++;
    }
    if (i > 0) {
      this.points.splice(0, i);
    }
  }

  clear() {
    this.points = [];
  }

  slice(sinceMs) {
    const out = [];
    for (let i = this.points.length - 1; i >= 0; i--) {
      if (this.points[i].tMs < sinceMs) break;
      out.push(this.points[i]);
    }
    out.reverse();
    return out;
  }
}

const state = {
  port: null,
  reader: null,
  readLoopAbort: null,
  worker: new Worker('frame-worker.js'),
  history: new ChannelHistory(),
  channelEnabled: new Array(CHANNEL_COUNT).fill(true),
  latest: new Array(CHANNEL_COUNT).fill(0),
  stats: Array.from({ length: CHANNEL_COUNT }, () => ({ min: Infinity, max: -Infinity, sum: 0, count: 0 })),
  firstTimestampUs: null,
  firstWallMs: null,
  connected: false,
  exportRows: [],
};

const el = {
  connect: document.getElementById('btn-connect'),
  disconnect: document.getElementById('btn-disconnect'),
  clear: document.getElementById('btn-clear'),
  exportBtn: document.getElementById('btn-export'),
  demo: document.getElementById('btn-demo'),
  calibStatus: document.getElementById('calib-status'),
  calibTrigger: document.getElementById('calib-trigger'),
  calibHysteresis: document.getElementById('calib-hysteresis'),
  calibRecord: document.getElementById('btn-calib-record'),
  calibSend: document.getElementById('btn-calib-send'),
  calibHoldAll: document.getElementById('calib-hold-all'),
  calibResult: document.getElementById('calib-result'),
  calibBars: document.getElementById('calib-bars'),
  calibExport: document.getElementById('btn-calib-export'),
  statusDot: document.getElementById('status-dot'),
  statusText: document.getElementById('status-text'),
  timebase: document.getElementById('timebase'),
  vrange: document.getElementById('vrange'),
  canvas: document.getElementById('wave-canvas'),
  channels: document.getElementById('channels'),
  mScanHz: document.getElementById('m-scan-hz'),
  mRxHz: document.getElementById('m-rx-hz'),
  mThroughput: document.getElementById('m-throughput'),
  mLost: document.getElementById('m-lost'),
  mCrc: document.getElementById('m-crc'),
  mVersion: document.getElementById('m-version'),
};

function setStatus(connected, text) {
  state.connected = connected;
  el.statusDot.classList.toggle('connected', connected);
  el.statusText.textContent = text;
  el.connect.disabled = connected;
  el.disconnect.disabled = !connected;
}

function buildChannelList() {
  el.channels.innerHTML = '';
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const row = document.createElement('div');
    row.className = 'channel-row';

    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = true;
    check.addEventListener('change', () => {
      state.channelEnabled[i] = check.checked;
    });

    const cols = channelColors();
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = cols[i];

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = CHANNEL_NAMES[i];

    const val = document.createElement('span');
    val.className = 'val';
    val.id = `ch-val-${i}`;
    val.textContent = '- mV';

    const minmax = document.createElement('span');
    minmax.className = 'minmax';
    minmax.id = `ch-minmax-${i}`;
    minmax.textContent = '-/-';

    row.append(check, swatch, name, val, minmax);
    el.channels.appendChild(row);
  }
}

function resizeCanvas() {
  const canvas = el.canvas;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
}

function drawWaveform() {
  const canvas = el.canvas;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  // Grid.
  ctx.strokeStyle = cssVar('--grid') || '#2b2b2b';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  const timebaseS = parseFloat(el.timebase.value);
  const vRangeMv = parseFloat(el.vrange.value);
  const nowMs = performance.now();
  const points = state.history.slice(nowMs - timebaseS * 1000);

  if (points.length < 2) {
    return;
  }

  const t0 = points[0].tMs;
  const tSpan = Math.max(1, nowMs - t0);

  const cols = channelColors();
  for (let ch = 0; ch < CHANNEL_COUNT; ch++) {
    if (!state.channelEnabled[ch]) continue;

    ctx.strokeStyle = cols[ch];
    ctx.lineWidth = 1.25;
    ctx.beginPath();

    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      const x = ((p.tMs - t0) / tSpan) * w;
      const mv = p.values[ch];
      const y = h - (mv / vRangeMv) * h;
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }
}

function updateChannelPanel() {
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const valEl = document.getElementById(`ch-val-${i}`);
    const minmaxEl = document.getElementById(`ch-minmax-${i}`);
    if (!valEl || !minmaxEl) continue;

    valEl.textContent = `${state.latest[i]} mV`;
    const s = state.stats[i];
    if (s.count > 0) {
      const avg = s.sum / s.count;
      const p2p = s.max - s.min;
      minmaxEl.textContent = `${s.min}/${s.max}`;
      minmaxEl.title = `min ${s.min} mV, max ${s.max} mV, avg ${avg.toFixed(1)} mV, 峰峰值 ${p2p} mV`;
    }
  }
}

function updateMetricsPanel(metrics) {
  // Derived from the firmware's own microsecond timestamps on data frames
  // (see frame-worker.js's deviceScanHz), not from perf frames (which are
  // currently zeroed on the firmware side, see hall_telemetry.c) and not
  // estimated by the browser -- so this is a real device-side scan rate.
  el.mScanHz.textContent = metrics.deviceScanHz > 0 ? `${metrics.deviceScanHz.toFixed(1)} Hz` : '-';
  el.mRxHz.textContent = `${metrics.hostReceiveHz.toFixed(1)} fps`;
  el.mThroughput.textContent = `${(metrics.throughputBytesPerS / 1024).toFixed(1)} KB/s`;
  el.mLost.textContent = String(metrics.lostFrames);
  el.mLost.classList.toggle('warn', metrics.lostFrames > 0);
  el.mCrc.textContent = String(metrics.crcErrors);
  el.mCrc.classList.toggle('warn', metrics.crcErrors > 0);
  el.mVersion.textContent = 'v3';
}

function handleDecodedFrames(frames) {
  const nowMs = performance.now();

  for (const frame of frames) {
    if (frame.type !== 1 /* TYPE_DATA */ || frame.count !== CHANNEL_COUNT) {
      continue;
    }

    if (state.firstTimestampUs === null) {
      state.firstTimestampUs = frame.timestampUs;
      state.firstWallMs = nowMs;
    }

    state.latest = frame.samples;
    for (let i = 0; i < CHANNEL_COUNT; i++) {
      const mv = frame.samples[i];
      const s = state.stats[i];
      s.min = Math.min(s.min, mv);
      s.max = Math.max(s.max, mv);
      s.sum += mv;
      s.count++;
    }

    state.history.push(nowMs, new Float32Array(frame.samples));
    state.exportRows.push([frame.seq, frame.timestampUs, ...frame.samples]);
    feedCalibSampling(frame.samples, nowMs);
    // Cap exported rows in memory; CSV export for very long sessions should
    // use a fresh capture rather than accumulating unbounded rows in a tab.
    if (state.exportRows.length > 200000) {
      state.exportRows.shift();
    }
  }
}

state.worker.onmessage = (event) => {
  const { kind, frames, metrics } = event.data;
  if (kind === 'frames') {
    handleDecodedFrames(frames);
    updateMetricsPanel(metrics);
  }
};

async function connect() {
  if (!('serial' in navigator)) {
    alert('当前浏览器不支持 Web Serial，请使用最新版 Chrome 或 Edge。');
    return;
  }

  try {
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200 });
    state.port = port;

    setStatus(true, '已连接');
    state.worker.postMessage({ kind: 'reset' });
    state.history.clear();
    state.exportRows = [];
    state.firstTimestampUs = null;

    const reader = port.readable.getReader();
    state.reader = reader;

    readLoop(reader);
  } catch (err) {
    console.error(err);
    setStatus(false, `连接失败: ${err.message}`);
  }
}

async function readLoop(reader) {
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value && value.length > 0) {
        state.worker.postMessage({ kind: 'bytes', payload: value.buffer }, [value.buffer]);
      }
    }
  } catch (err) {
    console.error('read loop error', err);
  } finally {
    setStatus(false, '已断开');
  }
}

async function disconnect() {
  try {
    if (state.reader) {
      await state.reader.cancel();
      state.reader.releaseLock();
      state.reader = null;
    }
    if (state.port) {
      await state.port.close();
      state.port = null;
    }
  } catch (err) {
    console.error(err);
  } finally {
    setStatus(false, '未连接');
  }
}

function clearAll() {
  state.history.clear();
  state.exportRows = [];
  state.stats = Array.from({ length: CHANNEL_COUNT }, () => ({ min: Infinity, max: -Infinity, sum: 0, count: 0 }));
  state.worker.postMessage({ kind: 'reset' });
}

function exportCsv() {
  if (state.exportRows.length === 0) {
    alert('还没有采集到数据。');
    return;
  }

  const header = ['seq', 'timestamp_us', ...CHANNEL_NAMES].join(',');
  const lines = [header];
  for (const row of state.exportRows) {
    lines.push(row.join(','));
  }

  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `megknob_capture_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// --- 逐键校准（网页端） ---
// 依据路线图（短期目标: 逐键校准）：采样与阈值计算全部在网页端完成，
// 固件只接收最终的每键触发/释放阈值（见 Issue D）并存入 NVS，
// 因此不需要固件实现专门的“校准模式”。
//
// 交互流程（2026-07-30 与用户确认）：
//   1. 点“按键量程检测”开始记录，随后随机按下所有按键；
//   2. 系统实时记录每键最大/最小电压（松开最高=静止，按到底最低=满行程，
//      因为 press_is_greater=false，按下电压下降）；
//   3. 点“量程标定完成”锁定每键量程 [min, max]；
//   4. 设定“触发行程”（如 0.1 = 按下 10% 量程触发）与“滞回区间”（如 0.1 或 0.01）；
//   5. 点“发送标定数值”把每键阈值经命令帧下发到固件（需固件 Issue D 协议）。
const calibration = {
  min: new Array(CHANNEL_COUNT).fill(null), // 满行程电压（按到底最低）
  max: new Array(CHANNEL_COUNT).fill(null), // 静止电压（松开最高）
  results: null,                            // 每键 {min,max,range,press,release,quality,ok}
};

let calibRecording = false;

// --- 校准竖条可视化 ---
// 每通道一条竖直电平条：灰色轨道代表 0-3300mV，游标是实时电压，
// 静止基准线=max，量程填色=min~max，触发/释放阈值各一条线。
const CAL_MAX_MV = 3300;
let calbarEls = [];

function mvToTopPct(mv) {
  return (1 - Math.max(0, Math.min(CAL_MAX_MV, mv)) / CAL_MAX_MV) * 100;
}

function buildCalibBars() {
  el.calibBars.innerHTML = '';
  calbarEls = [];
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const bar = document.createElement('div');
    bar.className = 'calbar';
    bar.title = CHANNEL_NAMES[i];
    bar.innerHTML =
      '<div class="calbar-track">' +
        '<div class="calbar-range"></div>' +
        '<div class="calbar-line calbar-mark-baseline"></div>' +
        '<div class="calbar-line calbar-mark-press"></div>' +
        '<div class="calbar-line calbar-mark-release"></div>' +
        '<div class="calbar-cursor"></div>' +
      '</div>' +
      `<div class="calbar-name">Y${i % 8}</div>`;
    el.calibBars.appendChild(bar);
    calbarEls.push({
      range: bar.querySelector('.calbar-range'),
      baseline: bar.querySelector('.calbar-mark-baseline'),
      press: bar.querySelector('.calbar-mark-press'),
      release: bar.querySelector('.calbar-mark-release'),
      cursor: bar.querySelector('.calbar-cursor'),
    });
  }
}

// 每帧调用：实时游标 + 静止基准线(max) + 量程填色(min~max) + 触发/释放线。
function updateCalibVisual() {
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const e = calbarEls[i];
    e.cursor.style.top = mvToTopPct(state.latest[i]) + '%';

    const mx = calibration.max[i];
    const mn = calibration.min[i];
    e.baseline.style.display = mx == null ? 'none' : 'block';
    if (mx != null) {
      e.baseline.style.top = mvToTopPct(mx) + '%';
    }

    if (mn != null && mx != null) {
      const top = mvToTopPct(mx);
      e.range.style.display = 'block';
      e.range.style.top = top + '%';
      e.range.style.height = (mvToTopPct(mn) - top) + '%';
    } else {
      e.range.style.display = 'none';
    }

    const r = calibration.results && calibration.results[i] && calibration.results[i].ok
      ? calibration.results[i] : null;
    if (r) {
      e.press.style.display = 'block';
      e.press.style.top = mvToTopPct(r.press) + '%';
      e.release.style.display = 'block';
      e.release.style.top = mvToTopPct(r.release) + '%';
    } else {
      e.press.style.display = 'none';
      e.release.style.display = 'none';
    }
  }
}

// “按键量程检测” ↔ “量程标定完成”切换。
function toggleCalibRecording() {
  if (!demo.active && !state.connected) {
    alert('请先“连接设备”，或点“演示模式”用模拟数据体验校准流程。');
    return;
  }
  if (calibRecording) {
    calibRecording = false; // 量程标定完成：锁定并计算阈值
    computeCalibThresholds();
  } else {
    calibration.min.fill(null); // 开始检测：清空每键极值重新记录
    calibration.max.fill(null);
    calibration.results = null;
    calibRecording = true;
  }
  updateCalibUI();
}

// 记录中：对每键累积 min/max（在 handleDecodedFrames 里被调用，真实/演示数据均可）。
function feedCalibSampling(samples, nowMs) {
  if (!calibRecording) {
    return;
  }
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const v = samples[i];
    calibration.min[i] = calibration.min[i] == null ? v : Math.min(calibration.min[i], v);
    calibration.max[i] = calibration.max[i] == null ? v : Math.max(calibration.max[i], v);
  }
}

function clamp01(x) {
  return Math.max(0, Math.min(1, isNaN(x) ? 0 : x));
}

// 触发行程(比例) + 滞回区间(比例) → 每键触发/释放阈值。
// 触发 = max - 触发行程*量程；释放 = 触发 + 滞回*量程（不超过 max）。
function computeCalibThresholds() {
  const triggerRatio = clamp01(parseFloat(el.calibTrigger.value));
  const hysteresis = clamp01(parseFloat(el.calibHysteresis.value));
  const results = [];
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const mn = calibration.min[i];
    const mx = calibration.max[i];
    if (mn == null || mx == null) {
      results.push({ i, ok: false, reason: '未检测到' });
      continue;
    }
    const range = mx - mn;
    const press = mx - triggerRatio * range;
    let release = press + hysteresis * range;
    if (release > mx) {
      release = mx;
    }
    let quality = 'ok';
    if (range < 80) {
      quality = 'bad';
    } else if (range < 200) {
      quality = 'warn';
    }
    results.push({ i, ok: true, min: mn, max: mx, range, press, release, quality });
  }
  calibration.results = results;
  updateCalibUI();
}

function renderCalibResults() {
  if (!calibration.results) {
    const detected = calibration.max.filter((v) => v != null).length;
    const hint = detected > 0 ? `已检测 ${detected}/24 键的量程。` : '尚未开始检测。';
    el.calibResult.innerHTML = `<div class="calib-empty">${hint}</div>`;
    return;
  }

  let html = '<table class="calib-table"><thead><tr>' +
    '<th>通道</th><th>静止</th><th>量程</th><th>触发</th><th>释放</th>' +
    '</tr></thead><tbody>';
  for (const r of calibration.results) {
    if (!r.ok) {
      html += `<tr class="bad"><td>${CHANNEL_NAMES[r.i]}</td><td colspan="4">${r.reason}</td></tr>`;
    } else {
      html += `<tr class="${r.quality}">` +
        `<td>${CHANNEL_NAMES[r.i]}</td>` +
        `<td>${Math.round(r.max)}</td>` +
        `<td>${Math.round(r.range)}</td>` +
        `<td>${Math.round(r.press)}</td>` +
        `<td>${Math.round(r.release)}</td></tr>`;
    }
  }
  html += '</tbody></table>';
  el.calibResult.innerHTML = html;
}

function updateCalibUI() {
  const hasRange = calibration.max.some((v) => v != null);
  let text;
  if (calibRecording) {
    text = '正在检测量程… 请随机按下所有按键，覆盖每键从静止到按到底。';
  } else if (!hasRange) {
    text = '第 ① 步：点“按键量程检测”，然后随机按下所有按键。';
  } else if (!calibration.results) {
    text = '第 ② 步：点“量程标定完成”。';
  } else {
    text = '第 ③ 步：确认触发行程/滞回区间，点“发送标定数值”。';
  }
  el.calibStatus.textContent = text;
  el.calibRecord.textContent = calibRecording ? '量程标定完成' : (hasRange ? '重新检测量程' : '按键量程检测');
  el.calibSend.disabled = !(calibration.results && calibration.results.some((r) => r.ok));
  renderCalibResults();
}

function exportCalibJson() {
  if (!calibration.results) {
    alert('请先完成量程检测。');
    return;
  }
  const data = {
    version: 2,
    triggerRatio: clamp01(parseFloat(el.calibTrigger.value)),
    hysteresis: clamp01(parseFloat(el.calibHysteresis.value)),
    note: '每键绝对阈值（毫伏）；press_is_greater=false（按下电压下降）；min=满行程 max=静止 press=触发 release=释放',
    channels: calibration.results.map((r) => (r.ok ? {
      name: CHANNEL_NAMES[r.i],
      min: Math.round(r.min),
      max: Math.round(r.max),
      range: Math.round(r.range),
      press: Math.round(r.press),
      release: Math.round(r.release),
    } : { name: CHANNEL_NAMES[r.i], error: r.reason })),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `megknob_calibration_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// CRC-16/CCITT-FALSE（与 frame-worker.js 一致），用于命令帧校验。
function crc16(bytes, len) {
  let crc = 0xffff;
  for (let i = 0; i < len; i++) {
    crc ^= bytes[i] << 8;
    for (let bit = 0; bit < 8; bit++) {
      crc = (crc & 0x8000) !== 0 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
    }
  }
  return crc;
}

// 组装“设置每键阈值”命令帧（Issue D 主机→设备协议）：
//   'M' 'K' | ver=3 | type=0x10(命令) | cmd=0x01(设置阈值) | len=96 |
//   payload: 24 × (press:u16le, release:u16le) | crc16(对前 6+96 字节)
function buildSetThresholdsFrame() {
  const payloadLen = CHANNEL_COUNT * 4;
  const total = 6 + payloadLen + 2;
  const buf = new Uint8Array(total);
  buf[0] = 0x4d; // 'M'
  buf[1] = 0x4b; // 'K'
  buf[2] = 3;
  buf[3] = 0x10;
  buf[4] = 0x01;
  buf[5] = payloadLen;
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const r = calibration.results[i];
    const press = r.ok ? Math.round(r.press) : 0;
    const release = r.ok ? Math.round(r.release) : 0;
    const o = 6 + i * 4;
    buf[o] = press & 0xff;
    buf[o + 1] = (press >> 8) & 0xff;
    buf[o + 2] = release & 0xff;
    buf[o + 3] = (release >> 8) & 0xff;
  }
  const crc = crc16(buf, total - 2);
  buf[total - 2] = crc & 0xff;
  buf[total - 1] = (crc >> 8) & 0xff;
  return buf;
}

async function sendCalibration() {
  if (!calibration.results || !calibration.results.some((r) => r.ok)) {
    alert('请先完成量程检测。');
    return;
  }
  const frame = buildSetThresholdsFrame();
  if (!state.port) {
    alert('未连接真实设备。当前为演示/预览：固件端命令解析（Issue D）实现后，' +
          '这里会经串口把每键阈值下发到设备。可先点“导出数据”保存标定结果。');
    return;
  }
  try {
    const writer = state.port.writable.getWriter();
    await writer.write(frame);
    writer.releaseLock();
    el.calibStatus.textContent = '已发送标定数值（需固件命令协议支持后生效）。';
  } catch (err) {
    alert('发送失败: ' + err.message);
  }
}

// --- Demo mode (no hardware attached) ---
// Drives the same handleDecodedFrames()/updateMetricsPanel() pipeline as the
// real Web Serial path, but synthesizes 24 channels locally so the UI can be
// evaluated without a device. Each channel gets a different resting voltage
// (baseline) on purpose -- that per-key spread is exactly the physical root
// cause of the inconsistent feel the upcoming per-key calibration addresses.
const demo = {
  active: false,
  timer: null,
  seq: 0,
  frames: 0,
  startMs: 0,
  channels: [],
  holdAll: false, // 校准“采满行程”演示辅助：强制全部按到底
};

function initDemoChannels() {
  demo.channels = [];
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    demo.channels.push({
      baseline: 1400 + Math.random() * 1200, // 每键静止电压不同
      driftAmp: 5 + Math.random() * 12,
      driftFreq: 0.1 + Math.random() * 0.4,
      phase: Math.random() * Math.PI * 2,
      pressed: false,
      pressValue: 0,
      untilMs: 0,
      bottomDepth: 700 + Math.random() * 700, // 每键满行程深度不同 → 动态范围不同
    });
  }
}

function demoStep(nowMs) {
  const t = (nowMs - demo.startMs) / 1000;
  const samples = new Array(CHANNEL_COUNT);

  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const c = demo.channels[i];

    let target;
    if (demo.holdAll) {
      // 校准“采满行程”演示：全部稳定按到底（每键深度不同）。
      target = c.baseline - c.bottomDepth;
    } else {
      // 随机触发一次“按下”，持续 150~650ms 后释放。press_is_greater=false
      // （见 megknob.overlay），所以按下表现为电压下掉。
      if (!c.pressed && Math.random() < 0.004) {
        c.pressed = true;
        c.pressValue = c.baseline - (600 + Math.random() * 800);
        c.untilMs = nowMs + 150 + Math.random() * 500;
      }
      if (c.pressed && nowMs > c.untilMs) {
        c.pressed = false;
      }

      const drift = Math.sin(t * c.driftFreq * Math.PI * 2 + c.phase) * c.driftAmp;
      target = c.pressed ? c.pressValue : c.baseline + drift;
    }

    const noise = (Math.random() - 0.5) * 6;
    samples[i] = Math.max(0, Math.min(3300, Math.round(target + noise)));
  }

  demo.seq = (demo.seq + 1) & 0xffff;
  demo.frames++;

  handleDecodedFrames([{
    type: 1,
    mode: 3,
    count: CHANNEL_COUNT,
    seq: demo.seq,
    timestampUs: Math.round((nowMs - demo.startMs) * 1000),
    samples,
  }]);

  const elapsedS = Math.max((nowMs - demo.startMs) / 1000, 1e-6);
  const fps = demo.frames / elapsedS;
  updateMetricsPanel({
    deviceScanHz: fps, // 演示源即“设备”
    hostReceiveHz: fps,
    throughputBytesPerS: fps * 62,
    lostFrames: 0,
    crcErrors: 0,
  });
}

function startDemo() {
  if (state.port) {
    alert('已连接真实设备，请先断开再进入演示模式。');
    return;
  }
  initDemoChannels();
  state.history.clear();
  state.exportRows = [];
  state.firstTimestampUs = null;
  state.stats = Array.from({ length: CHANNEL_COUNT }, () => ({ min: Infinity, max: -Infinity, sum: 0, count: 0 }));

  demo.active = true;
  demo.seq = 0;
  demo.frames = 0;
  demo.startMs = performance.now();
  demo.timer = setInterval(() => demoStep(performance.now()), 16); // ~60fps

  el.statusDot.classList.add('connected');
  el.statusText.textContent = '演示模式（模拟数据，无硬件）';
  el.connect.disabled = true;
  el.demo.textContent = '停止演示';
}

function stopDemo() {
  demo.active = false;
  if (demo.timer) {
    clearInterval(demo.timer);
    demo.timer = null;
  }
  el.statusDot.classList.remove('connected');
  el.statusText.textContent = '未连接';
  el.connect.disabled = !('serial' in navigator);
  el.demo.textContent = '演示模式';
}

function toggleDemo() {
  if (demo.active) {
    stopDemo();
  } else {
    startDemo();
  }
}

el.connect.addEventListener('click', connect);
el.disconnect.addEventListener('click', disconnect);
el.clear.addEventListener('click', clearAll);
el.exportBtn.addEventListener('click', exportCsv);
el.demo.addEventListener('click', toggleDemo);
el.calibRecord.addEventListener('click', toggleCalibRecording);
el.calibSend.addEventListener('click', sendCalibration);
el.calibExport.addEventListener('click', exportCalibJson);
el.calibTrigger.addEventListener('change', () => {
  if (calibration.max.some((v) => v != null)) { computeCalibThresholds(); }
});
el.calibHysteresis.addEventListener('change', () => {
  if (calibration.max.some((v) => v != null)) { computeCalibThresholds(); }
});
el.calibHoldAll.addEventListener('change', () => { demo.holdAll = el.calibHoldAll.checked; });
window.addEventListener('resize', resizeCanvas);

initPanels();
initTheme();
buildChannelList();
buildCalibBars();
resizeCanvas();
setStatus(false, '未连接');
updateCalibUI();

function animate() {
  drawWaveform();
  updateChannelPanel();
  updateCalibVisual();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

if (!('serial' in navigator)) {
  setStatus(false, '浏览器不支持 Web Serial（需 Chrome/Edge）');
  el.connect.disabled = true;
}
