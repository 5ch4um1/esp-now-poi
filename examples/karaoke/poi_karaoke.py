#!/usr/bin/env python3
"""
poi_karaoke.py - "Poi spinning karaoke" over ESP-NOW.

Plays a video and, in sync with its soundtrack:
  * no singing     -> streams music-reactive patterns to ALL poi sticks
  * somebody sings -> scrolls the lyric line as POV text

Uses the exact same ESP-NOW pixel packet format as the ESP32 firmware
(main/main.cpp / the original poi_show.py):

    byte 0      : type          = 0x01 (PKT_TYPE_PIXEL)
    bytes 1..2  : group bitmask (LSB first, 16 bit)
    byte 3      : frame_count   = 1
    byte 4      : pixel_count   = LEDs per strip in this packet
    bytes 5+    : RGB pixel data (pixel_count * 3 bytes)

One packet per frame is broadcast to every active strip at the full strip
height (20 px). The receiving firmware copies only as many pixels as each
strip physically has, so a single mask + pixel count works for every group.

Strips: groups 0,1 = 14px | groups 2,3 = 20px | groups 4,5 = 10px

Requirements
------------
* WiFi adapter with monitor mode support (ESPythoNOW sets it up itself)
* `ffmpeg`        - extracts the mono audio track for live music analysis
* `mpv` (optional)- plays the video; if absent the script falls back to a
                    wall-clock timer. Disable with --no-player.

Example
-------
sudo python3 poi_karaoke.py --interface wlan1 --channel 1 \
        --video Asereje.mp4 --lrc asereje.lrc --fps 240

Sync tweak: if lyrics appear early/late vs. the audio, use --offset (+/- seconds).
"""

import argparse
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
import wave

# Make the vendored ESPythoNOW library (../lib/ESPythoNOW) importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "lib", "ESPythoNOW"))

from ESPythoNOW import ESPythoNow

# ---------------------------------------------------------------- constants
BROADCAST_MAC = "FF:FF:FF:FF:FF:FF"
PKT_TYPE_PIXEL = 0x01
GROUP_LEDS = [14, 14, 20, 20, 10, 10]   # strips: top/mid/bot rows
NUM_GROUPS = 6
LED_H = 20                              # tallest strip -> banner height

# ESP-NOW frames are audio/video-free, channel must match the devices (firmware: 1)

# ---------------------------------------------------------------- 5x7 font
# 26 uppercase letters + digits + a bit of punctuation. 7 rows, 5 bits/row,
# bit 4 = leftmost pixel. Same glyphs as the firmware text mode.
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

