# ESPythoNOW (vendored)

`ESPythoNOW.py` is part of the [chmorgan's ESPythoNOW](https://github.com/ChuckMash/ESPythoNOW)
project (c) 2024 ChuckMash, MIT licensed — vendored here unmodified so the
examples in `examples/` are self-contained. Its LICENSE is in this folder.

## What it provides

A pure-Python ESP-NOW implementation on Linux: it configures a WiFi interface
into monitor mode and sends/receives raw ESP-NOW action frames via Scapy and
raw socket injection. No ESP32 hardware needed on the sender machine.

## Dependencies (for the examples)

```bash
python3 -m pip install -r requirements.txt
```

Requires `scapy` (the optional `paho-mqtt` / `pycryptodome` entries are there
for the library's MQTT and encryption features, not used by the poi examples).

## Usage in this repo

Both example programs add `../lib/ESPythoNOW` to their import path and use the
library like this:

```python
from ESPythoNOW import ESPythoNow
espnow = ESPythoNow(interface="wlan1", channel=1)
espnow.send("FF:FF:FF:FF:FF:FF", packet_bytes)
```

The class constructor puts the interface into monitor mode on the given
channel — which is why the scripts should be run with `sudo`.