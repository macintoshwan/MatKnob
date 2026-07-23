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
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define INST_ADC_INPUTS(n) DT_INST_PROP_LEN(n, io_channels)
#define INST_ADDRESS_GPIOS(n) DT_INST_PROP_LEN(n, address_gpios)
#define INST_COLUMNS(n) BIT(INST_ADDRESS_GPIOS(n))

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
    int32_t press_threshold_mv;
    int32_t release_threshold_mv;
    bool press_is_greater;
};

struct kscan_adc_mux_data {
    const struct device *dev;
    kscan_callback_t callback;
    struct k_work_delayable work;
    struct adc_sequence *seqs;
    uint16_t *samples;
    bool *matrix_state;
};

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

    for (uint8_t bit = 0; bit < config->address_gpio_count; bit++) {
        int err = gpio_pin_set_dt(&config->address_gpios[bit], (address & BIT(bit)) != 0);
        if (err) {
            LOG_ERR("Failed to set mux address GPIO %u: %d", bit, err);
            return err;
        }
    }

    if (config->settle_time_us > 0) {
        k_usleep(config->settle_time_us);
    }

    return 0;
}

static int kscan_adc_mux_read_channel(const struct device *dev, uint8_t channel, int32_t *sample_mv) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    data->seqs[channel].buffer = &data->samples[channel];
    data->seqs[channel].buffer_size = sizeof(data->samples[channel]);

    int err = adc_read(config->channels[channel].dev, &data->seqs[channel]);
    if (err) {
        LOG_ERR("ADC read failed for channel %u: %d", channel, err);
        return err;
    }

    *sample_mv = data->samples[channel];
    err = adc_raw_to_millivolts_dt(&config->channels[channel], sample_mv);
    if (err) {
        LOG_ERR("ADC conversion failed for channel %u: %d", channel, err);
        return err;
    }

    return 0;
}

static int kscan_adc_mux_read(const struct device *dev) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    for (uint8_t col = 0; col < config->column_count; col++) {
        int err = kscan_adc_mux_set_address(dev, col);
        if (err) {
            return err;
        }

        for (uint8_t row = 0; row < config->channel_count; row++) {
            int32_t sample_mv;
            err = kscan_adc_mux_read_channel(dev, row, &sample_mv);
            if (err) {
                return err;
            }

            uint16_t idx = (row * config->column_count) + col;
            bool pressed = kscan_adc_mux_pressed(config, data->matrix_state[idx], sample_mv);

            LOG_DBG("ADC mux r%u c%u sample=%d pressed=%d", row, col, sample_mv, pressed);

            if (pressed != data->matrix_state[idx]) {
                data->matrix_state[idx] = pressed;
                if (data->callback) {
                    data->callback(dev, row, col, pressed);
                }
            }
        }
    }

    return 0;
}

static void kscan_adc_mux_work_handler(struct k_work *work) {
    struct k_work_delayable *dwork = CONTAINER_OF(work, struct k_work_delayable, work);
    struct kscan_adc_mux_data *data = CONTAINER_OF(dwork, struct kscan_adc_mux_data, work);
    const struct kscan_adc_mux_config *config = data->dev->config;

    kscan_adc_mux_read(data->dev);
    k_work_schedule(&data->work, K_MSEC(config->polling_interval_ms));
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

    return k_work_schedule(&data->work, K_NO_WAIT) < 0 ? -EIO : 0;
}

static int kscan_adc_mux_disable(const struct device *dev) {
    struct kscan_adc_mux_data *data = dev->data;

    return k_work_cancel_delayable(&data->work) < 0 ? -EIO : 0;
}

static int kscan_adc_mux_init(const struct device *dev) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;

    data->dev = dev;

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
    }

    k_work_init_delayable(&data->work, kscan_adc_mux_work_handler);

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
    static uint16_t kscan_adc_mux_samples_##n[INST_ADC_INPUTS(n)];                                    \
    static bool kscan_adc_mux_matrix_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];                 \
                                                                                                      \
    static struct kscan_adc_mux_data kscan_adc_mux_data_##n = {                                       \
        .seqs = kscan_adc_mux_seqs_##n,                                                              \
        .samples = kscan_adc_mux_samples_##n,                                                        \
        .matrix_state = kscan_adc_mux_matrix_state_##n,                                              \
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
        .press_threshold_mv = DT_INST_PROP(n, press_threshold_mv),                                    \
        .release_threshold_mv = DT_INST_PROP(n, release_threshold_mv),                                \
        .press_is_greater = DT_INST_PROP(n, press_is_greater),                                       \
    };                                                                                                \
                                                                                                      \
    DEVICE_DT_INST_DEFINE(n, &kscan_adc_mux_init, NULL, &kscan_adc_mux_data_##n,                      \
                          &kscan_adc_mux_config_##n, POST_KERNEL, CONFIG_KSCAN_INIT_PRIORITY,         \
                          &kscan_adc_mux_api);

DT_INST_FOREACH_STATUS_OKAY(KSCAN_ADC_MUX_INIT)
