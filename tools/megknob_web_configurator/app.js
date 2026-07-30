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
  calibPressPct: document.getElementById('calib-press-pct'),
  calibReleasePct: document.getElementById('calib-release-pct'),
  calibBaseline: document.getElementById('btn-calib-baseline'),
  calibBottom: document.getElementById('btn-calib-bottom'),
  calibCompute: document.getElementById('btn-calib-compute'),
  calibHoldAll: document.getElementById('calib-hold-all'),
  calibResult: document.getElementById('calib-result'),
  calibBars: document.getElementById('calib-bars'),
  calibExport: document.getElementById('btn-calib-export'),
  calibApply: document.getElementById('btn-calib-apply'),
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

// --- Per-key calibration wizard (web side) ---
// Per the roadmap (短期目标: 逐键校准): sampling and threshold computation
// happen entirely here in the web app; the firmware only receives the final
// per-key press/release thresholds (see Issue D) and stores them in NVS. This
// wizard therefore needs no special firmware "calibration mode" -- it reuses
// the same live v3 waveform stream (real device or demo) for sampling.
const calibration = {
  baseline: new Array(CHANNEL_COUNT).fill(null),
  bottom: new Array(CHANNEL_COUNT).fill(null),
  results: null,
};

// Active sampling window, or null when idle. Filled by feedCalibSampling()
// from handleDecodedFrames() so both the real device and the demo source feed it.
let calibSampling = null;

// --- 校准竖条可视化 ---
// 每通道一条竖直电平条：灰色轨道代表 0-3300mV，白色游标是实时电压，
// 采静止电压后出基准线，采满行程后把动态范围填色，计算阈值后标出触发/释放线。
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

// 每帧调用：只更新实时电压游标。
function updateCalibCursors() {
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    calbarEls[i].cursor.style.top = mvToTopPct(state.latest[i]) + '%';
  }
}

// 校准数据变化时调用：更新静止电压线、动态范围填色、触发/释放阈值线。
function updateCalibBars() {
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const e = calbarEls[i];
    const b = calibration.baseline[i];
    const bot = calibration.bottom[i];
    const r = calibration.results && calibration.results[i] && calibration.results[i].ok
      ? calibration.results[i] : null;

    e.baseline.style.display = b == null ? 'none' : 'block';
    if (b != null) {
      e.baseline.style.top = mvToTopPct(b) + '%';
    }

    if (b != null && bot != null) {
      const top = Math.min(mvToTopPct(b), mvToTopPct(bot));
      const height = Math.abs(mvToTopPct(bot) - mvToTopPct(b));
      e.range.style.display = 'block';
      e.range.style.top = top + '%';
      e.range.style.height = height + '%';
    } else {
      e.range.style.display = 'none';
    }

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

function startCalibSampling(which) {
  if (!demo.active && !state.connected) {
    alert('请先“连接设备”，或点“演示模式”用模拟数据体验校准流程。');
    return;
  }
  calibSampling = {
    which,
    startMs: performance.now(),
    durationMs: 2000,
    acc: Array.from({ length: CHANNEL_COUNT }, () => ({ sum: 0, count: 0, min: Infinity, max: -Infinity })),
  };
  updateCalibUI();
}

function feedCalibSampling(samples, nowMs) {
  if (!calibSampling) {
    return;
  }
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const a = calibSampling.acc[i];
    a.sum += samples[i];
    a.count++;
    a.min = Math.min(a.min, samples[i]);
    a.max = Math.max(a.max, samples[i]);
  }
  if (nowMs - calibSampling.startMs >= calibSampling.durationMs) {
    finishCalibSampling();
  }
}

function finishCalibSampling() {
  const s = calibSampling;
  calibSampling = null;
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const a = s.acc[i];
    if (a.count === 0) {
      continue;
    }
    if (s.which === 'baseline') {
      calibration.baseline[i] = a.sum / a.count; // 松开：取平均
    } else {
      calibration.bottom[i] = a.min; // press_is_greater=false：按到底电压最低
    }
  }
  calibration.results = null; // 重新采样后旧结果作废
  updateCalibUI();
}

