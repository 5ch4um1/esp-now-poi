# firmware

ESP32-C3 receiver firmware for the Poi sticks. One copy per stick, flashed from
this same folder — the group a stick belongs to is set with
`DEVICE_GROUP_ID` in `main/main.c`.

## Features

* Listens for broadcast ESP-NOW pixel packets on WiFi channel 1
  (see [`../README.md`](../README.md) for the packet format).
* Filters packets by group bitmask; renders up to 20 LEDs on a WS2812 strip
  via the RMT peripheral.
* Keeps the **latest** received frame in a double-buffered latch — a lost
  packet just repeats the last frame (non-blocking and latency-free for POV).
* **Light sleep**: short button press turns off the radio and the 5V rail
  (GPIO7) and puts the ESP32-C3 to sleep; pressing the button again wakes it
  and reconnects to the stream.

## Pins

| Pin   | Function                                  |
|-------|-------------------------------------------|
| GPIO3 | Button (pull-up, active low, wake source) |
| GPIO6 | WS2812 LED data                           |
| GPIO7 | 5V regulator enable (off during sleep)    |

## Build & flash

Prerequisite: ESP-IDF v6.0 (ESP32-C3 target).

```bash
idf.py set-target esp32c3
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

The partition table (`partitions.csv`) only allocates what the firmware needs;
`sdkconfig.defaults` carries the recommended settings (WiFi on, BT off,
160 MHz, 1 kHz tick).

## Send a test frame

From the repo root, the quickest end-to-end check is the simple example:

```bash
sudo python3 examples/simple/poi_send.py --interface wlan1 --solid green --group-mask 0x04
```