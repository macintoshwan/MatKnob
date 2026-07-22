# MegKnob Hall voltage stream

The MegKnob acquisition firmware exposes only a USB CDC ACM virtual serial port. USB keyboard HID,
BLE HID, and every keymap binding are disabled so the acquisition device cannot send keys to the
host. Every completed mux scan sends all 24 voltage measurements in this order:

```text
U26 Y0..Y7, U27 Y0..Y7, U28 Y0..Y7
```

The wheel push position cycles the viewer mode:

```text
U26 -> U27 -> U28 -> all 24 channels -> U26
```

Sampling always includes all 24 channels. The mode only controls which curves the host displays.
Every data frame also contains the current mode, and a dedicated mode frame is sent immediately
after a wheel press, so reconnecting the host cannot leave it out of sync.

## Flash and run

Flash the generated firmware:

```text
app/build-megknob/zephyr/zmk.uf2
```

Install the host dependencies and start the PyQt5 oscilloscope-style viewer:

```powershell
python -m pip install -r tools/requirements-hall-viewer.txt
python tools/megknob_hall_viewer.py
```

Select the new MegKnob COM port and press **连接**. The baud-rate field is nominal for USB CDC;
the transport runs at USB speed. The viewer keeps five seconds of history and uses a 0-3300 mV
vertical scale. Its performance bar reports device scan rate, host receive rate, mean/min/max scan
period, period jitter, sequence-number frame loss, CRC errors, and serial throughput.

The toolbar provides run/stop capture, clear, 2/5/10/20-second timebases, and 2.0/2.5/3.3 V
ranges. The channel panel allows individual traces to be enabled. A wheel-button mode frame still
automatically selects U26, U27, U28, or all 24 channels.

For a repeatable headless 30-second performance baseline:

```powershell
python tools/megknob_hall_viewer.py --baseline COM12 --seconds 30
```

Close the graphical viewer first because Windows serial ports normally allow only one process to
open a COM port at a time. The command prints machine-readable JSON suitable for comparison after
changing `settle-time-us`.

## Wire format

Each little-endian binary frame is 62 bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 2 | magic `MK` |
| 2 | 1 | protocol version, currently and exclusively `3` |
| 3 | 1 | type: `1` data, `2` mode change, `3` periodic performance data |
| 4 | 1 | mode: `0` U26, `1` U27, `2` U28, `3` all |
| 5 | 1 | sample count: `24` data, `0` mode, `4` performance |
| 6 | 2 | sequence number |
| 8 | 4 | v3 `uint32` microsecond timestamp; wraps every about 71.6 minutes |
| 12 | 48 | data: 24 mV samples; performance: scan/address/ADC/process time in µs |
| 60 | 2 | CRC-16/CCITT-FALSE over bytes 0-59 |

If the host is slower than acquisition, firmware discards the oldest queued frame instead of
delaying ADC scanning.

Protocol v3 deliberately drops v1/v2 compatibility. Firmware accumulates short DWT deltas in a
64-bit nanosecond counter, then transmits its low 32-bit microsecond value. The host unwraps each
standard `uint32` rollover by adding `2^32` microseconds, so the displayed timeline remains
monotonic during long captures.

## Current acquisition timing

The current performance build uses:

```text
settle-time-us = 10
polling-interval-ms = 0
SAADC acquisition time = 3 us, 12-bit, no oversampling
one retained three-channel ADC batch read per mux address (dummy read disabled)
Gray-code mux order = 0, 1, 3, 2, 6, 7, 5, 4
continuous scan loop with one scheduler yield per complete scan
CRC-16/CCITT-FALSE uses a 16-entry nibble lookup table
```

The original baseline used 500 us settling, a 5 ms polling interval, and a dummy read, and measured
83.17 scans/s. The intermediate stable build used 200 us settling, a 1 ms polling interval, and a
dummy read. The 500 Hz candidate uses a dedicated ADC scan workqueue, so continuous scanning cannot
occupy ZMK's system workqueue. Keep the earlier configurations as references when validating it.