function computeCalibThresholds() {
  const pressPct = parseFloat(el.calibPressPct.value) / 100;
  const releasePct = parseFloat(el.calibReleasePct.value) / 100;
  const results = [];
  for (let i = 0; i < CHANNEL_COUNT; i++) {
    const b = calibration.baseline[i];
    const bot = calibration.bottom[i];
    if (b == null || bot == null) {
      results.push({ i, ok: false, reason: '缺少采样' });
      continue;
    }
    const range = b - bot;
    const press = b - range * pressPct;
    const release = b - range * releasePct;
    let quality = 'ok';
    if (range < 80) {
      quality = 'bad';
    } else if (range < 200) {
      quality = 'warn';
    }
    results.push({ i, ok: true, baseline: b, bottom: bot, range, press, release, quality });
  }
  calibration.results = results;
  updateCalibUI();
}

function renderCalibResults() {
  if (!calibration.results) {
    const hasBaseline = calibration.baseline.filter((v) => v != null).length;
    const hasBottom = calibration.bottom.filter((v) => v != null).length;
    const hint = (hasBaseline || hasBottom)
      ? `已采静止电压 ${hasBaseline}/24，满行程 ${hasBottom}/24。`
      : '尚未采样。';
    el.calibResult.innerHTML = `<div class="calib-empty">${hint}</div>`;
    return;
  }

  let html = '<table class="calib-table"><thead><tr>' +
    '<th>通道</th><th>静止</th><th>行程</th><th>触发</th><th>释放</th>' +
    '</tr></thead><tbody>';
  for (const r of calibration.results) {
    if (!r.ok) {
      html += `<tr class="bad"><td>${CHANNEL_NAMES[r.i]}</td><td colspan="4">${r.reason}</td></tr>`;
    } else {
      html += `<tr class="${r.quality}">` +
        `<td>${CHANNEL_NAMES[r.i]}</td>` +
        `<td>${Math.round(r.baseline)}</td>` +
        `<td>${Math.round(r.range)}</td>` +
        `<td>${Math.round(r.press)}</td>` +
        `<td>${Math.round(r.release)}</td></tr>`;
    }
  }
  html += '</tbody></table>';
  el.calibResult.innerHTML = html;
}

function updateCalibUI() {
  const hasBaseline = calibration.baseline.some((v) => v != null);
  const hasBottom = calibration.bottom.some((v) => v != null);
  let text;
  if (calibSampling) {
    text = calibSampling.which === 'baseline'
      ? '正在采样静止电压… 请保持所有按键松开（约 2 秒）。'
      : '正在采样满行程… 请把所有按键按到底（演示可勾选“按住全部”，约 2 秒）。';
  } else if (!hasBaseline) {
    text = '第 ① 步：松开所有按键，点“采静止电压”。';
  } else if (!hasBottom) {
    text = '第 ② 步：把所有按键按到底，点“采满行程”。';
  } else if (!calibration.results) {
    text = '第 ③ 步：点“计算阈值”生成每键触发/释放值。';
  } else {
    text = '校准完成。可导出数据；“下发到设备”需固件命令协议。';
  }
  el.calibStatus.textContent = text;
  renderCalibResults();
  updateCalibBars();
}

function exportCalibJson() {
  if (!calibration.results) {
    alert('请先完成采样并“计算阈值”。');
    return;
  }
  const data = {
    version: 1,
    pressPercent: parseFloat(el.calibPressPct.value),
    releasePercent: parseFloat(el.calibReleasePct.value),
    note: '每键绝对阈值（毫伏）；press_is_greater=false（按下电压下降）；baseline=静止电压 bottom=满行程 press=触发 release=释放',
    channels: calibration.results.map((r) => (r.ok ? {
      name: CHANNEL_NAMES[r.i],
      baseline: Math.round(r.baseline),
      bottom: Math.round(r.bottom),
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
el.calibBaseline.addEventListener('click', () => startCalibSampling('baseline'));
el.calibBottom.addEventListener('click', () => startCalibSampling('bottom'));
el.calibCompute.addEventListener('click', computeCalibThresholds);
el.calibExport.addEventListener('click', exportCalibJson);
el.calibApply.addEventListener('click', () =>
  alert('“下发到设备”需要固件 Issue D 双向命令协议，当前仅支持预览与导出校准 JSON。'));
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
  updateCalibCursors();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

if (!('serial' in navigator)) {
  setStatus(false, '浏览器不支持 Web Serial（需 Chrome/Edge）');
  el.connect.disabled = true;
}
