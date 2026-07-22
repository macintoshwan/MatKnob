/*
 * Copyright (c) 2026 The ZMK Contributors
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT zmk_kscan_adc_mux

#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/kscan.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>
#include <zephyr/timing/timing.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define INST_ADC_INPUTS(n) DT_INST_PROP_LEN(n, io_channels)
#define INST_ADDRESS_GPIOS(n) DT_INST_PROP_LEN(n, address_gpios)
#define INST_COLUMNS(n) BIT(INST_ADDRESS_GPIOS(n))
#define INST_SAMPLE_COUNT(n) (INST_ADC_INPUTS(n) * INST_COLUMNS(n))

#define HALL_STREAM_MAGIC_0 'M'
#define HALL_STREAM_MAGIC_1 'K'
#define HALL_STREAM_VERSION 3
#define HALL_STREAM_TYPE_DATA 1
#define HALL_STREAM_TYPE_MODE 2
#define HALL_STREAM_TYPE_PERF 3
#define HALL_STREAM_MODE_COUNT 4
#define HALL_STREAM_MAX_SAMPLES 24

#define HALL_COMMAND_MAGIC_0 'M'
#define HALL_COMMAND_MAGIC_1 'C'
#define HALL_RESPONSE_MAGIC_1 'R'
#define HALL_COMMAND_VERSION 1
#define HALL_COMMAND_PAYLOAD_SIZE 8
#define HALL_CONFIG_SCHEMA_VERSION 1

#define HALL_COMMAND_GET_CONFIG 1
#define HALL_COMMAND_SET_CONFIG 2
#define HALL_COMMAND_SAVE_CONFIG 3
#define HALL_COMMAND_RESET_CONFIG 4
#define HALL_COMMAND_SET_STREAM 5
#define HALL_COMMAND_PING 6

#define HALL_STATUS_OK 0
#define HALL_STATUS_BAD_VERSION 1
#define HALL_STATUS_BAD_LENGTH 2
#define HALL_STATUS_BAD_COMMAND 3
#define HALL_STATUS_BAD_VALUE 4
#define HALL_STATUS_STORAGE_ERROR 5

#define HALL_PRESS_MIN_MV 50
#define HALL_PRESS_MAX_MV 3000
#define HALL_RELEASE_MIN_MV 50
#define HALL_RELEASE_MAX_MV 3300
#define HALL_STABLE_SCAN_MIN 1
#define HALL_STABLE_SCAN_MAX 20

#define GPIO_CFG_INIT(idx, inst) GPIO_DT_SPEC_INST_GET_BY_IDX(inst, address_gpios, idx)
#define ADC_CFG_INIT(idx, inst) ADC_DT_SPEC_INST_GET_BY_IDX(inst, idx)

struct kscan_adc_mux_config {
    const struct gpio_dt_spec *address_gpios;
    const struct adc_dt_spec *channels;
    uint8_t address_gpio_count;
    uint8_t channel_count;
    uint8_t column_count;
    uint32_t polling_interval_ms;
    uint32_t settle_time_us;
    bool dummy_read;
    int32_t press_threshold_mv;
    int32_t release_threshold_mv;
    uint8_t stable_scan_count;
    bool press_is_greater;
    const struct device *stream_uart;
    uint32_t mode_switch_position;
    bool has_mode_switch;
};

struct __packed hall_stream_frame {
    uint8_t magic[2];
    uint8_t version;
    uint8_t type;
    uint8_t mode;
    uint8_t sample_count;
    uint16_t sequence;
    uint32_t timestamp_us;
    uint16_t samples_mv[HALL_STREAM_MAX_SAMPLES];
    uint16_t crc;
};

struct __packed hall_command_frame {
    uint8_t magic[2];
    uint8_t version;
    uint8_t command;
    uint8_t payload_length;
    uint8_t status;
    uint16_t request_id;
    uint8_t payload[HALL_COMMAND_PAYLOAD_SIZE];
    uint16_t crc;
};

struct __packed hall_persisted_config {
    uint8_t schema_version;
    uint8_t stable_scan_count;
    uint16_t press_threshold_mv;
    uint16_t release_threshold_mv;
};

struct kscan_adc_mux_data;

static struct hall_persisted_config hall_saved_config;
static bool hall_saved_config_valid;
static struct kscan_adc_mux_data *hall_active_data;
static const struct kscan_adc_mux_config *hall_active_config;
static int hall_settings_commit(void);

static int hall_settings_set(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    const char *next;

    if (!settings_name_steq(name, "config", &next) || next != NULL) {
        return -ENOENT;
    }
    if (len != sizeof(hall_saved_config)) {
        return -EINVAL;
    }

    int rc = read_cb(cb_arg, &hall_saved_config, sizeof(hall_saved_config));
    if (rc < 0) {
        return rc;
    }
    hall_saved_config_valid = rc == sizeof(hall_saved_config) &&
                              hall_saved_config.schema_version == HALL_CONFIG_SCHEMA_VERSION;
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(megknob_hall, "megknob/hall", NULL, hall_settings_set,
                               hall_settings_commit, NULL);

struct kscan_adc_mux_data {
    const struct device *dev;
    kscan_callback_t callback;
    struct k_work_delayable work;
    struct k_work_q *work_queue;
    k_thread_stack_t *work_queue_stack;
    size_t work_queue_stack_size;
    struct adc_sequence *seqs;
    struct adc_sequence batch_seq;
    uint32_t batch_channel_mask;
    int16_t *samples;
    uint16_t *voltages_mv;
    bool *matrix_state;
    bool *candidate_state;
    uint8_t *stable_counts;
    uint8_t stream_mode;
    bool stream_enabled;
    uint16_t runtime_press_threshold_mv;
    uint16_t runtime_release_threshold_mv;
    uint8_t runtime_stable_scan_count;
    struct k_mutex config_mutex;
    uint16_t stream_sequence;
    uint16_t perf_scan_count;
    uint16_t perf_scan_us;
    uint16_t perf_address_us;
    uint16_t perf_adc_us;
    uint16_t perf_process_us;
    timing_t timestamp_counter;
    uint64_t timestamp_ns;
    uint8_t current_address;
    bool address_valid;
    atomic_t scanning;
    struct k_msgq *stream_queue;
    struct k_msgq *command_queue;
    struct k_msgq *response_queue;
    uint8_t tx_bytes[sizeof(struct hall_stream_frame)];
    size_t tx_length;
    size_t tx_offset;
    struct k_sem tx_queued;
    struct k_work command_work;
    uint8_t rx_bytes[sizeof(struct hall_command_frame)];
    uint8_t rx_offset;
    uint16_t last_request_id;
    bool has_last_response;
    struct hall_command_frame last_response;
};

static bool hall_config_is_valid(const struct kscan_adc_mux_config *config, uint16_t press_mv,
                                 uint16_t release_mv, uint8_t stable_count);

static int hall_settings_commit(void) {
    if (!hall_saved_config_valid || hall_active_data == NULL || hall_active_config == NULL ||
        !hall_config_is_valid(hall_active_config, hall_saved_config.press_threshold_mv,
                              hall_saved_config.release_threshold_mv,
                              hall_saved_config.stable_scan_count)) {
        return 0;
    }

    k_mutex_lock(&hall_active_data->config_mutex, K_FOREVER);
    hall_active_data->runtime_press_threshold_mv = hall_saved_config.press_threshold_mv;
    hall_active_data->runtime_release_threshold_mv = hall_saved_config.release_threshold_mv;
    hall_active_data->runtime_stable_scan_count = hall_saved_config.stable_scan_count;
    k_mutex_unlock(&hall_active_data->config_mutex);
    return 0;
}

static uint16_t hall_stream_crc16(const uint8_t *bytes, size_t len);

static void hall_command_resync(struct kscan_adc_mux_data *data, uint8_t byte) {
    if (data->rx_offset == 0) {
        if (byte == HALL_COMMAND_MAGIC_0) {
            data->rx_bytes[data->rx_offset++] = byte;
        }
        return;
    }
    if (data->rx_offset == 1 && byte != HALL_COMMAND_MAGIC_1) {
        if (byte == HALL_COMMAND_MAGIC_0) {
            data->rx_offset = 1;
            data->rx_bytes[0] = HALL_COMMAND_MAGIC_0;
        } else {
            data->rx_offset = 0;
        }
        return;
    }

    data->rx_bytes[data->rx_offset++] = byte;
    if (data->rx_offset < sizeof(struct hall_command_frame)) {
        return;
    }

    struct hall_command_frame command;
    memcpy(&command, data->rx_bytes, sizeof(command));
    data->rx_offset = 0;
    if (hall_stream_crc16((const uint8_t *)&command, offsetof(struct hall_command_frame, crc)) !=
        command.crc) {
        return;
    }
    if (k_msgq_put(data->command_queue, &command, K_NO_WAIT) == 0) {
        k_work_submit(&data->command_work);
    }
}

static void kscan_adc_mux_uart_callback(const struct device *uart, void *user_data) {
    struct kscan_adc_mux_data *data = user_data;

    if (uart_irq_update(uart) <= 0) {
        return;
    }

    if (uart_irq_rx_ready(uart)) {
        uint8_t bytes[16];
        int count;
        while ((count = uart_fifo_read(uart, bytes, sizeof(bytes))) > 0) {
            for (int i = 0; i < count; i++) {
                hall_command_resync(data, bytes[i]);
            }
        }
    }

    if (!uart_irq_tx_ready(uart)) {
        return;
    }
    while (data->tx_offset < data->tx_length) {
        int sent = uart_fifo_fill(uart, data->tx_bytes + data->tx_offset,
                                  data->tx_length - data->tx_offset);
        if (sent <= 0) {
            return;
        }
        data->tx_offset += sent;
    }

    uart_irq_tx_disable(uart);
    k_sem_give(&data->tx_queued);
}

static uint64_t hall_cycles_elapsed(timing_t start) {
    timing_t end = timing_counter_get();
    return timing_cycles_get(&start, &end);
}

static uint16_t hall_cycles_to_us(uint64_t cycles) {
    return MIN(timing_cycles_to_ns(cycles) / NSEC_PER_USEC, UINT16_MAX);
}

static uint32_t hall_timestamp_us(struct kscan_adc_mux_data *data) {
    timing_t now = timing_counter_get();
    uint64_t elapsed_cycles = timing_cycles_get(&data->timestamp_counter, &now);
    data->timestamp_counter = now;
    /* Convert short deltas before accumulating, avoiding overflow in a
     * cycles-to-nanoseconds multiplication after very long runtimes. */
    data->timestamp_ns += timing_cycles_to_ns(elapsed_cycles);
    return (uint32_t)(data->timestamp_ns / NSEC_PER_USEC);
}

