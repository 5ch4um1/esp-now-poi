# examples

Command line programs that stream pixels to the Poi sticks. This is the
"software to send messages to the poi" half of the project — everything here
runs on a **Linux computer with a WiFi interface in monitor mode** (raw 802.11
frame injection). No ESP32 hardware is required on the sender side.

## Layout

| Folder                        | What it does                                            |
|-------------------------------|---------------------------------------------------------|
| `lib/ESPythoNOW/`             | Vendored ESP-NOW sender library (MIT, thanks ChuckMash) |
| `simple/poi_send.py`          | Smallest possible sender: color / rainbow test           |
| `karaoke/poi_karaoke.py`      | Video-synced karaoke + music-reactive beam patterns     |

## Getting started

Every script talks to the same broadcast address (`FF:FF:FF:FF:FF:FF`) on
channel 1, the channel the firmware listens on.

1. Put your WiFi adapter receive-only into monitor mode (ESPythoNOW does this
   itself when you pass it an interface, which is why you run with `sudo`).
2. Flash one or more sticks with the firmware in `../firmware/`.
3. Run an example:

```bash
python3 -m pip install -r lib/ESPythoNOW/requirements.txt
sudo python3 simple/poi_send.py --interface wlan1 --rainbow --group-mask 0x3f
```

Each example folder has its own README and usage notes.