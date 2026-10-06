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
| `--text "MSG"`          | scroll a text message as a POV banner         |

## Options

* `--interface` (required) — WiFi interface name, e.g. `wlan1`
* `--channel` — channel the sticks listen on (default `1`)
* `--group-mask` — bitmask of target groups (default `0x01`, hex OK)
* `--leds` — LEDs per strip in the frame (default `20`). For `--text` this is
  also the banner height: the font is scaled to fill whatever strip height
  you send, so `--leds` works for 10px, 14px, 20px, 24px strips, etc.
* `--font` — which bitmap glyph set `--text` uses (default `5x7`). Options:
  * `5x7` — the classic font, same glyphs as the karaoke example
  * `5x5` — compact 5-row version of the same font
  * `3x5` — tiny 3-pixel-wide font that stays legible on very short strips
* `--brightness` — 0.0 … 1.0 brightness scale (default `0.6`), applied to
  every mode as the last step before sending
* `--fps` — frame rate in frames per second (default `30`)

Text mode options:

* `--color COLOR` — text color (default `white`; names like `red`, `#ff8800`)
* `--text-rainbow` — rainbow gradient that flows along the text banner
* `--text-rainbow-rate N` — how fast the rainbow colors drift, independent of
  text scroll (hue-steps per second, default `10`; higher = colors change faster)
* `--text-speed N` — scroll rate in characters per second (default `1.0`)

Examples:

```bash
# Light group 0 red at full brightness
sudo python3 poi_send.py --interface wlan1 --solid red --group-mask 0x01 --brightness 1.0

# Rainbow on all six groups, 10px strips
sudo python3 poi_send.py --interface wlan1 --rainbow --group-mask 0x3f --leds 10

# 24px strips: the 5x7 font scales up to fill the whole banner
sudo python3 poi_send.py --interface wlan1 --text "BIG" --leds 24

# Very short strip: pick the tiny font so text stays readable
sudo python3 poi_send.py --interface wlan1 --text "TINY" --leds 10 --font 3x5

# Rolling rainbow at a fast frame rate
sudo python3 poi_send.py --interface wlan1 --cycle --fps 120

# Scroll a message in red
sudo python3 poi_send.py --interface wlan1 --text "HELLO POI" --color red

# Scroll a message in flowing rainbow colors
sudo python3 poi_send.py --interface wlan1 --text "RAINBOW" --text-rainbow
```

Ctrl-C leaves the strips dark. Text is sent **upside down** (LED 0 shows the
bottom of a glyph) to match how the strips are physically mounted — same
orientation as the karaoke example.

## Mixed strip lengths

Every frame is broadcast and the firmware clips it to each stick's own
length, so one sender can drive a mix of strip sizes at once. Because the
frame is clipped *after* it arrives, each stick always shows the **top**
of the banner. To size text for a mixed fleet:

* run the sender with `--leds` = the *longest* strip in the group, so the
  text isn't clipped mid-glyph on the longest stick (`--font 3x5` helps the
  clipped shorter sticks stay legible), or
* split groups by length and run one sender per group with matching `--leds`
  (each group needs a distinct `DEVICE_GROUP_ID` in the firmware and its own
  `--group-mask`).

Also remember: a stick with a 24-LED strip must be flashed with
`MAX_LEDS 24` in the firmware, otherwise it clips the frame at its compile-time
`MAX_LEDS`.

## How it fits

This is a deliberate contrast to `../karaoke/`: the karaoke script shows what is
possible once you can drive the sticks in sync with something real (audio +
video). This one shows the bare minimum — a handful of frames broadcast at the
right channel — and is a good first test that your monitor-mode WiFi card can
talk to the sticks at all.