static uint16_t hall_stream_crc16(const uint8_t *data, size_t len) {
    static const uint16_t nibble_table[16] = {
        0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
        0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    };
    uint16_t crc = 0xFFFF;
    while (len-- > 0) {
        crc ^= (uint16_t)(*data++) << 8;
        crc = (uint16_t)((crc << 4) ^ nibble_table[crc >> 12]);
        crc = (uint16_t)((crc << 4) ^ nibble_table[crc >> 12]);
    }
    return crc;
}

static bool hall_config_is_valid(const struct kscan_adc_mux_config *config, uint16_t press_mv,
                                 uint16_t release_mv, uint8_t stable_count) {
    if (press_mv < HALL_PRESS_MIN_MV || press_mv > HALL_PRESS_MAX_MV ||
        release_mv < HALL_RELEASE_MIN_MV || release_mv > HALL_RELEASE_MAX_MV ||
        stable_count < HALL_STABLE_SCAN_MIN || stable_count > HALL_STABLE_SCAN_MAX) {
        return false;
    }
    return config->press_is_greater ? press_mv > release_mv : press_mv < release_mv;
}

static void hall_response_fill_config(struct kscan_adc_mux_data *data,
                                      struct hall_command_frame *response) {
    k_mutex_lock(&data->config_mutex, K_FOREVER);
    response->payload_length = 6;
    sys_put_le16(data->runtime_press_threshold_mv, &response->payload[0]);
    sys_put_le16(data->runtime_release_threshold_mv, &response->payload[2]);
    response->payload[4] = data->runtime_stable_scan_count;
    response->payload[5] = data->stream_enabled ? 1 : 0;
    k_mutex_unlock(&data->config_mutex);
}

