/*
 * MegKnob Web Configurator - frame decoding worker.
 *
 * Runs off the UI thread so parsing/CRC work for a high-rate byte stream
 * never causes dropped frames or a janky UI, mirroring the "protocol
 * parsing and plotting in a Web Worker" principle from the roadmap (Issue
 * B in tools/privateDocs/DevDiary.md).
 *
 * Wire format (implemented by app/module/lib/hall_telemetry/hall_telemetry.c):
 * little-endian 62-byte frames.
 *
 *   offset  size  field
 *   0       2     magic "MK"
 *   2       1     protocol version (3)
 *   3       1     type: 1 data, 2 mode, 3 perf
 *   4       1     mode: 0 U26, 1 U27, 2 U28, 3 all
 *   5       1     sample count: 24 data, 0 mode, 4 perf
 *   6       2     sequence number
 *   8       4     uint32 microsecond timestamp (wraps ~71.6 min)
 *   12      48    24x uint16 mV samples (data) / first 4 used for perf us
 *   60      2     CRC-16/CCITT-FALSE over bytes 0-59
 */

const FRAME_SIZE = 62;
const MAGIC0 = 0x4d; // 'M'
const MAGIC1 = 0x4b; // 'K'
const PROTOCOL_VERSION = 3;

const TYPE_DATA = 1;
const TYPE_MODE = 2;
const TYPE_PERF = 3;

// CRC-16/CCITT-FALSE, byte-at-a-time bitwise implementation. Matches
// tools/megknob_hall_viewer.py's crc16() and the nibble-table firmware
// implementation in hall_telemetry.c (verified to produce identical output
// for the same input during development).
function crc16(bytes, len) {
  let crc = 0xffff;
  for (let i = 0; i < len; i++) {
    crc ^= bytes[i] << 8;
    for (let bit = 0; bit < 8; bit++) {
      crc =
        (crc & 0x8000) !== 0
          ? ((crc << 1) ^ 0x1021) & 0xffff
          : (crc << 1) & 0xffff;
    }
  }
  return crc;
}

let buffer = new Uint8Array(0);

// Rolling counters, mirroring Metrics in tools/megknob_hall_viewer.py so the
// two tools report comparable numbers (see Issue B acceptance criteria:
// "Web端 CRC、序号和数值结果与 Python 上位机一致").
const metrics = {
  frames: 0,
  dataFrames: 0,
  crcErrors: 0,
  lostFrames: 0,
  bytes: 0,
  lastSeq: null,
  startedAt: performance.now(),
  lastReportAt: 0,
  // Device-side scan rate derived from the firmware's own microsecond
  // timestamps (not measured/estimated by the browser), so this number is
  // directly comparable to tools/megknob_hall_viewer.py's "device_scan_hz".
  lastRawTimestampUs: null,
  lastDataTimestampUs: null,
  periodSumUs: 0,
  periodCount: 0,
  deviceWrapBase: 0,
};

function appendBytes(chunk) {
  const merged = new Uint8Array(buffer.length + chunk.length);
  merged.set(buffer, 0);
  merged.set(chunk, buffer.length);
  buffer = merged;
  metrics.bytes += chunk.length;
}

function findMagic(from) {
  for (let i = from; i + 1 < buffer.length; i++) {
    if (buffer[i] === MAGIC0 && buffer[i + 1] === MAGIC1) {
      return i;
    }
  }
  return -1;
}

