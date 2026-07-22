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
    struct hall_stream_frame tx_frame;
    size_t tx_offset;
    struct k_sem tx_queued;
};

static void kscan_adc_mux_uart_callback(const struct device *uart, void *user_data) {
    struct kscan_adc_mux_data *data = user_data;

    if (uart_irq_update(uart) <= 0 || !uart_irq_tx_ready(uart)) {
        return;
    }

    const uint8_t *bytes = (const uint8_t *)&data->tx_frame;
    while (data->tx_offset < sizeof(data->tx_frame)) {
        int sent = uart_fifo_fill(uart, bytes + data->tx_offset,
                                  sizeof(data->tx_frame) - data->tx_offset);
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

static void hall_stream_enqueue(const struct device *dev, uint8_t type) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    if (config->stream_uart == NULL || data->stream_queue == NULL) {
        return;
    }

    struct hall_stream_frame frame = {
        .magic = {HALL_STREAM_MAGIC_0, HALL_STREAM_MAGIC_1},
        .version = HALL_STREAM_VERSION,
        .type = type,
        .mode = data->stream_mode,
        .sample_count = type == HALL_STREAM_TYPE_DATA ?
                            MIN(INST_SAMPLE_COUNT(0), HALL_STREAM_MAX_SAMPLES) :
                        type == HALL_STREAM_TYPE_PERF ? 4 : 0,
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

static bool kscan_adc_mux_pressed(const struct kscan_adc_mux_config *config, bool was_pressed,
                                  int32_t sample_mv) {
    if (config->press_is_greater) {
        return was_pressed ? sample_mv > config->release_threshold_mv
                           : sample_mv > config->press_threshold_mv;
    }

    return was_pressed ? sample_mv < config->release_threshold_mv
                       : sample_mv < config->press_threshold_mv;
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
        uint32_t lower_channels = data->batch_channel_mask & (BIT(config->channels[row].channel_id) - 1U);
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

        for (uint8_t row = 0; row < config->channel_count; row++) {
            int32_t sample_mv = samples_mv[row];
            uint16_t idx = (row * config->column_count) + col;
            data->voltages_mv[idx] = CLAMP(sample_mv, 0, UINT16_MAX);
            bool pressed = kscan_adc_mux_pressed(config, data->matrix_state[idx], sample_mv);

            LOG_DBG("ADC mux r%u c%u sample=%d pressed=%d stable=%u", row, col, sample_mv, pressed,
                    data->stable_counts[idx]);

            if (pressed == data->matrix_state[idx]) {
                data->candidate_state[idx] = pressed;
                data->stable_counts[idx] = 0;
                continue;
            }

            if (pressed == data->candidate_state[idx]) {
                if (data->stable_counts[idx] < config->stable_scan_count) {
                    data->stable_counts[idx]++;
                }
            } else {
                data->candidate_state[idx] = pressed;
                data->stable_counts[idx] = 1;
            }

            if (data->stable_counts[idx] >= config->stable_scan_count) {
                data->matrix_state[idx] = pressed;
                data->stable_counts[idx] = 0;
                if (data->callback) {
                    data->callback(dev, row, col, pressed);
                }
            }
        }
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

    if (config->stream_uart != NULL && !device_is_ready(config->stream_uart)) {
        LOG_ERR("ADC stream UART is not ready");
        return -ENODEV;
    }

    if (config->stream_uart != NULL) {
        k_sem_init(&data->tx_queued, 0, 1);
        int err = uart_irq_callback_user_data_set(config->stream_uart,
                                                   kscan_adc_mux_uart_callback, data);
        if (err) {
            LOG_ERR("Failed to configure ADC stream UART callback: %d", err);
            return err;
        }
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

#define KSCAN_ADC_MUX_INIT(n)                                                                         \
    static const struct gpio_dt_spec kscan_adc_mux_address_gpios_##n[] = {                            \
        LISTIFY(INST_ADDRESS_GPIOS(n), GPIO_CFG_INIT, (, ), n)};                                      \
                                                                                                      \
    static const struct adc_dt_spec kscan_adc_mux_channels_##n[] = {                                  \
        LISTIFY(INST_ADC_INPUTS(n), ADC_CFG_INIT, (, ), n)};                                         \
                                                                                                      \
    static struct adc_sequence kscan_adc_mux_seqs_##n[INST_ADC_INPUTS(n)];                            \
    static int16_t kscan_adc_mux_samples_##n[INST_ADC_INPUTS(n)];                                     \
    static uint16_t kscan_adc_mux_voltages_mv_##n[INST_SAMPLE_COUNT(n)];                              \
    static bool kscan_adc_mux_matrix_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];                 \
    static bool kscan_adc_mux_candidate_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];              \
    static uint8_t kscan_adc_mux_stable_counts_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];             \
    static struct k_work_q kscan_adc_mux_work_queue_##n;                                             \
    K_THREAD_STACK_DEFINE(kscan_adc_mux_work_queue_stack_##n, 1024);                                 \
    K_MSGQ_DEFINE(kscan_adc_mux_stream_queue_##n, sizeof(struct hall_stream_frame), 4, 4);             \
    static void kscan_adc_mux_stream_thread_##n(void *, void *, void *);                               \
    K_THREAD_DEFINE(kscan_adc_mux_stream_tid_##n, 1024, kscan_adc_mux_stream_thread_##n, NULL, NULL,  \
                    NULL, K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);                                    \
                                                                                                      \
    static struct kscan_adc_mux_data kscan_adc_mux_data_##n = {                                       \
        .seqs = kscan_adc_mux_seqs_##n,                                                              \
        .samples = kscan_adc_mux_samples_##n,                                                        \
        .voltages_mv = kscan_adc_mux_voltages_mv_##n,                                                \
        .matrix_state = kscan_adc_mux_matrix_state_##n,                                              \
        .candidate_state = kscan_adc_mux_candidate_state_##n,                                        \
        .stable_counts = kscan_adc_mux_stable_counts_##n,                                            \
        .work_queue = &kscan_adc_mux_work_queue_##n,                                                 \
        .work_queue_stack = kscan_adc_mux_work_queue_stack_##n,                                      \
        .work_queue_stack_size = K_THREAD_STACK_SIZEOF(kscan_adc_mux_work_queue_stack_##n),           \
        .stream_queue = &kscan_adc_mux_stream_queue_##n,                                             \
    };                                                                                                \
                                                                                                      \
    static const struct kscan_adc_mux_config kscan_adc_mux_config_##n = {                             \
        .address_gpios = kscan_adc_mux_address_gpios_##n,                                            \
        .channels = kscan_adc_mux_channels_##n,                                                       \
        .address_gpio_count = INST_ADDRESS_GPIOS(n),                                                  \
        .channel_count = INST_ADC_INPUTS(n),                                                         \
        .column_count = INST_COLUMNS(n),                                                             \
        .polling_interval_ms = DT_INST_PROP(n, polling_interval_ms),                                  \
        .settle_time_us = DT_INST_PROP(n, settle_time_us),                                           \
        .dummy_read = DT_INST_PROP(n, dummy_read),                                                   \
        .press_threshold_mv = DT_INST_PROP(n, press_threshold_mv),                                    \
        .release_threshold_mv = DT_INST_PROP(n, release_threshold_mv),                                \
        .stable_scan_count = DT_INST_PROP(n, stable_scan_count),                                      \
        .press_is_greater = DT_INST_PROP(n, press_is_greater),                                       \
        .stream_uart = COND_CODE_1(DT_INST_NODE_HAS_PROP(n, stream_uart),                             \
                                   (DEVICE_DT_GET(DT_INST_PHANDLE(n, stream_uart))), (NULL)),         \
        .mode_switch_position = DT_INST_PROP_OR(n, mode_switch_position, 0),                          \
        .has_mode_switch = DT_INST_NODE_HAS_PROP(n, mode_switch_position),                            \
    };                                                                                                \
                                                                                                      \
    static void kscan_adc_mux_stream_thread_##n(void *a, void *b, void *c) {                          \
        ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);                                                  \
        struct hall_stream_frame frame;                                                              \
        const struct device *uart = kscan_adc_mux_config_##n.stream_uart;                             \
        struct kscan_adc_mux_data *data = &kscan_adc_mux_data_##n;                                   \
        while (true) {                                                                                \
            k_msgq_get(&kscan_adc_mux_stream_queue_##n, &frame, K_FOREVER);                           \
            if (uart == NULL) { continue; }                                                          \
            uint32_t dtr = 0;                                                                         \
            if (uart_line_ctrl_get(uart, UART_LINE_CTRL_DTR, &dtr) == 0 && dtr == 0) { continue; }   \
            data->tx_frame = frame;                                                                  \
            data->tx_offset = 0;                                                                     \
            uart_irq_tx_enable(uart);                                                                \
            k_sem_take(&data->tx_queued, K_FOREVER);                                                 \
        }                                                                                             \
    }                                                                                                 \
                                                                                                      \
    DEVICE_DT_INST_DEFINE(n, &kscan_adc_mux_init, NULL, &kscan_adc_mux_data_##n,                      \
                          &kscan_adc_mux_config_##n, POST_KERNEL, CONFIG_KSCAN_INIT_PRIORITY,         \
                          &kscan_adc_mux_api);

DT_INST_FOREACH_STATUS_OKAY(KSCAN_ADC_MUX_INIT)
