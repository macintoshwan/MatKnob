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
const CHANNEL_COLORS = [
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#f5f5f5', '#72ffda',
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#f5f5f5', '#72ffda',
  '#ffd000', '#00d8ff', '#ff4dcb', '#57e389', '#ff7b45', '#9d7cff', '#f5f5f5', '#72ffda',
];
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

    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = CHANNEL_COLORS[i];

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
  ctx.strokeStyle = '#21252c';
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

  for (let ch = 0; ch < CHANNEL_COUNT; ch++) {
    if (!state.channelEnabled[ch]) continue;

    ctx.strokeStyle = CHANNEL_COLORS[ch];
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

el.connect.addEventListener('click', connect);
el.disconnect.addEventListener('click', disconnect);
el.clear.addEventListener('click', clearAll);
el.exportBtn.addEventListener('click', exportCsv);
window.addEventListener('resize', resizeCanvas);

buildChannelList();
resizeCanvas();
setStatus(false, '未连接');

function animate() {
  drawWaveform();
  updateChannelPanel();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

if (!('serial' in navigator)) {
  setStatus(false, '浏览器不支持 Web Serial（需 Chrome/Edge）');
  el.connect.disabled = true;
}
