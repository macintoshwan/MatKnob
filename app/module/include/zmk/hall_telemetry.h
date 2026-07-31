/*
 * Copyright (c) 2026 The ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/sys/util.h>

/**
 * Number of Hall/ADC channels carried in a single telemetry data frame. This
 * matches the MegKnob 24-channel layout (3x 74HC4051 x 8 channels) and the
 * protocol v3 wire format.
 */
#define HALL_TELEMETRY_CHANNELS 24

/**
 * Submits one scan's worth of Hall channel voltages (millivolts) to the
 * telemetry link, if a hall-telemetry-uart device is present and enabled in
 * the build. If the telemetry driver is not compiled in (CONFIG_HALL_TELEMETRY
 * disabled, e.g. any non-MegKnob board), this is a no-op inline function that
 * compiles away to nothing, so callers do not need to guard every call site
 * with #if.
 *
 * This function must be safe to call from the same context as the kscan scan
 * loop: it only copies data into a bounded queue (K_NO_WAIT, drops the
 * oldest entry if full) and never blocks, sleeps, or touches USB/UART
 * directly. The actual CDC ACM transmission happens on a separate,
 * K_LOWEST_APPLICATION_THREAD_PRIO thread so a slow or disconnected USB host
 * cannot stall Hall scanning, HID reporting, or the BLE stack.
 *
 * @param mode Viewer mode byte forwarded as-is in the wire frame (0-3);
 *             callers that have no concept of "mode" should
 *             pass 3 (ALL channels).
 * @param sample_mv Array of HALL_TELEMETRY_CHANNELS millivolt readings, in
 *                   U26 Y0..Y7, U27 Y0..Y7, U28 Y0..Y7 order.
 */
#if IS_ENABLED(CONFIG_HALL_TELEMETRY)
void hall_telemetry_submit(uint8_t mode, const int32_t sample_mv[HALL_TELEMETRY_CHANNELS]);

/**
 * Reads the currently active per-key press/release thresholds for one channel,
 * if a per-key calibration has been downloaded from the web configurator (see
 * the Issue D command protocol). kscan drivers call this per key and fall back
 * to their devicetree-global defaults when it returns false (no calibration
 * applied yet, or thresholds were reset to defaults).
 *
 * @param channel    Channel index 0..HALL_TELEMETRY_CHANNELS-1, matching the
 *                   kscan key index and the telemetry frame's channel order.
 * @param press_mv   Output: press threshold in millivolts.
 * @param release_mv Output: release threshold in millivolts.
 * @return true if per-key thresholds are active and were written to the
 *         outputs; false to use the devicetree defaults instead.
 */
bool hall_telemetry_get_thresholds(uint8_t channel, int32_t *press_mv, int32_t *release_mv);
#else
static inline void hall_telemetry_submit(uint8_t mode,
                                         const int32_t sample_mv[HALL_TELEMETRY_CHANNELS]) {
    ARG_UNUSED(mode);
    ARG_UNUSED(sample_mv);
}

static inline bool hall_telemetry_get_thresholds(uint8_t channel, int32_t *press_mv,
                                                 int32_t *release_mv) {
    ARG_UNUSED(channel);
    ARG_UNUSED(press_mv);
    ARG_UNUSED(release_mv);
    return false;
}
#endif
