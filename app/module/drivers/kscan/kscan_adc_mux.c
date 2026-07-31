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

#include <zmk/debounce.h>
#include <zmk/hall_telemetry.h>

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
    struct zmk_debounce_config debounce_config;
};

struct kscan_adc_mux_data {
    const struct device *dev;
    kscan_callback_t callback;
    struct k_work_delayable work;
    struct adc_sequence *seqs;
    uint16_t *samples;
    bool *matrix_state;
    struct zmk_debounce_state *debounce_state;
};

/* Raw, instantaneous threshold comparison for a single ADC sample. This is
 * intentionally noisy right around the flip point: Hall sensor output can
 * hover a few millivolts wide there due to mechanical vibration, magnet
 * wobble, and ADC quantization/noise. The result is fed into the
 * zmk_debounce integrator below rather than being latched directly, so a
 * handful of consecutive scans agreeing is required before the reported
 * (debounced) state actually changes and a callback fires. Without that,
 * a finger resting near the threshold can make the driver emit dozens of
 * spurious press/release pairs per second, which is what was causing
 * modifiers (Ctrl/Alt/GUI) to get stuck: see kscan_adc_mux_read() below. */
static bool kscan_adc_mux_pressed(const struct device *dev, uint16_t idx, bool was_pressed,
                                  int32_t sample_mv) {
    const struct kscan_adc_mux_config *config = dev->config;
    int32_t press_mv = config->press_threshold_mv;
    int32_t release_mv = config->release_threshold_mv;

    /* If the web configurator has downloaded a per-key calibration (Issue D
     * command protocol), it overrides the DT-global defaults for this key;
     * hall_telemetry_get_thresholds() returns false until then, keeping the
     * defaults. On boards without CONFIG_HALL_TELEMETRY this is an inline stub
     * that always returns false, so the defaults are always used. */
    (void)hall_telemetry_get_thresholds(idx, &press_mv, &release_mv);

    if (config->press_is_greater) {
        return was_pressed ? sample_mv > release_mv : sample_mv > press_mv;
    }

    return was_pressed ? sample_mv < release_mv : sample_mv < press_mv;
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

static int kscan_adc_mux_read_channel(const struct device *dev, uint8_t channel,
                                      int32_t *sample_mv) {
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

    /* Collected for hall_telemetry_submit() below. Only meaningful when
     * channel_count * column_count == HALL_TELEMETRY_CHANNELS (true for the
     * MegKnob 3x8 layout); telemetry is a no-op build-time stub on any board
     * that does not opt into CONFIG_HALL_TELEMETRY, so this stays harmless
     * (just an unused stack array) everywhere else. */
    int32_t telemetry_mv[HALL_TELEMETRY_CHANNELS];
    bool telemetry_shape_matches =
        ((uint16_t)config->channel_count * config->column_count) == HALL_TELEMETRY_CHANNELS;

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

            if (telemetry_shape_matches) {
                telemetry_mv[idx] = sample_mv;
            }

            struct zmk_debounce_state *deb_state = &data->debounce_state[idx];

            /* Instantaneous (possibly bouncy) threshold decision, based on
             * the debounced/latched state from the previous scan so the
             * hysteresis (press vs release threshold) still applies. */
            bool raw_pressed =
                kscan_adc_mux_pressed(dev, idx, zmk_debounce_is_pressed(deb_state), sample_mv);

            zmk_debounce_update(deb_state, raw_pressed, config->polling_interval_ms,
                                &config->debounce_config);

            LOG_DBG("ADC mux r%u c%u sample=%d raw=%d debounced=%d", row, col, sample_mv,
                    raw_pressed, zmk_debounce_is_pressed(deb_state));

            if (!zmk_debounce_get_changed(deb_state)) {
                continue;
            }

            bool pressed = zmk_debounce_is_pressed(deb_state);
            data->matrix_state[idx] = pressed;

            if (data->callback) {
                data->callback(dev, row, col, pressed);
            }
        }
    }

    /* Telemetry is submitted last, after all 24 channels for this scan are
     * known, and only ever pushes into a bounded queue with K_NO_WAIT (see
     * hall_telemetry_submit()) -- it cannot block or slow down this scan
     * loop, keeping HID/BLE-relevant timing unaffected by whether a USB
     * telemetry host is attached. Mode is hardcoded to "all channels" (3);
     * the wheel-press-cycles-viewer-mode behavior described in
     * a future telemetry control protocol is not wired up to this simplified
     * driver. */
    if (telemetry_shape_matches) {
        hall_telemetry_submit(3, telemetry_mv);
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

static void kscan_adc_mux_release_all(const struct device *dev) {
    const struct kscan_adc_mux_config *config = dev->config;
    struct kscan_adc_mux_data *data = dev->data;
    uint16_t count = (uint16_t)config->channel_count * config->column_count;

    /* Hall/ADC-threshold keys have no physical "open" state once scanning
     * stops: whatever matrix_state[] last held keeps being what the host
     * believes is pressed, because no further HID report will ever be sent
     * to correct it. If a modifier such as Ctrl/Alt/GUI is mid-press right
     * when USB/BLE is unplugged or the scan is disabled, the host is left
     * with that modifier stuck down until the user physically presses and
     * releases the real key again. Explicitly emit release callbacks for
     * every position that is still marked pressed before we stop scanning,
     * so ZMK's input pipeline always sees a clean press/release pair. */
    for (uint16_t idx = 0; idx < count; idx++) {
        /* Reset the debounce integrator too, so that after a disable/enable
         * cycle (e.g. output switching or PM suspend/resume) we don't carry
         * over a half-confirmed transition from before the scan stopped. */
        data->debounce_state[idx] = (struct zmk_debounce_state){0};

        if (!data->matrix_state[idx]) {
            continue;
        }

        data->matrix_state[idx] = false;

        if (data->callback) {
            uint8_t row = idx / config->column_count;
            uint8_t col = idx % config->column_count;

            data->callback(dev, row, col, false);
        }
    }
}

static int kscan_adc_mux_disable(const struct device *dev) {
    struct kscan_adc_mux_data *data = dev->data;
    int err = k_work_cancel_delayable(&data->work);

    kscan_adc_mux_release_all(dev);

    return err < 0 ? -EIO : 0;
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

#define KSCAN_ADC_MUX_INIT(n)                                                                      \
    BUILD_ASSERT(DT_INST_PROP(n, debounce_press_ms) <= DEBOUNCE_COUNTER_MAX,                       \
                 "debounce-press-ms is too large");                                                \
    BUILD_ASSERT(DT_INST_PROP(n, debounce_release_ms) <= DEBOUNCE_COUNTER_MAX,                     \
                 "debounce-release-ms is too large");                                              \
                                                                                                   \
    static const struct gpio_dt_spec kscan_adc_mux_address_gpios_##n[] = {                         \
        LISTIFY(INST_ADDRESS_GPIOS(n), GPIO_CFG_INIT, (, ), n)};                                   \
                                                                                                   \
    static const struct adc_dt_spec kscan_adc_mux_channels_##n[] = {                               \
        LISTIFY(INST_ADC_INPUTS(n), ADC_CFG_INIT, (, ), n)};                                       \
                                                                                                   \
    static struct adc_sequence kscan_adc_mux_seqs_##n[INST_ADC_INPUTS(n)];                         \
    static uint16_t kscan_adc_mux_samples_##n[INST_ADC_INPUTS(n)];                                 \
    static bool kscan_adc_mux_matrix_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];              \
    static struct zmk_debounce_state                                                               \
        kscan_adc_mux_debounce_state_##n[INST_ADC_INPUTS(n) * INST_COLUMNS(n)];                    \
                                                                                                   \
    static struct kscan_adc_mux_data kscan_adc_mux_data_##n = {                                    \
        .seqs = kscan_adc_mux_seqs_##n,                                                            \
        .samples = kscan_adc_mux_samples_##n,                                                      \
        .matrix_state = kscan_adc_mux_matrix_state_##n,                                            \
        .debounce_state = kscan_adc_mux_debounce_state_##n,                                        \
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
        .press_threshold_mv = DT_INST_PROP(n, press_threshold_mv),                                 \
        .release_threshold_mv = DT_INST_PROP(n, release_threshold_mv),                             \
        .press_is_greater = DT_INST_PROP(n, press_is_greater),                                     \
        .debounce_config =                                                                         \
            {                                                                                      \
                .debounce_press_ms = DT_INST_PROP(n, debounce_press_ms),                           \
                .debounce_release_ms = DT_INST_PROP(n, debounce_release_ms),                       \
            },                                                                                     \
    };                                                                                             \
                                                                                                   \
    DEVICE_DT_INST_DEFINE(n, &kscan_adc_mux_init, NULL, &kscan_adc_mux_data_##n,                   \
                          &kscan_adc_mux_config_##n, POST_KERNEL, CONFIG_KSCAN_INIT_PRIORITY,      \
                          &kscan_adc_mux_api);

DT_INST_FOREACH_STATUS_OKAY(KSCAN_ADC_MUX_INIT)
