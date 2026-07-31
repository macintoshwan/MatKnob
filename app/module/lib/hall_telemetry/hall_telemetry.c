/*
 * Copyright (c) 2026 The ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <zmk/hall_telemetry.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define HALL_TELEMETRY_UART_NODE DT_CHOSEN(zmk_hall_telemetry_uart)

BUILD_ASSERT(DT_NODE_HAS_STATUS(HALL_TELEMETRY_UART_NODE, okay),
             "zmk,hall-telemetry-uart chosen node must exist and be okay");

/* Telemetry data frames (device -> host): little-endian 62-byte frames, `MK`
 * magic, protocol version 3. Data and performance frames both carry 24 uint16
 * payload slots; performance frames only populate the first 4 (scan/address/
 * adc/process microseconds) and zero the rest, matching
 * tools/megknob_hall_viewer.py's `FRAME = Struct("<2sBBBBHI24HH")` and
 * `if kind == 3 and count >= 4: metrics.add_perf(values)` handling. */
#define HALL_TELEMETRY_MAGIC0 'M'
#define HALL_TELEMETRY_MAGIC1 'K'
#define HALL_TELEMETRY_VERSION 3

#define HALL_TELEMETRY_TYPE_DATA 1
#define HALL_TELEMETRY_TYPE_MODE 2
#define HALL_TELEMETRY_TYPE_PERF 3

#define HALL_TELEMETRY_PERF_SAMPLE_COUNT 4

/* Command frames (host -> device): `MK` magic + version + type=0x10 + cmd +
 * len + payload(len) + crc16 (see tools/megknob_web_configurator/app.js's
 * buildSetThresholdsFrame()). */
#define HALL_CMD_TYPE 0x10
/* Ack frames (device -> host): distinct `AK` magic so the web/Python frame
 * parser (which resyncs on `MK` 62-byte data frames) skips them instead of
 * misreading an 8-byte ack as telemetry. type=0x11. */
#define HALL_ACK_MAGIC0 'A'
#define HALL_ACK_MAGIC1 'K'
#define HALL_ACK_TYPE 0x11

/* Command opcodes. */
#define HALL_CMD_SET_THRESHOLDS 0x01
#define HALL_CMD_GET_THRESHOLDS 0x02
#define HALL_CMD_SAVE_NVS 0x03
#define HALL_CMD_RESET_DEFAULTS 0x04

/* Ack status codes. */
#define HALL_ACK_OK 0x00
#define HALL_ACK_ERR_BAD_LEN 0x01
#define HALL_ACK_ERR_NO_DATA 0x02
#define HALL_ACK_ERR_SAVE 0x03
#define HALL_ACK_ERR_UNSUPPORTED 0xfe
#define HALL_ACK_ERR_UNKNOWN_CMD 0xff

struct hall_telemetry_wire_frame {
    uint8_t magic[2];
    uint8_t version;
    uint8_t type;
    uint8_t mode;
    uint8_t count;
    uint16_t seq;
    uint32_t timestamp_us;
    uint16_t data[HALL_TELEMETRY_CHANNELS];
    uint16_t crc;
} __packed;

BUILD_ASSERT(sizeof(struct hall_telemetry_wire_frame) == 62,
             "hall telemetry wire frame must stay 62 bytes to match "
             "tools/megknob_hall_viewer.py");

/* Pending-frame queue entry. Kept separate from the wire frame so the producer
 * side (kscan_adc_mux scan loop) never has to know about CRC/byte-order. A
 * single queue carries both telemetry data frames and command acks so the UART
 * is only ever written by the one TX thread below (no cross-thread interleave). */
struct hall_telemetry_item {
    bool is_ack;
    uint8_t type;
    uint8_t mode;
    uint8_t count;
    uint16_t data[HALL_TELEMETRY_CHANNELS];
    uint8_t ack_cmd;
    uint8_t ack_status;
};

static const struct device *const hall_telemetry_uart = DEVICE_DT_GET(HALL_TELEMETRY_UART_NODE);

K_MSGQ_DEFINE(hall_telemetry_queue, sizeof(struct hall_telemetry_item),
              CONFIG_HALL_TELEMETRY_QUEUE_DEPTH, 4);

static uint16_t hall_telemetry_seq;
static uint32_t hall_telemetry_scan_count;

/* --- Per-key thresholds (Issue D) -----------------------------------------
 * Overrides the DT-global press/release thresholds in kscan_adc_mux once the
 * web configurator downloads a per-key calibration. Until then
 * hall_thresholds_valid is false and kscan falls back to the DT defaults. */
struct hall_thresholds {
    int32_t press[HALL_TELEMETRY_CHANNELS];
    int32_t release[HALL_TELEMETRY_CHANNELS];
};