function decodeFrames() {
  const decoded = [];

  while (true) {
    const start = findMagic(0);
    if (start < 0) {
      // Keep the last byte in case it is the first half of a future magic.
      if (buffer.length > 1) {
        buffer = buffer.slice(buffer.length - 1);
      }
      break;
    }

    if (start > 0) {
      buffer = buffer.slice(start);
    }

    if (buffer.length < FRAME_SIZE) {
      break;
    }

    const view = new DataView(buffer.buffer, buffer.byteOffset, FRAME_SIZE);
    const version = view.getUint8(2);
    const receivedCrc = view.getUint16(60, true);
    const computedCrc = crc16(buffer, 60);

    if (version !== PROTOCOL_VERSION || receivedCrc !== computedCrc) {
      metrics.crcErrors++;
      // Advance by one byte and keep looking, matching the Python
      // implementation's resync-on-CRC-failure behavior.
      buffer = buffer.slice(1);
      continue;
    }

    const type = view.getUint8(3);
    const mode = view.getUint8(4);
    const count = view.getUint8(5);
    const seq = view.getUint16(6, true);
    const timestampUs = view.getUint32(8, true);

    const samples = new Array(24);
    for (let i = 0; i < 24; i++) {
      samples[i] = view.getUint16(12 + i * 2, true);
    }

    buffer = buffer.slice(FRAME_SIZE);

    metrics.frames++;
    if (metrics.lastSeq !== null) {
      const gap = (seq - metrics.lastSeq) & 0xffff;
      if (gap > 1 && gap < 0x8000) {
        metrics.lostFrames += gap - 1;
      }
    }
    metrics.lastSeq = seq;

    if (type === TYPE_DATA) {
      metrics.dataFrames++;

      // uint32 microsecond timestamp wraps every ~71.6 minutes; unwrap it
      // into an effectively unbounded host-side timeline, same approach as
      // tools/megknob_hall_viewer.py's Metrics.add_frame(), then track the
      // inter-frame period so we can report a real device scan rate derived
      // from firmware timestamps (not a browser-side estimate).
      if (
        metrics.lastRawTimestampUs !== null &&
        timestampUs < metrics.lastRawTimestampUs
      ) {
        metrics.deviceWrapBase += 2 ** 32;
      }
      const unwrappedUs = metrics.deviceWrapBase + timestampUs;

      if (metrics.lastDataTimestampUs !== null) {
        const deltaUs = unwrappedUs - metrics.lastDataTimestampUs;
        if (deltaUs > 0 && deltaUs < 1_000_000) {
          metrics.periodSumUs += deltaUs;
          metrics.periodCount++;
        }
      }

      metrics.lastRawTimestampUs = timestampUs;
      metrics.lastDataTimestampUs = unwrappedUs;
    }

    decoded.push({ type, mode, count, seq, timestampUs, samples });
  }

  return decoded;
}

self.onmessage = (event) => {
  const { kind, payload } = event.data;

  if (kind === "bytes") {
    appendBytes(new Uint8Array(payload));
    const frames = decodeFrames();

    const now = performance.now();
    if (frames.length > 0 || now - metrics.lastReportAt > 250) {
      metrics.lastReportAt = now;
      const elapsedS = Math.max((now - metrics.startedAt) / 1000, 1e-6);
      const meanPeriodUs =
        metrics.periodCount > 0 ? metrics.periodSumUs / metrics.periodCount : 0;
      self.postMessage({
        kind: "frames",
        frames,
        metrics: {
          frames: metrics.frames,
          dataFrames: metrics.dataFrames,
          crcErrors: metrics.crcErrors,
          lostFrames: metrics.lostFrames,
          bytes: metrics.bytes,
          hostReceiveHz: metrics.dataFrames / elapsedS,
          throughputBytesPerS: metrics.bytes / elapsedS,
          deviceScanHz: meanPeriodUs > 0 ? 1_000_000 / meanPeriodUs : 0,
        },
      });
    }
  } else if (kind === "reset") {
    buffer = new Uint8Array(0);
    metrics.frames = 0;
    metrics.dataFrames = 0;
    metrics.crcErrors = 0;
    metrics.lostFrames = 0;
    metrics.bytes = 0;
    metrics.lastSeq = null;
    metrics.startedAt = performance.now();
    metrics.lastReportAt = 0;
    metrics.lastRawTimestampUs = null;
    metrics.lastDataTimestampUs = null;
    metrics.periodSumUs = 0;
    metrics.periodCount = 0;
    metrics.deviceWrapBase = 0;
  }
};
