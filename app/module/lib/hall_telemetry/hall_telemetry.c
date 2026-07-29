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
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <zmk/hall_telemetry.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define HALL_TELEMETRY_UART_NODE DT_CHOSEN(zmk_hall_telemetry_uart)

BUILD_ASSERT(DT_NODE_HAS_STATUS(HALL_TELEMETRY_UART_NODE, okay),
             "zmk,hall-telemetry-uart chosen node must exist and be okay");

/* Wire format: little-endian 62-byte frames, `MK` magic, protocol version 3. Data and performance
 * frames both carry 24 uint16 payload slots; performance frames only
 * populate the first 4 (scan/address/adc/process microseconds) and zero the
 * rest, matching tools/megknob_hall_viewer.py's `FRAME = Struct("<2sBBBBHI24HH")`
 * and `if kind == 3 and count >= 4: metrics.add_perf(values)` handling. */
#define HALL_TELEMETRY_MAGIC0 'M'
#define HALL_TELEMETRY_MAGIC1 'K'
#define HALL_TELEMETRY_VERSION 3

#define HALL_TELEMETRY_TYPE_DATA 1
#define HALL_TELEMETRY_TYPE_MODE 2
#define HALL_TELEMETRY_TYPE_PERF 3

#define HALL_TELEMETRY_PERF_SAMPLE_COUNT 4

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

/* Pending-frame queue entry. Kept separate from the wire frame so the
 * producer side (kscan_adc_mux scan loop) never has to know about
 * CRC/byte-order and so we can keep this struct tightly packed for the
 * message queue without __packed alignment surprises. */
struct hall_telemetry_item {
    uint8_t type;
    uint8_t mode;
    uint8_t count;
    uint16_t data[HALL_TELEMETRY_CHANNELS];
};

static const struct device *const hall_telemetry_uart = DEVICE_DT_GET(HALL_TELEMETRY_UART_NODE);

K_MSGQ_DEFINE(hall_telemetry_queue, sizeof(struct hall_telemetry_item),
             CONFIG_HALL_TELEMETRY_QUEUE_DEPTH, 4);

static uint16_t hall_telemetry_seq;
static uint32_t hall_telemetry_scan_count;

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
        crc = (uint16_t)((crc << 4) ^ hall_telemetry_crc_nibble_table[((crc >> 12) ^ (data[i] >> 4)) & 0xF]);
        crc = (uint16_t)((crc << 4) ^ hall_telemetry_crc_nibble_table[((crc >> 12) ^ (data[i] & 0xF)) & 0xF]);
    }

    return crc;
}

static void hall_telemetry_send_frame(const struct hall_telemetry_item *item) {
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

    return 0;
}

SYS_INIT(hall_telemetry_init, POST_KERNEL, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);