# ---------------------------------------------------------------- helpers
def normalize_lyrics(text):
    """Fold accents/lowercase onto the ASCII font (e.g. é -> E)."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.upper()


def parse_lrc(path):
    """Return [(start_s, end_s, text), ...] sorted by time. '' = instrumental."""
    raw = []
    pat = re.compile(r"\[(\d+):(\d+)(?:[.:](\d+))?\]")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            tags = list(pat.finditer(line))
            if not tags:
                continue
            text = line[tags[-1].end():].strip()
            for m in tags:
                mm = int(m.group(1))
                ss = int(m.group(2))
                frac = int(m.group(3)) if m.group(3) else 0
                if len(m.group(3)) >= 2:
                    frac = frac / (10 ** len(m.group(3)))
                else:
                    frac = frac / 10.0
                raw.append((mm * 60 + ss + frac, text))
    if not raw:
        return []
    raw.sort()
    segs = []
    for i, (st, tx) in enumerate(raw):
        en = raw[i + 1][0] if i + 1 < len(raw) else st + 30.0
        segs.append((st, en, tx))
    return segs


# ---------------------------------------------------------------- banner
def flip_cols(ch):
    """5x7 glyph -> a 20-tall column list for each of its 5 columns.

    Columns are sent upside down (LED 0 = bottom of the glyph, glyph row 6
    on top) to match how the strips are physically mounted.
    """
    g = GLYPHS.get(ch, GLYPHS[" "])
    cols = []
    for gx in range(5):
        col = [0] * LED_H
        for r in range(LED_H):
            src = (LED_H - r) * 7 // (LED_H + 1)   # invert vertical orientation
            col[r] = (g[src] >> (4 - gx)) & 1
        cols.append(col)
    return cols


def build_banner(text):
    """Full scrolling banner for one lyric line. Returns list of columns."""
    cols = []
    for _ in range(12):                      # lead-in blank space
        cols.append([0] * LED_H)
    for ch in text:
        for col in flip_cols(ch):            # each glyph col drawn 2 wide
            cols.append(col)
            cols.append(col)
        cols.append([0] * LED_H)             # spacing between chars
        cols.append([0] * LED_H)
    return cols


# ---------------------------------------------------------------- audio
def extract_wav(video, wav_path):
    """Extract mono 8 kHz s16 audio for live energy analysis."""
    if not os.path.exists(wav_path):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video,
                        "-vn", "-ac", "1", "-ar", "8000",
                        "-sample_fmt", "s16", wav_path], check=True)


class WavEnergy:
    def __init__(self, path):
        w = wave.open(path, "rb")
        self.rate = w.getframerate()
        n = w.getnframes()
        import array
        self.samples = array.array("h")
        self.samples.frombytes(w.readframes(n))
        w.close()
        self.duration = n / self.rate
        self.win = max(1, self.rate // 20)   # ~50 ms window
        self.smooth = 0.0

    def energy_at(self, t):
        i = int(max(0.0, t) * self.rate)
        seg = self.samples[i: i + self.win]
        if not len(seg):
            return 0.0
        s = sum(x * x for x in seg) / len(seg)
        e = math.sqrt(s) / 32768.0
        self.smooth = self.smooth * 0.7 + e * 0.3
        return self.smooth


class PseudoEnergy:
    """Keeps the visuals moving when there is no audio to analyze."""
    duration = 99999.0

    def energy_at(self, t):
        return 0.25 + 0.25 * math.sin(t * 2.2) + 0.25 * math.sin(t * 0.5)


# ---------------------------------------------------------------- video sync
def launch_player(video):
    """Play the video + its soundtrack in the desktop user's session.

    When run under sudo (needed for monitor mode) an mpv child would start as
    root and lose access to PulseAudio/PipeWire (hence "no music") and to the
    X/Wayland display. So if we are root we re-spawn mpv as the original user,
    carrying its runtime dir. On headless setup we use a null video output so
    the audio still plays.
    """
    sock = "/tmp/mpvpoi.sock"
    try:
        try:
            os.unlink(sock)
        except OSError:
            pass

        env = dict(os.environ)
        uid = None
        if os.geteuid() == 0:
            su = os.environ.get("SUDO_USER")
            sui = os.environ.get("SUDO_UID")
            if su and sui:
                uid = int(sui)
                env["XDG_RUNTIME_DIR"] = "/run/user/%d" % uid
                env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/%d/bus" % uid
                env["HOME"] = "/home/%s" % su
                # Only claim the desktop's X display if we can actually auth.
                if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
                    xauth = "/home/%s/.Xauthority" % su
                    if os.path.exists("/tmp/.X11-unix/X0") and os.path.exists(xauth):
                        env["DISPLAY"] = ":0"
                        env["XAUTHORITY"] = xauth

        has_display = bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
        cmd = ["mpv", "--no-terminal", "--input-ipc-server=" + sock]
        if has_display:
            cmd.append("--fs")
        else:
            # No reachable video session: keep the soundtrack, drop the picture.
            cmd.append("--vo=null")
        cmd.append(video)

        proc = subprocess.Popen(cmd, env=env, user=uid)
        return proc, sock
    except (FileNotFoundError, PermissionError, OSError):
        print("mpv not found / can't start as user - falling back to "
              "wall-clock sync (use --no-player to silence this).")
        return None, None


class Sync:
    """Follows mpv playback for tight sync; wall-clock fallback otherwise.

    Polls mpv only a few times per second and interpolates in between, so the
    100+ fps render loop never blocks on the IPC socket (the old code did a
    blocking recv with a 50 ms timeout every single frame, which stalled the
    loop whenever mpv sent an unsolicited event instead of the reply).
    """

    def __init__(self, sock, no_player=False, offset=0.0, poll=0.05):
        self.sock = sock
        self.offset = offset
        self.fd = None
        self.t0 = time.monotonic()
        self.mode = "mono"
        self.poll = poll
        self.synced_t = None        # last media time reported by mpv
        self.synced_at = 0.0        # monotonic() when that time was read
        self.last_poll = 0.0
        if sock and not no_player:
            self.mode = "mpv"

    def _talk(self):
        """Ask mpv for time-pos, return the float or None (skip events)."""
        try:
            if self.fd is None:
                self.fd = socket.socket(socket.AF_UNIX)
                self.fd.connect(self.sock)
                self.fd.settimeout(self.poll)
            self.fd.sendall(b'{"command":["get_property","time-pos"]}\n')
            buf = b""
            while True:
                try:
                    chunk = self.fd.recv(4096)
                except socket.timeout:
                    return None
                if not chunk:
                    return None
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if "data" in obj or "error" in obj:
                        return obj
                    # unsolicited mpv event notification -> keep reading
        except Exception:
            try:
                self.fd.close()
            except Exception:
                pass
            self.fd = None
        return None

    def now(self):
        if self.mode != "mpv":
            return time.monotonic() - self.t0 + self.offset
        mono = time.monotonic()
        if self.synced_t is None or (mono - self.last_poll) >= self.poll:
            self.last_poll = mono
            obj = self._talk()
            if obj is not None and isinstance(obj.get("data"), (int, float)):
                self.synced_t = float(obj["data"])
                self.synced_at = time.monotonic()
        if self.synced_t is not None:
            return self.synced_t + (time.monotonic() - self.synced_at) + self.offset
        return mono - self.t0 + self.offset


# ---------------------------------------------------------------- patterns
def hsv2rgb(h):
    h = int(h) & 255
    s = h * 3
    if s < 255:
        return (255 - s, s, 0)
    if s < 510:
        s -= 255
        return (0, 255 - s, s)
    s -= 510
    return (s, 0, 255 - s)


def pattern_bass(t, e):
    b = 0.10 + 0.90 * e
    r, g, b2 = hsv2rgb(t * 40)
    px = [(int(r * b), int(g * b), int(b2 * b))] * LED_H
    return px


def pattern_spectrum(t, e):
    px = []
    for i in range(LED_H):
        r, g, b = hsv2rgb(t * 30 + i * 14 + e * 70)
        wob = 0.2 + 1.3 * e * (0.5 + 0.5 * math.sin(t * 9 + i))
        wob = min(1.0, wob)
        px.append((int(r * wob), int(g * wob), int(b * wob)))
    return px


def pattern_bounce(t, e):
    pos = int((t * (4 + 10 * e)) % (LED_H * 2))
    px = []
    for i in range(LED_H):
        d = abs(i - pos) / 4.0
        glow = max(0.0, 1.0 - d)
        b = 0.05 + 0.95 * glow * e
        r, g, blue = hsv2rgb(t * 60 + i * 8)
        px.append((int(r * b), int(g * b), int(blue * b)))
    return px


PATTERNS = [pattern_bass, pattern_spectrum, pattern_bounce]


def music_column(t, e):
    return PATTERNS[int(t) % len(PATTERNS)](t, min(1.0, e))


# ---------------------------------------------------------------- packets
def send_packet(espnow, mask, px, rgb):
    if px <= 0:
        return
    pkt = bytes([PKT_TYPE_PIXEL, mask & 0xFF, (mask >> 8) & 0xFF, 1, px])
    espnow.send(BROADCAST_MAC, pkt + b"".join(bytes(p) for p in rgb))


def main():
    ap = argparse.ArgumentParser(description="Poi spinning karaoke over ESP-NOW")
    ap.add_argument("--interface", required=True, help="wifi IF in monitor mode")
    ap.add_argument("--video", default="Asereje.mp4")
    ap.add_argument("--lrc", default="asereje.lrc")
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--fps", type=int, default=240)
    ap.add_argument("--brightness", type=float, default=0.6)
    ap.add_argument("--energy", type=float, default=3.5, help="music sensitivity")
    ap.add_argument("--offset", type=float, default=0.0, help="lyric sync +/-sec")
    ap.add_argument("--text-speed", type=float, default=1.0,
                    help="scroll-rate multiplier (fps has no effect on text speed)")
    ap.add_argument("--group-mask", type=lambda s: int(s, 0), default=0x0F,
                    help="bitmask of strips to light (hex). default 0x0F = "
                         "groups 0-3; groups 4,5 (10px) are not in use")
    ap.add_argument("--no-player", action="store_true",
                    help="don't launch mpv, use a wall-clock timer")
    args = ap.parse_args()

    # LRC timeline
    segs = parse_lrc(args.lrc)
    if not segs:
        print("No usable lyric timestamps in %s" % args.lrc)
        return 1
    print("Loaded %d lyric segments" % len(segs))

    # Audio energy (extract a mono wav if needed)
    wav_path = os.path.splitext(args.video)[0] + "_mono.wav"
    energy = None
    try:
        extract_wav(args.video, wav_path)
        energy = WavEnergy(wav_path)
        print("Audio energy ready (%.1f s @ %d Hz)" % (energy.duration, energy.rate))
    except Exception as ex:
        print("Audio analysis unavailable (%s); using pseudo energy" % ex)
        energy = PseudoEnergy()

    # Video player + sync
    proc, sock = (None, None) if args.no_player else launch_player(args.video)
    sync = Sync(sock, no_player=args.no_player, offset=args.offset)

    # ESP-NOW: default scapy TX path. It is slower than the raw socket path but
    # self-throttles, which keeps monitoring radio from being flooded (raw +
    # high fps previously saturated the kernel buffer and killed streaming).
    espnow = ESPythoNow(interface=args.interface, channel=args.channel)
    print("ESPythoNOW ready on %s ch%d -> %s" %
          (args.interface, args.channel, BROADCAST_MAC))

    send_mask = args.group_mask & 0xFFFF
    send_px = LED_H  # one 20px frame covers every strip (firmware trims it)
    br = max(0.0, min(1.0, args.brightness))

    # Banner + scroll state for the active lyric
    active_key = None
    banner = None
    banner_ts = 0.0
    cols_per_s = 1.0

    frame = 1.0 / args.fps
    last = time.monotonic()

    try:
        while True:
            t = sync.now()
            if energy.duration is not None and t > energy.duration + 2:
                print("End of playback. Bye!")
                break

            e = energy.energy_at(t) * args.energy
            e = max(0.0, min(1.0, e))

            # Find current lyric segment (need its length for the scroll pace)
            cur = None
            for st, en, tx in segs:
                if st <= t < en:
                    cur = (st, en, tx)
                    break

            if cur is not None and cur[2]:
                st, en, tx = cur
                key = (round(st, 2), tx)
                if key != active_key:
                    active_key = key
                    banner = build_banner(normalize_lyrics(tx))
                    banner_ts = t
                    cols_per_s = args.text_speed * len(banner) / max(en - st, 1.2)

                scroll = int((t - banner_ts) * cols_per_s) % len(banner)
                colpix = banner[scroll]

                # One packet -> every masked strip shows the same frame.
                col = [((int(255 * br) if colpix[i] else 0),) * 3
                       for i in range(send_px)]
                send_packet(espnow, send_mask, send_px, col)
            else:
                active_key = None
                col = music_column(t, e)
                send_packet(espnow, send_mask, send_px, col[:send_px])

            # Pace the loop
            now = time.monotonic()
            wait = frame - (now - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if proc is not None:
            proc.terminate()

    return 0


if __name__ == "__main__":
    sys.exit(main())