static void hall_command_process(struct k_work *work) {
    struct kscan_adc_mux_data *data = CONTAINER_OF(work, struct kscan_adc_mux_data, command_work);
    const struct kscan_adc_mux_config *config = data->dev->config;
    struct hall_command_frame command;

    while (k_msgq_get(data->command_queue, &command, K_NO_WAIT) == 0) {
        struct hall_command_frame response = {
            .magic = {HALL_COMMAND_MAGIC_0, HALL_RESPONSE_MAGIC_1},
            .version = HALL_COMMAND_VERSION,
            .command = command.command,
            .status = HALL_STATUS_OK,
            .request_id = command.request_id,
        };

        if (data->has_last_response && command.request_id == data->last_request_id) {
            if (k_msgq_put(data->response_queue, &data->last_response, K_MSEC(50)) != 0) {
                LOG_WRN("Dropped duplicate Hall response %u", command.request_id);
            }
            continue;
        }
        if (command.version != HALL_COMMAND_VERSION) {
            response.status = HALL_STATUS_BAD_VERSION;
        } else if (command.payload_length > HALL_COMMAND_PAYLOAD_SIZE) {
            response.status = HALL_STATUS_BAD_LENGTH;
        } else {
            switch (command.command) {
            case HALL_COMMAND_GET_CONFIG:
                if (command.payload_length != 0) {
                    response.status = HALL_STATUS_BAD_LENGTH;
                } else {
                    hall_response_fill_config(data, &response);
                }
                break;
            case HALL_COMMAND_SET_CONFIG: {
                if (command.payload_length != 5) {
                    response.status = HALL_STATUS_BAD_LENGTH;
                    break;
                }
                uint16_t press_mv = sys_get_le16(&command.payload[0]);
                uint16_t release_mv = sys_get_le16(&command.payload[2]);
                uint8_t stable_count = command.payload[4];
                if (!hall_config_is_valid(config, press_mv, release_mv, stable_count)) {
                    response.status = HALL_STATUS_BAD_VALUE;
                    break;
                }
                k_mutex_lock(&data->config_mutex, K_FOREVER);
                data->runtime_press_threshold_mv = press_mv;
                data->runtime_release_threshold_mv = release_mv;
                data->runtime_stable_scan_count = stable_count;
                memset(data->stable_counts, 0, INST_SAMPLE_COUNT(0));
                memcpy(data->candidate_state, data->matrix_state,
                       sizeof(bool) * INST_SAMPLE_COUNT(0));
                k_mutex_unlock(&data->config_mutex);
                hall_response_fill_config(data, &response);
                break;
            }
            case HALL_COMMAND_SAVE_CONFIG: {
                if (command.payload_length != 0) {
                    response.status = HALL_STATUS_BAD_LENGTH;
                    break;
                }
                struct hall_persisted_config saved;
                k_mutex_lock(&data->config_mutex, K_FOREVER);
                saved = (struct hall_persisted_config){
                    .schema_version = HALL_CONFIG_SCHEMA_VERSION,
                    .stable_scan_count = data->runtime_stable_scan_count,
                    .press_threshold_mv = data->runtime_press_threshold_mv,
                    .release_threshold_mv = data->runtime_release_threshold_mv,
                };
                k_mutex_unlock(&data->config_mutex);
                int rc = settings_save_one("megknob/hall/config", &saved, sizeof(saved));
                if (rc != 0) {
                    response.status = HALL_STATUS_STORAGE_ERROR;
                }
                hall_response_fill_config(data, &response);
                break;
            }
            case HALL_COMMAND_RESET_CONFIG: {
                if (command.payload_length != 0) {
                    response.status = HALL_STATUS_BAD_LENGTH;
                    break;
                }
                k_mutex_lock(&data->config_mutex, K_FOREVER);
                data->runtime_press_threshold_mv = config->press_threshold_mv;
                data->runtime_release_threshold_mv = config->release_threshold_mv;
                data->runtime_stable_scan_count = config->stable_scan_count;
                memset(data->stable_counts, 0, INST_SAMPLE_COUNT(0));
                memcpy(data->candidate_state, data->matrix_state,
                       sizeof(bool) * INST_SAMPLE_COUNT(0));
                k_mutex_unlock(&data->config_mutex);
                hall_saved_config_valid = false;
                int rc = settings_delete("megknob/hall/config");
                if (rc != 0 && rc != -ENOENT) {
                    response.status = HALL_STATUS_STORAGE_ERROR;
                }
                hall_response_fill_config(data, &response);
                break;
            }
            case HALL_COMMAND_SET_STREAM:
                if (command.payload_length != 1 || command.payload[0] > 1) {
                    response.status = command.payload_length != 1 ? HALL_STATUS_BAD_LENGTH
                                                                  : HALL_STATUS_BAD_VALUE;
                    break;
                }
                k_mutex_lock(&data->config_mutex, K_FOREVER);
                data->stream_enabled = command.payload[0] != 0;
                k_mutex_unlock(&data->config_mutex);
                hall_response_fill_config(data, &response);
                break;
            case HALL_COMMAND_PING:
                if (command.payload_length != 0) {
                    response.status = HALL_STATUS_BAD_LENGTH;
                    break;
                }
                response.payload_length = 4;
                response.payload[0] = HALL_STREAM_VERSION;
                response.payload[1] = HALL_CONFIG_SCHEMA_VERSION;
                response.payload[2] = HALL_STREAM_MAX_SAMPLES;
                response.payload[3] = HALL_COMMAND_VERSION;
                break;
            default:
                response.status = HALL_STATUS_BAD_COMMAND;
                break;
            }
        }
        response.crc =
            hall_stream_crc16((const uint8_t *)&response, offsetof(struct hall_command_frame, crc));
        data->last_request_id = command.request_id;
        data->last_response = response;
        data->has_last_response = true;
        if (k_msgq_put(data->response_queue, &response, K_MSEC(50)) != 0) {
            LOG_WRN("Dropped Hall command response %u", response.request_id);
        }
    }
}

