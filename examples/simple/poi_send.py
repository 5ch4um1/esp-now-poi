#!/usr/bin/env python3
"""
poi_send.py - the smallest possible ESP-NOW sender for the esp-now-poi sticks.

A single-file command line tool that streams raw pixels to the Poi firmware:

  * --solid    light every LED with one color (quick "does it work?" test)
  * --rainbow  sweep a hue gradient across the whole strip, color cycles slowly
  * --cycle    show a rolling color cycle strip by strip
  * --text     scroll a text message as a POV banner, in one color or rainbow

It broadcasts on the WiFi channel the sticks listen on (channel 1 by default),
using the exact ESP-NOW pixel packet format documented in the repo README:

    byte 0      : type           = 0x01 (PKT_TYPE_PIXEL)
    bytes 1..2  : group bitmask  (16 bit, LSB first)
    byte 3      : frame_count    = 1
    byte 4      : pixel_count    = LEDs to fill
    bytes 5+    : RGB data (pixel_count * 3 bytes)

Why root? The ESPythoNOW library puts the interface into monitor mode (raw
802.11 injection), which needs root. See README within this folder.

Example
-------
sudo python3 poi_send.py --interface wlan1 --solid red
sudo python3 poi_send.py --interface wlan1 --text "HELLO POI" --color red
sudo python3 poi_send.py --interface wlan1 --text "RAINBOW" --text-rainbow
sudo python3 poi_send.py --interface wlan1 --leds 24 --text "BIG"
sudo python3 poi_send.py --interface wlan1 --leds 10 --font 3x5 --text "TINY"

--leds sets the strip height; --text scales the font to fill it, and --font
picks the base glyph set (default 5x7, also 5x5 and 3x5).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "lib", "ESPythoNOW"))
from ESPythoNOW import ESPythoNow

BROADCAST_MAC = "FF:FF:FF:FF:FF:FF"
PKT_TYPE_PIXEL = 0x01

# ---------------------------------------------------------------- fonts
# Bitmap fonts. GLYPHS is the base 5x7 set (7 rows, 5 bits/row, bit 4 =
# leftmost pixel, same glyphs as the karaoke example). 5x5 is a compact
# derivation and 3x5 a tiny 3-wide font for very short strips. Every font is
# scaled to any strip height at render time (see glyph_cols), so any
# --leds / strip resolution can be used.
GLYPHS = {
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18),
    ",": (0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x08),
    "!": (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "'": (0x04, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00),
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}

# 5x5 = top five rows of the 5x7 set (compact, same width).
GLYPHS_5X5 = {ch: tuple(rows[:5]) for ch, rows in GLYPHS.items()}

# 3x5 = tiny 3-bit-wide font for very low resolution strips. Rows are 3 bits,
# bit 2 = leftmost pixel.
GLYPHS_3X5 = {
    "A": (2, 5, 7, 5, 5), "B": (7, 5, 7, 5, 7), "C": (7, 4, 4, 4, 7),
    "D": (7, 5, 5, 5, 7), "E": (7, 4, 7, 4, 7), "F": (7, 4, 7, 4, 4),
    "G": (7, 4, 5, 5, 3), "H": (5, 5, 7, 5, 5), "I": (7, 2, 2, 2, 7),
    "J": (1, 1, 1, 5, 3), "K": (5, 5, 6, 5, 5), "L": (4, 4, 4, 4, 7),
    "M": (5, 7, 7, 5, 5), "N": (5, 6, 7, 3, 5), "O": (2, 5, 5, 5, 2),
    "P": (7, 5, 7, 4, 4), "Q": (2, 5, 5, 7, 3), "R": (7, 5, 7, 6, 5),
    "S": (7, 4, 3, 1, 7), "T": (7, 2, 2, 2, 2), "U": (5, 5, 5, 5, 7),
    "V": (5, 5, 5, 5, 2), "W": (5, 5, 7, 7, 5), "X": (5, 5, 2, 5, 5),
    "Y": (5, 5, 2, 2, 2), "Z": (7, 1, 2, 4, 7),
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7),
    "3": (7, 1, 3, 1, 7), "4": (5, 5, 7, 1, 1), "5": (7, 4, 7, 1, 7),
    "6": (7, 4, 7, 5, 7), "7": (7, 1, 2, 2, 2), "8": (7, 5, 7, 5, 7),
    "9": (7, 5, 7, 1, 7),
    "-": (0, 0, 7, 0, 0), ".": (0, 0, 0, 0, 2), ",": (0, 0, 0, 2, 4),
    "!": (2, 2, 2, 0, 2), "?": (7, 1, 2, 0, 2), "'": (2, 4, 0, 0, 0),
    " ": (0, 0, 0, 0, 0),
}

# One entry per selectable font. "repeat" expands each glyph column
# horizontally (POV pseudo-resolution), "space" is blank cols between chars.
FONTS = {
    "5x7":  {"w": 5, "h": 7, "repeat": 2, "space": 2, "glyphs": GLYPHS},
    "5x5":  {"w": 5, "h": 5, "repeat": 2, "space": 2, "glyphs": GLYPHS_5X5},
    "3x5":  {"w": 3, "h": 5, "repeat": 2, "space": 2, "glyphs": GLYPHS_3X5},
}


# ---------------------------------------------------------------- helpers
def color(name_or_hex):
    """'red' / 'blue' / '#ff8800' etc -> (r, g, b)."""
    named = {
        "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
        "white": (255, 255, 255), "warm": (255, 180, 90),
        "purple": (160, 0, 255), "cyan": (0, 255, 255), "yellow": (255, 255, 0),
        "off": (0, 0, 0),
    }
    v = name_or_hex.lower()
    if v in named:
        return named[v]
    if v.startswith("#") and len(v) == 7:
        return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
    raise SystemExit("unknown color %r (try 'red', '#ff8800', ...)" % name_or_hex)


def scale(rgb, br):
    return tuple(int(c * br) for c in rgb)


def hsv2rgb(h):
    """6-stop hue wheel -> (r,g,b), h in 0..255."""
    h = int(h) & 255
    if h < 43:
        return (255, int(h * 6), 0)
    if h < 85:
        h -= 43
        return (int(255 - h * 6), 255, 0)
    if h < 128:
        h -= 85
        return (0, 255, int(h * 6))
    if h < 170:
        h -= 128
        return (0, int(255 - h * 6), 255)
    if h < 213:
        h -= 170
        return (int(h * 6), 0, 255)
    h -= 213
    return (255, 0, int(255 - h * 6))


# ---------------------------------------------------------------- text banner
def glyph_cols(ch, font, height):
    """Glyph -> one column list per horizontal pixel of the glyph.

    The glyph bitmap is scaled to any strip height (font size follows the
    strip). Columns are sent upside down (LED 0 = bottom of the glyph) to
    match how the strips are physically mounted.
    """
    w, h = font["w"], font["h"]
    g = font["glyphs"].get(ch.upper(), font["glyphs"][" "])
    cols = []
    for gx in range(w):
        col = [0] * height
        if height > 1:
            for r in range(height):
                src = (height - 1 - r) * (h - 1) // (height - 1)  # invert, stretch
                col[r] = (g[src] >> (w - 1 - gx)) & 1
        cols.append(col)
    return cols


def build_banner(text, font, height):
    """Full scrolling banner for one text line. Returns list of columns."""
    w, repeat, space = font["w"], font["repeat"], font["space"]
    cols = []
    for _ in range(12):                      # lead-in blank space
        cols.append([0] * height)
    for ch in text.upper():
        for col in glyph_cols(ch, font, height):
            for _ in range(repeat):          # each glyph col drawn N wide
                cols.append(col)
        for _ in range(space):               # spacing between chars
            cols.append([0] * height)
    return cols


# ---------------------------------------------------------------- sending
def send_frame(espnow, mask, leds, rgb):
    """One broadcast packet carrying the whole strip frame."""
    pkt = bytes([PKT_TYPE_PIXEL, mask & 0xFF, (mask >> 8) & 0xFF, 1, leds])
    espnow.send(BROADCAST_MAC, pkt + b"".join(bytes(c) for c in rgb))


def main():
    ap = argparse.ArgumentParser(description="Minimal ESP-NOW Poi sender")
    ap.add_argument("--interface", required=True,
                    help="WiFi interface, will be put into monitor mode")
    ap.add_argument("--channel", type=int, default=1,
                    help="WiFi channel the sticks listen on")
    ap.add_argument("--group-mask", type=lambda s: int(s, 0), default=0x01,
                    help="bitmask of stick groups (hex ok), default 0x01")
    ap.add_argument("--leds", type=int, default=20,
                    help="LEDs per group in each frame (also the banner "
                         "height for --text)")
    ap.add_argument("--font", choices=sorted(FONTS), default="5x7",
                    help="bitmap font for --text (default 5x7; 5x5 compact, "
                         "3x5 for very short strips)")
    ap.add_argument("--brightness", type=float, default=0.6)
    ap.add_argument("--fps", type=int, default=30)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--solid", metavar="COLOR",
                      help="light every LED with one color and hold")
    mode.add_argument("--rainbow", action="store_true",
                      help="hue gradient across the strip, slowly cycling")
    mode.add_argument("--cycle", action="store_true",
                      help="rolling rainbow strip by strip")
    mode.add_argument("--text", metavar="STRING",
                      help="scroll a text message as a POV banner")
    ap.add_argument("--color", metavar="COLOR", default="white",
                    help="color for --text (default white)")
    ap.add_argument("--text-rainbow", action="store_true",
                    help="rainbow gradient across the --text banner")
    ap.add_argument("--text-rainbow-rate", type=float, default=10.0,
                    help="--text-rainbow color drift, independent of text scroll "
                         "(hue-steps per second, default 10)")
    ap.add_argument("--text-speed", type=float, default=1.0,
                    help="--text scroll rate in characters per second")
    args = ap.parse_args()

    br = max(0.0, min(1.0, args.brightness))
    mask = args.group_mask & 0xFFFF
    frame = 1.0 / max(1, args.fps)
    leds = max(1, min(args.leds, 81))        # 245 payload bytes / 3
    font = FONTS[args.font]
    COLS_PER_CHAR = font["w"] * font["repeat"] + font["space"]

    espnow = ESPythoNow(interface=args.interface, channel=args.channel)
    print("ESPythoNOW ready on %s ch%d group mask 0x%x -> %s (%d LEDs)" %
          (args.interface, args.channel, mask, BROADCAST_MAC, leds))

    banner = build_banner(args.text, font, leds) if args.text else None
    col_idx = 0.0
    t = 0.0
    try:
        while True:
            if args.solid:
                rgb = [color(args.solid)] * leds
            elif args.text:
                colpix = banner[int(col_idx) % len(banner)]
                if args.text_rainbow:
                    # Gradient keeps riding ON the banner (col_idx), but the
                    # whole gradient also drifts with wall-clock time, so a
                    # letter isn't stuck on one color across banner loops.
                    hue = (int(col_idx) * 4 + int(t * args.text_rainbow_rate)) & 255
                    base = hsv2rgb(hue)
                else:
                    base = color(args.color)
                rgb = [(base if colpix[i] else (0, 0, 0)) for i in range(leds)]
                col_idx += args.text_speed * COLS_PER_CHAR * frame
            elif args.rainbow:
                # Static gradient, hue rotates slowly so you can see it moves.
                rgb = [hsv2rgb((i * 255 // max(1, leds - 1)) + t * 2)
                       for i in range(leds)]
            else:  # --cycle
                rgb = [hsv2rgb(t * 40 + i * 255 // max(1, leds - 1))
                       for i in range(leds)]
            # Brightness is applied once, as the last step, for every mode.
            rgb = [scale(c, br) for c in rgb]
            send_frame(espnow, mask, leds, rgb)
            time.sleep(frame)
            t += frame
    except KeyboardInterrupt:
        print("\nStopped.")
        try:
            send_frame(espnow, mask, leds, [(0, 0, 0)] * leds)  # strips dark
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())