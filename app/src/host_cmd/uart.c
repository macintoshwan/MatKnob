/*
 * Copyright (c) 2026 The ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/endpoints.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/hid.h>

#include <dt-bindings/zmk/hid_usage_pages.h>
#include <dt-bindings/zmk/keys.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define HOST_CMD_UART_NODE DT_CHOSEN(zmk_host_cmd_uart)

BUILD_ASSERT(DT_NODE_HAS_STATUS(HOST_CMD_UART_NODE, okay),
             "zmk,host-cmd-uart chosen node must exist and be okay");

static const struct device *const uart_dev = DEVICE_DT_GET(HOST_CMD_UART_NODE);

K_MSGQ_DEFINE(host_cmd_queue, CONFIG_ZMK_HOST_CMD_LINE_MAX_LEN, CONFIG_ZMK_HOST_CMD_QUEUE_DEPTH, 4);

static char rx_line[CONFIG_ZMK_HOST_CMD_LINE_MAX_LEN];
static size_t rx_len;
static struct k_work_delayable host_cmd_failsafe_work;

static int send_ack(const char *msg) {
    for (size_t i = 0; msg[i] != '\0'; i++) {
        uart_poll_out(uart_dev, (unsigned char)msg[i]);
    }
    uart_poll_out(uart_dev, '\r');
    uart_poll_out(uart_dev, '\n');
    return 0;
}

static int inject_key(uint32_t code, bool pressed) {
    return raise_zmk_keycode_state_changed_from_encoded(code, pressed, k_uptime_get());
}

static void release_all_inputs(void) {
    zmk_hid_keyboard_clear();
    zmk_hid_consumer_clear();
    (void)zmk_endpoint_send_report(HID_USAGE_KEY);
    (void)zmk_endpoint_send_report(HID_USAGE_CONSUMER);

#if IS_ENABLED(CONFIG_ZMK_POINTING)
    zmk_hid_mouse_clear();
    (void)zmk_endpoint_send_mouse_report();
#endif
}

static void host_cmd_failsafe_handler(struct k_work *work) {
    ARG_UNUSED(work);
    release_all_inputs();
    LOG_WRN("host command failsafe triggered: all inputs released");
}

static inline void reset_failsafe_timer(void) {
    (void)k_work_reschedule(&host_cmd_failsafe_work,
                            K_MSEC(CONFIG_ZMK_HOST_CMD_FAILSAFE_TIMEOUT_MS));
}

#if IS_ENABLED(CONFIG_ZMK_POINTING)
static int send_mouse_report_now(void) { return zmk_endpoint_send_mouse_report(); }

static int parse_button(const char *token, zmk_mouse_button_t *button) {
    if (token == NULL || token[0] == '\0' || token[1] != '\0') {
        return -EINVAL;
    }

    switch (toupper((unsigned char)token[0])) {
    case 'L':
        *button = 0;
        return 0;
    case 'R':
        *button = 1;
        return 0;
    case 'M':
        *button = 2;
        return 0;
    default:
        return -EINVAL;
    }
}

static int mouse_button_down(zmk_mouse_button_t button) {
    int err = zmk_hid_mouse_button_press(button);
    if (err < 0) {
        return err;
    }
    return send_mouse_report_now();
}

static int mouse_button_up(zmk_mouse_button_t button) {
    int err = zmk_hid_mouse_button_release(button);
    if (err < 0) {
        return err;
    }
    return send_mouse_report_now();
}

static int mouse_button_click(zmk_mouse_button_t button) {
    int err = mouse_button_down(button);
    if (err < 0) {
        return err;
    }

    if (CONFIG_ZMK_HOST_CMD_CLICK_DELAY_MS > 0) {
        k_msleep(CONFIG_ZMK_HOST_CMD_CLICK_DELAY_MS);
    }

    return mouse_button_up(button);
}

static int mouse_move_relative(int16_t x, int16_t y) {
    zmk_hid_mouse_movement_set(x, y);
    int err = send_mouse_report_now();
    zmk_hid_mouse_movement_set(0, 0);
    return err;
}
#endif

static void trim_spaces(char *line) {
    size_t start = 0;
    while (line[start] != '\0' && isspace((unsigned char)line[start])) {
        start++;
    }

    if (start > 0) {
        memmove(line, line + start, strlen(line + start) + 1);
    }

    size_t len = strlen(line);
    while (len > 0 && isspace((unsigned char)line[len - 1])) {
        line[len - 1] = '\0';
        len--;
    }
}

static int split_tokens(char *line, char **tokens, size_t max_tokens) {
    size_t count = 0;
    char *p = line;

    if (line[0] == '\0') {
        return 0;
    }

    tokens[count++] = p;
    while (*p != '\0') {
        if (*p == ':') {
            *p = '\0';
            if (count >= max_tokens) {
                return -EINVAL;
            }
            tokens[count++] = p + 1;
        }
        p++;
    }

    return (int)count;
}

static int parse_hex_usage_id(const char *token, uint32_t *encoded_usage) {
    if (token == NULL || *token == '\0') {
        return -EINVAL;
    }

    char *endptr = NULL;
    unsigned long value = strtoul(token, &endptr, 16);
    if (*endptr != '\0' || value > 0xFFUL) {
        return -EINVAL;
    }

    *encoded_usage = ZMK_HID_USAGE(HID_USAGE_KEY, (uint32_t)value);
    return 0;
}

static int parse_i16(const char *token, int16_t *out) {
    if (token == NULL || *token == '\0') {
        return -EINVAL;
    }

    char *endptr = NULL;
    long v = strtol(token, &endptr, 10);
    if (*endptr != '\0' || v < INT16_MIN || v > INT16_MAX) {
        return -EINVAL;
    }

    *out = (int16_t)v;
    return 0;
}

static int process_line(char *line) {
    char *tokens[4] = {0};

    trim_spaces(line);
    if (line[0] == '\0') {
        return 0;
    }

    int count = split_tokens(line, tokens, ARRAY_SIZE(tokens));
    if (count < 2) {
        send_ack("ERR FORMAT");
        return -EINVAL;
    }

    char module = (char)toupper((unsigned char)tokens[0][0]);
    char command = (char)toupper((unsigned char)tokens[1][0]);

    if (module == 'S' && command == 'P' && count == 2) {
        reset_failsafe_timer();
        send_ack("PONG");
        return 0;
    }

    if (module == 'K') {
        int err = -EINVAL;
        if (command == 'A' && count == 2) {
            release_all_inputs();
            err = 0;
        } else if ((command == 'D' || command == 'U') && count == 3) {
            uint32_t usage;
            err = parse_hex_usage_id(tokens[2], &usage);
            if (err == 0) {
                err = inject_key(usage, command == 'D');
            }
        }

        if (err == 0) {
            reset_failsafe_timer();
            send_ack("OK K");
        } else {
            send_ack("ERR K");
        }
        return err;
    }

    if (module == 'M') {
#if IS_ENABLED(CONFIG_ZMK_POINTING)
        int err = -EINVAL;
        if (command == 'R' && count == 4) {
            int16_t x = 0;
            int16_t y = 0;
            err = parse_i16(tokens[2], &x);
            if (err == 0) {
                err = parse_i16(tokens[3], &y);
            }
            if (err == 0) {
                err = mouse_move_relative(x, y);
            }
        } else if ((command == 'C' || command == 'D' || command == 'U') && count == 3) {
            zmk_mouse_button_t button;
            err = parse_button(tokens[2], &button);
            if (err == 0) {
                if (command == 'C') {
                    err = mouse_button_click(button);
                } else if (command == 'D') {
                    err = mouse_button_down(button);
                } else {
                    err = mouse_button_up(button);
                }
            }
        }

        if (err == 0) {
            reset_failsafe_timer();
            send_ack("OK M");
        } else {
            send_ack("ERR M");
        }
        return err;
#else
        send_ack("ERR M DISABLED");
        return -ENOTSUP;
#endif
    }

    send_ack("ERR UNKNOWN");
    return -EINVAL;
}

static void host_cmd_worker(void) {
    char line[CONFIG_ZMK_HOST_CMD_LINE_MAX_LEN];

    while (true) {
        if (k_msgq_get(&host_cmd_queue, line, K_FOREVER) == 0) {
            int err = process_line(line);
            if (err < 0) {
                LOG_WRN("host cmd failed (%d): %s", err, line);
            }
        }
    }
}

K_THREAD_DEFINE(host_cmd_thread, 1024, (k_thread_entry_t)host_cmd_worker, NULL, NULL, NULL,
                K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);

static void enqueue_line(void) {
    rx_line[rx_len] = '\0';
    if (k_msgq_put(&host_cmd_queue, rx_line, K_NO_WAIT) != 0) {
        send_ack("ERR QUEUE");
    }
    rx_len = 0;
}

static void serial_cb(const struct device *dev, void *user_data) {
    ARG_UNUSED(dev);
    ARG_UNUSED(user_data);

    if (!uart_irq_update(uart_dev)) {
        return;
    }

    while (uart_irq_rx_ready(uart_dev)) {
        uint8_t c;
        if (uart_fifo_read(uart_dev, &c, 1) != 1) {
            break;
        }

        if (c == '\r' || c == '\n') {
            if (rx_len > 0) {
                enqueue_line();
            }
            continue;
        }

        if (rx_len + 1 < sizeof(rx_line)) {
            rx_line[rx_len++] = (char)c;
        } else {
            rx_len = 0;
            send_ack("ERR TOOLONG");
        }
    }
}

static int host_cmd_init(void) {
    if (!device_is_ready(uart_dev)) {
        LOG_ERR("host cmd uart not ready");
        return -ENODEV;
    }

    int ret = uart_irq_callback_user_data_set(uart_dev, serial_cb, NULL);
    if (ret < 0) {
        LOG_ERR("failed to set uart callback (%d)", ret);
        return ret;
    }

    k_work_init_delayable(&host_cmd_failsafe_work, host_cmd_failsafe_handler);
    reset_failsafe_timer();

    uart_irq_rx_enable(uart_dev);
    send_ack("HOSTCMD READY");
    return 0;
}

SYS_INIT(host_cmd_init, POST_KERNEL, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);