static void hall_stream_enqueue(const struct device *dev, uint8_t type) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    k_mutex_lock(&data->config_mutex, K_FOREVER);
    bool stream_enabled = data->stream_enabled;
    k_mutex_unlock(&data->config_mutex);
    if (config->stream_uart == NULL || data->stream_queue == NULL || !stream_enabled) {
        return;
    }

    struct hall_stream_frame frame = {
        .magic = {HALL_STREAM_MAGIC_0, HALL_STREAM_MAGIC_1},
        .version = HALL_STREAM_VERSION,
        .type = type,
        .mode = data->stream_mode,
        .sample_count = type == HALL_STREAM_TYPE_DATA
                            ? MIN(INST_SAMPLE_COUNT(0), HALL_STREAM_MAX_SAMPLES)
                        : type == HALL_STREAM_TYPE_PERF ? 4
                                                        : 0,
        .sequence = data->stream_sequence++,
        .timestamp_us = hall_timestamp_us(data),
    };

    if (type == HALL_STREAM_TYPE_DATA) {
        for (uint8_t i = 0; i < frame.sample_count; i++) {
            frame.samples_mv[i] = data->voltages_mv[i];
        }
    } else if (type == HALL_STREAM_TYPE_PERF) {
        frame.samples_mv[0] = data->perf_scan_us;
        frame.samples_mv[1] = data->perf_address_us;
        frame.samples_mv[2] = data->perf_adc_us;
        frame.samples_mv[3] = data->perf_process_us;
    }
    frame.crc = hall_stream_crc16((const uint8_t *)&frame, offsetof(struct hall_stream_frame, crc));

    /* Keep acquisition real-time: discard the oldest frame if the host is behind. */
    if (k_msgq_put(data->stream_queue, &frame, K_NO_WAIT) != 0) {
        struct hall_stream_frame discarded;
        (void)k_msgq_get(data->stream_queue, &discarded, K_NO_WAIT);
        (void)k_msgq_put(data->stream_queue, &frame, K_NO_WAIT);
    }
}