static struct hall_thresholds hall_thresholds;
static bool hall_thresholds_valid;

bool hall_telemetry_get_thresholds(uint8_t channel, int32_t *press_mv, int32_t *release_mv) {
    if (!hall_thresholds_valid || channel >= HALL_TELEMETRY_CHANNELS) {
        return false;
    }
    *press_mv = hall_thresholds.press[channel];
    *release_mv = hall_thresholds.release[channel];
    return true;
}

/* CRC-16/CCITT-FALSE, 16-entry nibble lookup table, matching the algorithm
 * described in the 2026-07-20 dev log entry and tools/megknob_hall_viewer.py's
 * crc16(). */
static const uint16_t hall_telemetry_crc_nibble_table[16] = {
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
};

static uint16_t hall_telemetry_crc16(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;

    for (size_t i = 0; i < len; i++) {
        crc = (uint16_t)((crc << 4) ^
                         hall_telemetry_crc_nibble_table[((crc >> 12) ^ (data[i] >> 4)) & 0xF]);
        crc = (uint16_t)((crc << 4) ^
                         hall_telemetry_crc_nibble_table[((crc >> 12) ^ (data[i] & 0xF)) & 0xF]);
    }

    return crc;
}

/* --- Persistence (settings/NVS) ------------------------------------------- */
#if IS_ENABLED(CONFIG_SETTINGS)
#define HALL_SETTINGS_SUBTREE "hall"
#define HALL_SETTINGS_THRESHOLDS_KEY "hall/thresholds"

