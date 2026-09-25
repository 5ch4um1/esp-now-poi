# esp-now-poi

Wireless pixel streaming for Poi sticks over **ESP-NOW** — no BLE, no MQTT, no
cloud. Broadcast RGB frames from any WiFi-equipped computer straight onto
WS2812 POV strips.

This repository contains:

| Path                    | What it is                                        |
|-------------------------|---------------------------------------------------|
| `firmware/`             | ESP32-C3 firmware for the Poi sticks (receiver)   |
| `examples/`             | Linux sender software (see below)                 |

## How it works

The system is send-and-forget: it has no connection, no pairing, and no state.

**Sender** (a Linux computer, or soon our smartwatch) puts a WiFi adapter into
monitor mode, crafts an 802.11 frame containing a 5-byte header plus raw RGB
pixel data, and broadcasts it on channel 1.

**Sticks** (ESP32-C3 + WS2812 strip) listen to every 802.11 frame, pick out the
ESP-NOW pixel packets, keep only those aimed at their group, and render them to
the LED strip at full speed. The firmware holds the **latest** frame in a
double buffered latch, so a lost radio packet simply means the previous frame
shows for one frame longer — exactly what a spinning POV stick wants: repetition,
not latency.

Every stick carries a `DEVICE_GROUP_ID` (0–5). A sender can light up any subset
of the six sticks by setting the matching bits in the group bitmask — so two
spinners can be driven separately from a single transmitter, or all at once.

### Power & control on the stick

* Single button (GPIO3): **short press → light sleep** (radio and the 5V rail
  via GPIO7 are both shut down for long battery life), **press again → wake**
  and reconnect to the stream.
* LED data on GPIO6 (WS2812).

## Communication protocol

ESP-NOW is a raw, connectionless protocol from 51-byte and e.g. 250-byte
802.11 action frames. We use the 250-byte variant, unencrypted, to broadcast
pixel data with no acknowledgement:

| Offset | Size | Field               | Meaning                                        |
|-------:|-----:|---------------------|------------------------------------------------|
| `0`    | 1    | `type`              | `0x01` = pixel stream                          |
| `1`    | 2    | `group_mask`        | bitmask of target groups, LSB first (16 bit)   |
| `3`    | 1    | `frame_count`       | number of RGB frames in this packet            |
| `4`    | 1    | `pixels_per_frame`  | LEDs per frame (`pixels_per_frame * 3` bytes)  |
| `5+`   | n    | `data`              | `frame_count × pixels_per_frame × 3` RGB bytes |

* **Address** – broadcast (`FF:FF:FF:FF:FF:FF`) on WiFi **channel 1**, sender
  and firmware must agree on the channel.
* **Frame size** – a packet may carry at most 245 payload bytes, so a 20-LED
  frame fits 4 per packet (`(250 − 5) / (20 × 3)`).
* **Group masking** – a stick lights a packet only if `group_mask & (1 <<
  DEVICE_GROUP_ID)` is set. Different sticks may have different LED counts
  (14 / 20 / 10); the firmware trims each frame to its own strip length, so one
  sender with one mask can drive every stick at once.
* **Delivery** – fire-and-forget. The receiver keeps the newest frame and
  repeats it while nothing new arrives. There is no retry; a lost packet is
  simply never displayed.

## Examples (sender software)

The `examples/` folder contains ready-to-use **command line programs** that
stream frames to the Poi from a Linux computer. To use them the computer must
have a **WiFi interface that supports monitor mode**, and the scripts are run
with `sudo` because the ESPythoNOW library switches the interface into monitor
mode (raw 802.11 injection) itself.

* **`examples/simple/`** – the smallest possible sender. Light the sticks with
  a color (`--solid red`), or run a rainbow sweep (`--rainbow` / `--cycle`).
  The first thing to try.
* **`examples/karaoke/`** – "Poi spinning karaoke": plays a video and, in sync
  with its soundtrack, either streams music-reactive patterns to all sticks or
  (when someone sings) scrolls the lyric line as POV text past your eyes.

There is also **coming soon** an **ESP32 smartwatch firmware** at
[https://github.com/5ch4um1/esp32-smartwatch-firmware](https://github.com/5ch4um1/esp32-smartwatch-firmware):
an ESP32-C6 based smartwatch with an AMOLED display that acts as a battery
powered, wearable ESP-NOW sender with group-aware modes, audio-reactive modes
and a screen-off sleep page.

## Building the firmware

Requires [ESP-IDF v6.0](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/get-started/)
with the ESP32-C3 target and the `led_strip` component (resolved automatically):

```bash
cd firmware
idf.py set-target esp32c3
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

## License

MIT — see [LICENSE](LICENSE). The vendored `examples/lib/ESPythoNOW` sender
library is (c) 2024 ChuckMash, also MIT.