static bool kscan_adc_mux_pressed(const struct kscan_adc_mux_config *config,
                                  const struct kscan_adc_mux_data *data, bool was_pressed,
                                  int32_t sample_mv) {
    if (config->press_is_greater) {
        return was_pressed ? sample_mv > data->runtime_release_threshold_mv
                           : sample_mv > data->runtime_press_threshold_mv;
    }

    return was_pressed ? sample_mv < data->runtime_release_threshold_mv
                       : sample_mv < data->runtime_press_threshold_mv;
}

static int kscan_adc_mux_set_address(const struct device *dev, uint8_t address) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;
    uint8_t changed = data->address_valid ? data->current_address ^ address
                                          : BIT_MASK(config->address_gpio_count);

    for (uint8_t bit = 0; bit < config->address_gpio_count; bit++) {
        if (!(changed & BIT(bit))) {
            continue;
        }
        int err = gpio_pin_set_dt(&config->address_gpios[bit], (address & BIT(bit)) != 0);
        if (err) {
            LOG_ERR("Failed to set mux address GPIO %u: %d", bit, err);
            return err;
        }
    }
    data->current_address = address;
    data->address_valid = true;

    if (config->settle_time_us > 0) {
        /* Sub-millisecond mux settling must not pay scheduler/tick wake-up latency. */
        k_busy_wait(config->settle_time_us);
    }

    return 0;
}

static int kscan_adc_mux_read_channels(const struct device *dev, int32_t *samples_mv) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    data->batch_seq.buffer = data->samples;
    data->batch_seq.buffer_size = sizeof(data->samples[0]) * config->channel_count;

    int err;
    if (config->dummy_read) {
        err = adc_read(config->channels[0].dev, &data->batch_seq);
        if (err) {
            LOG_ERR("ADC batch dummy read failed: %d", err);
            return err;
        }
    }

    err = adc_read(config->channels[0].dev, &data->batch_seq);
    if (err) {
        LOG_ERR("ADC batch read failed: %d", err);
        return err;
    }

    /* Zephyr stores multi-channel samples in ascending ADC channel-id order. */
    for (uint8_t row = 0; row < config->channel_count; row++) {
        uint32_t lower_channels =
            data->batch_channel_mask & (BIT(config->channels[row].channel_id) - 1U);
        uint8_t sample_index = POPCOUNT(lower_channels);
        samples_mv[row] = data->samples[sample_index];
        err = adc_raw_to_millivolts_dt(&config->channels[row], &samples_mv[row]);
        if (err) {
            LOG_ERR("ADC conversion failed for channel %u: %d", row, err);
            return err;
        }
    }

    return 0;
}