static int hall_settings_set(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    if (strcmp(name, "thresholds") != 0) {
        return -ENOENT;
    }
    if (len != sizeof(hall_thresholds)) {
        return -EINVAL;
    }
    ssize_t rc = read_cb(cb_arg, &hall_thresholds, len);
    if (rc < 0) {
        return (int)rc;
    }
    hall_thresholds_valid = (rc == (ssize_t)len);
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(hall_telemetry, HALL_SETTINGS_SUBTREE, NULL, hall_settings_set, NULL,
                               NULL);

static int hall_thresholds_save(void) {
    return settings_save_one(HALL_SETTINGS_THRESHOLDS_KEY, &hall_thresholds,
                             sizeof(hall_thresholds));
}

static void hall_thresholds_delete_nvs(void) { settings_delete(HALL_SETTINGS_THRESHOLDS_KEY); }
#else
static int hall_thresholds_save(void) { return -ENOTSUP; }
static void hall_thresholds_delete_nvs(void) {}
#endif /* IS_ENABLED(CONFIG_SETTINGS) */

/* --- Command handling + ack ----------------------------------------------- */
static void hall_cmd_send_ack(uint8_t cmd, uint8_t status) {
    struct hall_telemetry_item item = {
        .is_ack = true,
        .ack_cmd = cmd,
        .ack_status = status,
    };
    /* Acks are best-effort: if the queue is momentarily full of telemetry we
     * drop the ack rather than the command's effect already applied above. */
    (void)k_msgq_put(&hall_telemetry_queue, &item, K_NO_WAIT);
}

static void hall_cmd_handle(uint8_t cmd, const uint8_t *payload, uint8_t len) {
    uint8_t status = HALL_ACK_OK;

    switch (cmd) {
    case HALL_CMD_SET_THRESHOLDS:
        if (len != HALL_TELEMETRY_CHANNELS * 4) {
            status = HALL_ACK_ERR_BAD_LEN;
            break;
        }
        for (uint8_t i = 0; i < HALL_TELEMETRY_CHANNELS; i++) {
            hall_thresholds.press[i] = (int32_t)sys_get_le16(&payload[i * 4]);
            hall_thresholds.release[i] = (int32_t)sys_get_le16(&payload[i * 4 + 2]);
        }
        hall_thresholds_valid = true;
        LOG_INF("applied per-key thresholds for %u channels", HALL_TELEMETRY_CHANNELS);
        break;

    case HALL_CMD_SAVE_NVS:
        if (!hall_thresholds_valid) {
            status = HALL_ACK_ERR_NO_DATA;
            break;
        }
        status = (hall_thresholds_save() == 0) ? HALL_ACK_OK : HALL_ACK_ERR_SAVE;
        break;

    case HALL_CMD_RESET_DEFAULTS:
        hall_thresholds_valid = false;
        hall_thresholds_delete_nvs();
        LOG_INF("reset thresholds to DT defaults");
        break;

    case HALL_CMD_GET_THRESHOLDS:
        status = HALL_ACK_ERR_UNSUPPORTED; /* read-back left for a follow-up */
        break;

    default:
        status = HALL_ACK_ERR_UNKNOWN_CMD;
        break;
    }

    hall_cmd_send_ack(cmd, status);
}

/* --- Command frame parser (byte-at-a-time state machine) ------------------- */
#define HALL_CMD_RX_BUF_SIZE (6 + HALL_TELEMETRY_CHANNELS * 4 + 2)

static uint8_t hall_cmd_rx_buf[HALL_CMD_RX_BUF_SIZE];
static size_t hall_cmd_rx_len;

static void hall_cmd_feed_byte(uint8_t b) {
    /* Resync on the `MK` magic. */
    if (hall_cmd_rx_len == 0) {
        if (b == HALL_TELEMETRY_MAGIC0) {
            hall_cmd_rx_buf[hall_cmd_rx_len++] = b;
        }
        return;
    }
    if (hall_cmd_rx_len == 1) {
        if (b == HALL_TELEMETRY_MAGIC1) {
            hall_cmd_rx_buf[hall_cmd_rx_len++] = b;
        } else {
            hall_cmd_rx_len = 0;
            if (b == HALL_TELEMETRY_MAGIC0) {
                hall_cmd_rx_buf[hall_cmd_rx_len++] = b;
            }
        }
        return;
    }

    hall_cmd_rx_buf[hall_cmd_rx_len++] = b;
    if (hall_cmd_rx_len < 6) {
        return;
    }

    uint8_t payload_len = hall_cmd_rx_buf[5];
    size_t total = 6 + payload_len + 2;
    if (total > sizeof(hall_cmd_rx_buf)) {
        /* Implausible length: drop and resync. */
        hall_cmd_rx_len = 0;
        return;
    }
    if (hall_cmd_rx_len < total) {
        return;
    }

    uint8_t version = hall_cmd_rx_buf[2];
    uint8_t type = hall_cmd_rx_buf[3];
    uint8_t cmd = hall_cmd_rx_buf[4];
    uint16_t crc_recv = sys_get_le16(&hall_cmd_rx_buf[total - 2]);
    uint16_t crc_calc = hall_telemetry_crc16(hall_cmd_rx_buf, total - 2);

    if (version == HALL_TELEMETRY_VERSION && type == HALL_CMD_TYPE && crc_recv == crc_calc) {
        hall_cmd_handle(cmd, &hall_cmd_rx_buf[6], payload_len);
    } else {
        LOG_WRN("cmd frame rejected (ver=%u type=%u crc %04x!=%04x)", version, type, crc_recv,
                crc_calc);
    }

    hall_cmd_rx_len = 0;
}

/* --- RX thread: commands are rare and tiny, so a low-priority poll loop is
 * enough and keeps the UART read side completely off the HID/BLE path. */
static void hall_cmd_rx_worker(void *p1, void *p2, void *p3) {
    ARG_UNUSED(p1);
    ARG_UNUSED(p2);
    ARG_UNUSED(p3);

    uint8_t b;
    while (true) {
        if (!device_is_ready(hall_telemetry_uart)) {
            k_msleep(100);
            continue;
        }
        if (uart_poll_in(hall_telemetry_uart, &b) == 0) {
            hall_cmd_feed_byte(b);
        } else {
            k_msleep(2);
        }
    }
}

K_THREAD_DEFINE(hall_cmd_rx_thread, 1024, hall_cmd_rx_worker, NULL, NULL, NULL,
                K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);

/* --- TX path: a single thread writes the UART for both data + ack frames --- */
static void hall_telemetry_send_ack_frame(uint8_t cmd, uint8_t status) {
    uint8_t ack[8] = {
        HALL_ACK_MAGIC0, HALL_ACK_MAGIC1, HALL_TELEMETRY_VERSION, HALL_ACK_TYPE, cmd, status, 0, 0,
    };
    uint16_t crc = hall_telemetry_crc16(ack, 6);
    ack[6] = crc & 0xff;
    ack[7] = (crc >> 8) & 0xff;

    for (size_t i = 0; i < sizeof(ack); i++) {
        uart_poll_out(hall_telemetry_uart, ack[i]);
    }
}

static void hall_telemetry_send_frame(const struct hall_telemetry_item *item) {
    if (item->is_ack) {
        hall_telemetry_send_ack_frame(item->ack_cmd, item->ack_status);
        return;
    }

    struct hall_telemetry_wire_frame frame = {
        .magic = {HALL_TELEMETRY_MAGIC0, HALL_TELEMETRY_MAGIC1},
        .version = HALL_TELEMETRY_VERSION,
        .type = item->type,
        .mode = item->mode,
        .count = item->count,
        .seq = sys_cpu_to_le16(hall_telemetry_seq++),
        .timestamp_us = sys_cpu_to_le32((uint32_t)k_ticks_to_us_floor64(k_uptime_ticks())),
    };

    for (size_t i = 0; i < HALL_TELEMETRY_CHANNELS; i++) {
        frame.data[i] = sys_cpu_to_le16(item->data[i]);
    }

    uint16_t crc = hall_telemetry_crc16((const uint8_t *)&frame, sizeof(frame) - sizeof(frame.crc));
    frame.crc = sys_cpu_to_le16(crc);

    /* uart_poll_out is fine here: this thread is the lowest-priority
     * application thread and is the only writer, and CDC ACM already has a
     * ring buffer underneath (see the 2026-07-20 CDC batch send optimization
     * log entry for why byte-at-a-time poll writes were previously the
     * bottleneck at >800 fps -- at the reduced, best-effort telemetry rate
     * used here that tradeoff is intentionally simple over maximally fast). */
    const uint8_t *bytes = (const uint8_t *)&frame;
    for (size_t i = 0; i < sizeof(frame); i++) {
        uart_poll_out(hall_telemetry_uart, bytes[i]);
    }
}

static void hall_telemetry_worker(void *p1, void *p2, void *p3) {
    ARG_UNUSED(p1);
    ARG_UNUSED(p2);
    ARG_UNUSED(p3);

    struct hall_telemetry_item item;

    while (true) {
        if (k_msgq_get(&hall_telemetry_queue, &item, K_FOREVER) == 0) {
            hall_telemetry_send_frame(&item);
        }
    }
}

K_THREAD_DEFINE(hall_telemetry_thread, 1024, hall_telemetry_worker, NULL, NULL, NULL,
                K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);

static void hall_telemetry_enqueue(const struct hall_telemetry_item *item) {
    /* K_NO_WAIT + drop-oldest-on-full: telemetry must never apply backpressure
     * to the caller (the Hall scan loop). If the USB host is slow, absent, or
     * disconnected, the queue fills up and we discard the oldest pending
     * frame to make room, rather than blocking or discarding the new one --
     * this matches the "always show the most recent signal" behavior the
     * Python viewer already assumes (see its own bounded `pending` deque). */
    if (k_msgq_put(&hall_telemetry_queue, item, K_NO_WAIT) == 0) {
        return;
    }

    struct hall_telemetry_item discarded;
    (void)k_msgq_get(&hall_telemetry_queue, &discarded, K_NO_WAIT);
    (void)k_msgq_put(&hall_telemetry_queue, item, K_NO_WAIT);
}

void hall_telemetry_submit(uint8_t mode, const int32_t sample_mv[HALL_TELEMETRY_CHANNELS]) {
    if (!device_is_ready(hall_telemetry_uart)) {
        return;
    }

    struct hall_telemetry_item item = {
        .is_ack = false,
        .type = HALL_TELEMETRY_TYPE_DATA,
        .mode = mode,
        .count = HALL_TELEMETRY_CHANNELS,
    };

    for (size_t i = 0; i < HALL_TELEMETRY_CHANNELS; i++) {
        int32_t clamped = CLAMP(sample_mv[i], 0, UINT16_MAX);
        item.data[i] = (uint16_t)clamped;
    }

    hall_telemetry_enqueue(&item);

    hall_telemetry_scan_count++;
    if (hall_telemetry_scan_count >= CONFIG_HALL_TELEMETRY_PERF_FRAME_INTERVAL) {
        hall_telemetry_scan_count = 0;
        /* Perf timing instrumentation (scan/address/adc/process us) is not
         * wired up to a producer yet in this pass -- emit a zeroed perf
         * frame so protocol framing/cadence matches the Python viewer's
         * expectations without claiming numbers we have not
         * actually measured on this build. */
        struct hall_telemetry_item perf_item = {
            .is_ack = false,
            .type = HALL_TELEMETRY_TYPE_PERF,
            .mode = mode,
            .count = HALL_TELEMETRY_PERF_SAMPLE_COUNT,
        };
        hall_telemetry_enqueue(&perf_item);
    }
}

static int hall_telemetry_init(void) {
    if (!device_is_ready(hall_telemetry_uart)) {
        LOG_ERR("hall telemetry uart not ready");
        return -ENODEV;
    }

#if IS_ENABLED(CONFIG_SETTINGS)
    /* Load any previously saved per-key thresholds so a calibrated board keeps
     * its thresholds across power cycles. */
    (void)settings_load_subtree(HALL_SETTINGS_SUBTREE);
#endif

    return 0;
}

SYS_INIT(hall_telemetry_init, POST_KERNEL, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);
