# simple

The smallest possible sender for the esp-now-poi sticks. One file, no video,
no audio, no lyrics — just say what you want to see and it streams it.

```bash
sudo python3 poi_send.py --interface wlan1 --solid green --group-mask 0x3f
```

## Requirements

* A WiFi adapter in monitor mode (set up automatically by ESPythoNOW)
* Python 3 + `scapy`:

```bash
python3 -m pip install -r ../lib/ESPythoNOW/requirements.txt
```

## Modes

| Flag                    | Effect                                        |
|-------------------------|-----------------------------------------------|
| `--solid COLOR`         | every LED one color and hold (the sanity test)|
| `--rainbow`             | hue gradient across the strip, slowly cycling |
| `--cycle`               | rolling rainbow, strip by strip               |

## Options

* `--interface` (required) — WiFi interface name, e.g. `wlan1`
* `--channel` — channel the sticks listen on (default `1`)
* `--group-mask` — bitmask of target groups (default `0x01`, hex OK)
* `--leds` — LEDs per strip in the frame (default `20`)
* `--brightness` — 0.0 … 1.0 brightness scale (default `0.6`)
* `--fps` — frame rate in frames per second (default `30`)

Examples:

```bash
# Light group 0 red at full brightness
sudo python3 poi_send.py --interface wlan1 --solid red --group-mask 0x01 --brightness 1.0

# Rainbow on all six groups, 10px strips
sudo python3 poi_send.py --interface wlan1 --rainbow --group-mask 0x3f --leds 10

# Rolling rainbow at a fast frame rate
sudo python3 poi_send.py --interface wlan1 --cycle --fps 120
```

Ctrl-C leaves the strips dark.

## How it fits

This is a deliberate contrast to `../karaoke/`: the karaoke script shows what is
possible once you can drive the sticks in sync with something real (audio +
video). This one shows the bare minimum — a handful of frames broadcast at the
right channel — and is a good first test that your monitor-mode WiFi card can
talk to the sticks at all.