static int kscan_adc_mux_read(const struct device *dev) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    static const uint8_t gray_order[8] = {0, 1, 3, 2, 6, 7, 5, 4};
    timing_t scan_start = timing_counter_get();
    uint64_t address_cycles = 0;
    uint64_t adc_cycles = 0;

    for (uint8_t order = 0; order < config->column_count; order++) {
        uint8_t col = gray_order[order];
        timing_t stage_start = timing_counter_get();
        int err = kscan_adc_mux_set_address(dev, col);
        address_cycles += hall_cycles_elapsed(stage_start);
        if (err) {
            return err;
        }

        int32_t samples_mv[INST_ADC_INPUTS(0)];
        stage_start = timing_counter_get();
        err = kscan_adc_mux_read_channels(dev, samples_mv);
        adc_cycles += hall_cycles_elapsed(stage_start);
        if (err) {
            return err;
        }

        k_mutex_lock(&data->config_mutex, K_FOREVER);
        for (uint8_t row = 0; row < config->channel_count; row++) {
            int32_t sample_mv = samples_mv[row];
            uint16_t idx = (row * config->column_count) + col;
            data->voltages_mv[idx] = CLAMP(sample_mv, 0, UINT16_MAX);
            bool pressed = kscan_adc_mux_pressed(config, data, data->matrix_state[idx], sample_mv);

            LOG_DBG("ADC mux r%u c%u sample=%d pressed=%d stable=%u", row, col, sample_mv, pressed,
                    data->stable_counts[idx]);

            if (pressed == data->matrix_state[idx]) {
                data->candidate_state[idx] = pressed;
                data->stable_counts[idx] = 0;
                continue;
            }

            if (pressed == data->candidate_state[idx]) {
                if (data->stable_counts[idx] < data->runtime_stable_scan_count) {
                    data->stable_counts[idx]++;
                }
            } else {
                data->candidate_state[idx] = pressed;
                data->stable_counts[idx] = 1;
            }

            if (data->stable_counts[idx] >= data->runtime_stable_scan_count) {
                data->matrix_state[idx] = pressed;
                data->stable_counts[idx] = 0;
                if (data->callback) {
                    data->callback(dev, row, col, pressed);
                }
            }
        }
        k_mutex_unlock(&data->config_mutex);
    }

    uint64_t total_cycles = hall_cycles_elapsed(scan_start);
    data->perf_scan_us = hall_cycles_to_us(total_cycles);
    data->perf_address_us = hall_cycles_to_us(address_cycles);
    data->perf_adc_us = hall_cycles_to_us(adc_cycles);
    data->perf_process_us = hall_cycles_to_us(total_cycles - address_cycles - adc_cycles);
    hall_stream_enqueue(dev, HALL_STREAM_TYPE_DATA);
    if (++data->perf_scan_count == 256) {
        data->perf_scan_count = 0;
        hall_stream_enqueue(dev, HALL_STREAM_TYPE_PERF);
    }

    return 0;
}

static void kscan_adc_mux_work_handler(struct k_work *work) {
    struct k_work_delayable *dwork = CONTAINER_OF(work, struct k_work_delayable, work);
    struct kscan_adc_mux_data *data = CONTAINER_OF(dwork, struct kscan_adc_mux_data, work);
    const struct kscan_adc_mux_config *config = data->dev->config;

    while (atomic_get(&data->scanning)) {
        (void)kscan_adc_mux_read(data->dev);
        if (config->polling_interval_ms > 0) {
            k_msleep(config->polling_interval_ms);
        } else {
            /* Let the equally-prioritized CDC sender run without paying the
             * delayable-work reschedule cost once per scan. */
            k_yield();
        }
    }
}

static int kscan_adc_mux_configure(const struct device *dev, kscan_callback_t callback) {
    struct kscan_adc_mux_data *data = dev->data;

    if (!callback) {
        return -EINVAL;
    }

    data->callback = callback;
    return 0;
}

static int kscan_adc_mux_enable(const struct device *dev) {
    struct kscan_adc_mux_data *data = dev->data;

    if (!atomic_cas(&data->scanning, 0, 1)) {
        return 0;
    }
    if (k_work_schedule_for_queue(data->work_queue, &data->work, K_NO_WAIT) < 0) {
        atomic_clear(&data->scanning);
        return -EIO;
    }
    return 0;
}

static int kscan_adc_mux_disable(const struct device *dev) {
    struct kscan_adc_mux_data *data = dev->data;

    atomic_clear(&data->scanning);
    return 0;
}

