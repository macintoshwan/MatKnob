/*
 * Copyright (c) 2026 The ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

#include <stdio.h>

#include <lvgl.h>
#include <zephyr/kernel.h>

#include <zmk/battery.h>
#include <zmk/ble.h>
#include <zmk/display.h>
#include <zmk/endpoints.h>
#include <zmk/event_manager.h>
#include <zmk/events/ble_active_profile_changed.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/events/endpoint_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/events/wpm_state_changed.h>
#include <zmk/keymap.h>
#include <zmk/wpm.h>

struct megknob_status_state {
    zmk_keymap_layer_index_t layer;
    enum zmk_transport selected_transport;
    enum zmk_transport preferred_transport;
    uint8_t profile;
    bool ble_connected;
    uint8_t battery_percent;
    uint8_t wpm;
};

static lv_obj_t *status_label;

static void megknob_status_update_work_cb(struct k_work *work);
K_WORK_DEFINE(megknob_status_update_work, megknob_status_update_work_cb);

static struct megknob_status_state megknob_status_get_state(void) {
    const struct zmk_endpoint_instance endpoint = zmk_endpoint_get_selected();
    const enum zmk_transport selected_transport = endpoint.transport;

    return (struct megknob_status_state){
        .layer = zmk_keymap_highest_layer_active(),
        .selected_transport = selected_transport,
        .preferred_transport = zmk_endpoint_get_preferred_transport(),
        .profile = selected_transport == ZMK_TRANSPORT_BLE ? endpoint.ble.profile_index + 1
                                                           : zmk_ble_active_profile_index() + 1,
        .ble_connected = zmk_ble_active_profile_is_connected(),
        .battery_percent = zmk_battery_state_of_charge(),
        .wpm = zmk_wpm_get_state(),
    };
}

static void megknob_status_update_work_cb(struct k_work *work) {
    ARG_UNUSED(work);

    if (status_label == NULL) {
        return;
    }

    const struct megknob_status_state state = megknob_status_get_state();
    const char *transport;
    const char *connection;

    if (state.selected_transport == ZMK_TRANSPORT_USB) {
        transport = "USB";
        connection = "OK";
    } else if (state.selected_transport == ZMK_TRANSPORT_BLE ||
               state.preferred_transport == ZMK_TRANSPORT_BLE) {
        transport = "BLE";
        connection = state.ble_connected ? "OK" : "--";
    } else {
        transport = "OFF";
        connection = "--";
    }

    char text[48];
    snprintf(text, sizeof(text), "%-3s P%u %-2s\nL%u BAT:%3u%% %3uWPM", transport, state.profile,
             connection, state.layer, state.battery_percent, state.wpm);
    lv_label_set_text(status_label, text);
}

static int megknob_status_listener(const zmk_event_t *eh) {
    ARG_UNUSED(eh);

    if (zmk_display_is_initialized()) {
        k_work_submit_to_queue(zmk_display_work_q(), &megknob_status_update_work);
    }

    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(megknob_status, megknob_status_listener);
ZMK_SUBSCRIPTION(megknob_status, zmk_layer_state_changed);
ZMK_SUBSCRIPTION(megknob_status, zmk_endpoint_changed);
ZMK_SUBSCRIPTION(megknob_status, zmk_ble_active_profile_changed);
ZMK_SUBSCRIPTION(megknob_status, zmk_battery_state_changed);
ZMK_SUBSCRIPTION(megknob_status, zmk_wpm_state_changed);

lv_obj_t *zmk_display_status_screen(void) {
    lv_obj_t *screen = lv_obj_create(NULL);

    status_label = lv_label_create(screen);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_12, LV_PART_MAIN);
    lv_obj_align(status_label, LV_ALIGN_CENTER, 0, 0);
    megknob_status_update_work_cb(NULL);

    return screen;
}
