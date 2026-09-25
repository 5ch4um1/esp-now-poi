#!/usr/bin/env python3
"""
poi_send.py - the smallest possible ESP-NOW sender for the esp-now-poi sticks.

A single-file command line tool that streams raw pixels to the Poi firmware:

  * --solid  light every LED with one color (quick "does it work?" test)
  * --rainbow sweep a hue gradient across the whole strip, color cycles slowly
  * --cycle  show a rolling color cycle strip by strip

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
sudo python3 poi_send.py --interface wlan1 --rainbow --group-mask 0x3f
sudo python3 poi_send.py --interface wlan1 --cycle --leds 10 --fps 20
"""

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "lib", "ESPythoNOW"))
from ESPythoNOW import ESPythoNow

BROADCAST_MAC = "FF:FF:FF:FF:FF:FF"
PKT_TYPE_PIXEL = 0x01


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
                    help="LEDs per group in each frame")
    ap.add_argument("--brightness", type=float, default=0.6)
    ap.add_argument("--fps", type=int, default=30)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--solid", metavar="COLOR",
                      help="light every LED with one color and hold")
    mode.add_argument("--rainbow", action="store_true",
                      help="hue gradient across the strip, slowly cycling")
    mode.add_argument("--cycle", action="store_true",
                      help="rolling rainbow strip by strip")
    args = ap.parse_args()

    br = max(0.0, min(1.0, args.brightness))
    mask = args.group_mask & 0xFFFF
    frame = 1.0 / max(1, args.fps)

    espnow = ESPythoNow(interface=args.interface, channel=args.channel)
    print("ESPythoNOW ready on %s ch%d group mask 0x%x -> %s (%d LEDs)" %
          (args.interface, args.channel, mask, BROADCAST_MAC, args.leds))

    t = 0.0
    try:
        while True:
            if args.solid:
                rgb = [scale(color(args.solid), br)] * args.leds
            elif args.rainbow:
                # Static gradient, hue rotates slowly so you can see it moves.
                rgb = [scale(hsv2rgb((i * 255 // max(1, args.leds - 1)) + t * 2),
                             br) for i in range(args.leds)]
            else:  # --cycle
                rgb = []
                for i in range(args.leds):
                    rgb.append(scale(hsv2rgb((t * 40 + i * 255 // max(1, args.leds - 1)),
                                             br)))
            send_frame(espnow, mask, args.leds, rgb)
            time.sleep(frame)
            t += frame
    except KeyboardInterrupt:
        print("\nStopped.")
        try:
            send_frame(espnow, mask, args.leds,
                       [(0, 0, 0)] * args.leds)  # leave the strips dark
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())