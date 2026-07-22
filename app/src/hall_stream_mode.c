/* SPDX-License-Identifier: MIT */

#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>
#include <zmk/hall_stream.h>

static int hall_stream_mode_listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);

    if (ev != NULL && ev->state) {
        (void)zmk_hall_stream_cycle_mode(ev->position);
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(hall_stream_mode, hall_stream_mode_listener);
ZMK_SUBSCRIPTION(hall_stream_mode, zmk_position_state_changed);