static int kscan_adc_mux_init(const struct device *dev) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    data->dev = dev;
    k_mutex_init(&data->config_mutex);
    hall_active_data = data;
    hall_active_config = config;
    data->stream_enabled = true;
    data->runtime_press_threshold_mv = config->press_threshold_mv;
    data->runtime_release_threshold_mv = config->release_threshold_mv;
    data->runtime_stable_scan_count = config->stable_scan_count;
    if (hall_saved_config_valid &&
        hall_config_is_valid(config, hall_saved_config.press_threshold_mv,
                             hall_saved_config.release_threshold_mv,
                             hall_saved_config.stable_scan_count)) {
        data->runtime_press_threshold_mv = hall_saved_config.press_threshold_mv;
        data->runtime_release_threshold_mv = hall_saved_config.release_threshold_mv;
        data->runtime_stable_scan_count = hall_saved_config.stable_scan_count;
    }
    k_work_init(&data->command_work, hall_command_process);

    if (config->stream_uart != NULL && !device_is_ready(config->stream_uart)) {
        LOG_ERR("ADC stream UART is not ready");
        return -ENODEV;
    }

    if (config->stream_uart != NULL) {
        k_sem_init(&data->tx_queued, 0, 1);
        int err =
            uart_irq_callback_user_data_set(config->stream_uart, kscan_adc_mux_uart_callback, data);
        if (err) {
            LOG_ERR("Failed to configure ADC stream UART callback: %d", err);
            return err;
        }
        uart_irq_rx_enable(config->stream_uart);
    }

    for (uint8_t i = 0; i < config->address_gpio_count; i++) {
        const struct gpio_dt_spec *gpio = &config->address_gpios[i];

        if (!device_is_ready(gpio->port)) {
            LOG_ERR("Mux address GPIO port %s is not ready", gpio->port->name);
            return -ENODEV;
        }

        int err = gpio_pin_configure_dt(gpio, GPIO_OUTPUT_INACTIVE);
        if (err) {
            LOG_ERR("Failed to configure mux address GPIO %u: %d", i, err);
            return err;
        }
    }

    for (uint8_t i = 0; i < config->channel_count; i++) {
        const struct adc_dt_spec *channel = &config->channels[i];

        if (!adc_is_ready_dt(channel)) {
            LOG_ERR("ADC controller %s is not ready", channel->dev->name);
            return -ENODEV;
        }

        int err = adc_channel_setup_dt(channel);
        if (err) {
            LOG_ERR("ADC channel setup failed for channel %u: %d", i, err);
            return err;
        }

        err = adc_sequence_init_dt(channel, &data->seqs[i]);
        if (err) {
            LOG_ERR("ADC sequence init failed for channel %u: %d", i, err);
            return err;
        }

        if (i > 0 && (channel->dev != config->channels[0].dev ||
                      data->seqs[i].resolution != data->seqs[0].resolution ||
                      data->seqs[i].oversampling != data->seqs[0].oversampling)) {
            LOG_ERR("ADC mux inputs must share one controller, resolution, and oversampling");
            return -EINVAL;
        }
        data->batch_channel_mask |= BIT(channel->channel_id);
    }

    data->batch_seq = data->seqs[0];
    data->batch_seq.channels = data->batch_channel_mask;
    data->batch_seq.buffer = data->samples;
    data->batch_seq.buffer_size = sizeof(data->samples[0]) * config->channel_count;

    timing_init();
    timing_start();
    data->timestamp_counter = timing_counter_get();
    k_work_init_delayable(&data->work, kscan_adc_mux_work_handler);
    k_work_queue_start(data->work_queue, data->work_queue_stack, data->work_queue_stack_size,
                       K_LOWEST_APPLICATION_THREAD_PRIO, NULL);

    return 0;
}

int zmk_hall_stream_cycle_mode(uint32_t position) {
    const struct device *dev = DEVICE_DT_GET(DT_DRV_INST(0));
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    if (!config->has_mode_switch || position != config->mode_switch_position) {
        return -EINVAL;
    }

    data->stream_mode = (data->stream_mode + 1) % HALL_STREAM_MODE_COUNT;
    hall_stream_enqueue(dev, HALL_STREAM_TYPE_MODE);
    return 0;
}

static const struct kscan_driver_api kscan_adc_mux_api = {
    .config = kscan_adc_mux_configure,
    .enable_callback = kscan_adc_mux_enable,
    .disable_callback = kscan_adc_mux_disable,
};

