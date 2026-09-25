# karaoke

"Poi spinning karaoke" over ESP-NOW: play a video, and either stream
**music-reactive patterns** across all sticks, or — the moment somebody sings —
scroll the **lyric line as POV text** in time with the audio.

```bash
sudo python3 poi_karaoke.py --interface wlan1 --channel 1 \
        --video Asereje.mp4 --lrc asereje.lrc --fps 240
```

## How it decides what to show

* **no singing** → one of three music-reactive patterns (bass pulse, spectrum,
  bounce), driven by a live energy analysis of the extracted audio track;
* **somebody sings** → the current lyric line scrolls as 5x7 text over the POV
  sticks; the scroll pace is tuned to the length of the line so it always fits
  its time slot.

The one packet-per-frame broadcast carries the *full strip height* (20 px raw)
to every masked group; the firmware trims each strip to its own length, so one
mask covers the different strip sizes. Lyric text is sent **upside down**
(LED 0 shows the bottom of a glyph) to match how the strips are physically
mounted.

## Requirements

* Linux + WiFi adapter in monitor mode (set up by ESPythoNOW, hence `sudo`)
* Python 3 + `scapy`:
  `python3 -m pip install -r ../lib/ESPythoNOW/requirements.txt`
* `ffmpeg` — extracts a mono WAV for live audio analysis
* `mpv` (optional) — plays the video; without it the script falls back to a
  wall-clock timer (`--no-player`)

The video file itself (e.g. `Asereje.mp4`) is **not** part of this repo;
`.lrc` lyric files are. `ffmpeg` will create `Asereje_mono.wav` next to the
video on first run.

## Important flags

* `--interface` — WiFi interface (monitor mode)
* `--video`, `--lrc` — media + `.lrc` file
* `--channel` — WiFi channel of the sticks (default `1`)
* `--fps` — stream frame rate (default `240`)
* `--group-mask` — which groups to light (default `0x0f` = groups 0–3)
* `--brightness`, `--energy` — visual levels
* `--text-speed` — lyric scroll multiplier (independent of `--fps`)
* `--offset` — seconds to shift lyrics vs. audio if they feel late/early

## Files

* `poi_karaoke.py` — the script
* `asereje.lrc` — example lyric track (timestamps + text)
* `../lib/ESPythoNOW/` — the vendored ESP-NOW sender library