#define KSCAN_ADC_MUX_INIT(n)                                                                      \
    static const struct gpio_dt_spec kscan_adc_mux_address_gpios_##n[] = {                         \
        LISTIFY(INST_ADDRESS_GPIOS(n), GPIO_CFG_INIT, (, ), n)};                                   \
                                                                                                   \
    static const struct adc_dt_spec kscan_adc_mux_channels_##n[] = {                               \
        LISTIFY(INST_ADC_INPUTS(n), ADC_CFG_INIT, (, ), n)};                                       \
                                                                                                   \
    static struct adc_sequence kscan_adc_mux_seqs_##n[INST_ADC_INPUTS(n)];                         \
    static int16_t kscan_adc_mux_samples_##n[INST_ADC_INPUTS(n)];                                  \
    static uint16_t kscan_adc_mux_voltages_mv_##n[INST_SAMPLE_COUNT(n)];                           \
    static bool kscan_adc_mux_matrix_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];              \
    static bool kscan_adc_mux_candidate_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];           \
    static uint8_t kscan_adc_mux_stable_counts_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];          \
    static struct k_work_q kscan_adc_mux_work_queue_##n;                                           \
    K_THREAD_STACK_DEFINE(kscan_adc_mux_work_queue_stack_##n, 1024);                               \
    K_MSGQ_DEFINE(kscan_adc_mux_stream_queue_##n, sizeof(struct hall_stream_frame), 4, 4);         \
    K_MSGQ_DEFINE(kscan_adc_mux_command_queue_##n, sizeof(struct hall_command_frame), 4, 4);       \
    K_MSGQ_DEFINE(kscan_adc_mux_response_queue_##n, sizeof(struct hall_command_frame), 4, 4);      \
    static void kscan_adc_mux_stream_thread_##n(void *, void *, void *);                           \
    K_THREAD_DEFINE(kscan_adc_mux_stream_tid_##n, 1024, kscan_adc_mux_stream_thread_##n, NULL,     \
                    NULL, NULL, K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);                           \
                                                                                                   \
    static struct kscan_adc_mux_data kscan_adc_mux_data_##n = {                                    \
        .seqs = kscan_adc_mux_seqs_##n,                                                            \
        .samples = kscan_adc_mux_samples_##n,                                                      \
        .voltages_mv = kscan_adc_mux_voltages_mv_##n,                                              \
        .matrix_state = kscan_adc_mux_matrix_state_##n,                                            \
        .candidate_state = kscan_adc_mux_candidate_state_##n,                                      \
        .stable_counts = kscan_adc_mux_stable_counts_##n,                                          \
        .work_queue = &kscan_adc_mux_work_queue_##n,                                               \
        .work_queue_stack = kscan_adc_mux_work_queue_stack_##n,                                    \
        .work_queue_stack_size = K_THREAD_STACK_SIZEOF(kscan_adc_mux_work_queue_stack_##n),        \
        .stream_queue = &kscan_adc_mux_stream_queue_##n,                                           \
        .command_queue = &kscan_adc_mux_command_queue_##n,                                         \
        .response_queue = &kscan_adc_mux_response_queue_##n,                                       \
    };                                                                                             \
                                                                                                   \
    static const struct kscan_adc_mux_config kscan_adc_mux_config_##n = {                          \
        .address_gpios = kscan_adc_mux_address_gpios_##n,                                          \
        .channels = kscan_adc_mux_channels_##n,                                                    \
        .address_gpio_count = INST_ADDRESS_GPIOS(n),                                               \
        .channel_count = INST_ADC_INPUTS(n),                                                       \
        .column_count = INST_COLUMNS(n),                                                           \
        .polling_interval_ms = DT_INST_PROP(n, polling_interval_ms),                               \
        .settle_time_us = DT_INST_PROP(n, settle_time_us),                                         \
        .dummy_read = DT_INST_PROP(n, dummy_read),                                                 \
        .press_threshold_mv = DT_INST_PROP(n, press_threshold_mv),                                 \
        .release_threshold_mv = DT_INST_PROP(n, release_threshold_mv),                             \
        .stable_scan_count = DT_INST_PROP(n, stable_scan_count),                                   \
        .press_is_greater = DT_INST_PROP(n, press_is_greater),                                     \
        .stream_uart = COND_CODE_1(DT_INST_NODE_HAS_PROP(n, stream_uart),                          \
                                   (DEVICE_DT_GET(DT_INST_PHANDLE(n, stream_uart))), (NULL)),      \
        .mode_switch_position = DT_INST_PROP_OR(n, mode_switch_position, 0),                       \
        .has_mode_switch = DT_INST_NODE_HAS_PROP(n, mode_switch_position),                         \
    };                                                                                             \
                                                                                                   \
    static void kscan_adc_mux_stream_thread_##n(void *a, void *b, void *c) {                       \
        ARG_UNUSED(a);                                                                             \
        ARG_UNUSED(b);                                                                             \
        ARG_UNUSED(c);                                                                             \
        struct hall_stream_frame frame;                                                            \
        struct hall_command_frame response;                                                        \
        const struct device *uart = kscan_adc_mux_config_##n.stream_uart;                          \
        struct kscan_adc_mux_data *data = &kscan_adc_mux_data_##n;                                 \
        while (true) {                                                                             \
            bool is_response =                                                                     \
                k_msgq_get(&kscan_adc_mux_response_queue_##n, &response, K_NO_WAIT) == 0;          \
            if (!is_response &&                                                                    \
                k_msgq_get(&kscan_adc_mux_stream_queue_##n, &frame, K_MSEC(10)) != 0) {            \
                continue;                                                                          \
            }                                                                                      \
            if (uart == NULL) {                                                                    \
                continue;                                                                          \
            }                                                                                      \
            uint32_t dtr = 0;                                                                      \
            if (uart_line_ctrl_get(uart, UART_LINE_CTRL_DTR, &dtr) == 0 && dtr == 0) {             \
                continue;                                                                          \
            }                                                                                      \
            data->tx_length = is_response ? sizeof(response) : sizeof(frame);                      \
            memcpy(data->tx_bytes, is_response ? (const void *)&response : (const void *)&frame,   \
                   data->tx_length);                                                               \
            data->tx_offset = 0;                                                                   \
            uart_irq_tx_enable(uart);                                                              \
            k_sem_take(&data->tx_queued, K_FOREVER);                                               \
        }                                                                                          \
    }                                                                                              \
                                                                                                   \
    DEVICE_DT_INST_DEFINE(n, &kscan_adc_mux_init, NULL, &kscan_adc_mux_data_##n,                   \
                          &kscan_adc_mux_config_##n, POST_KERNEL, CONFIG_KSCAN_INIT_PRIORITY,      \
                          &kscan_adc_mux_api);

DT_INST_FOREACH_STATUS_OKAY(KSCAN_ADC_MUX_INIT)
