# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Control of BRMesh / Fastcon Bluetooth LE lights from Home Assistant. The repo holds three independent implementations of the same protocol plus a helper ESPHome component:

| Path | What | Status |
|------|------|--------|
| `custom_components/fastcon/` | Home Assistant integration (HACS) using the HA host's Bluetooth adapter | Main focus of current work |
| `components/brmesh_tx/` + `brmesh-transmitter.yaml` | ESPHome component that rebroadcasts the integration's packets from an ESP32 (range extension) | Active |
| `components/fastcon/` + `fastcon-*.yaml` | Standalone ESPHome firmware (lights defined in YAML) | Maintained |
| `src/` + `platformio.ini` | Original Arduino/PlatformIO firmware with MQTT | Legacy, kept as protocol reference |

`SPECIFICATION.md` is the authoritative design/protocol document (§7.3 covers the HA integration in depth). `FUNCTIONAL_SPECIFICATION.md` analyses the original Arduino code. The Playwright setup (`package.json`, `playwright.config.ts`, `tests/example.spec.ts`, `index.html`, `script.js`, `styles.css`) is unrelated boilerplate.

## Commands

```bash
# Python tests (what CI runs; no Home Assistant install needed)
python -m unittest discover -s tests/python -v

# Single test
python -m unittest discover -s tests/python -k test_crc_is_x25

# ESPHome firmware
esphome run fastcon-esp32.yaml        # needs secrets.yaml (from secrets.yaml.template)

# Legacy Arduino firmware (needs src/credentials.h from credentials.h.example)
pio run -e esp32-c6-devkitc-1
pio run -e heltec_wifi_lora_32_V3_analysis   # *_analysis envs build with -Wall -Wextra -Wpedantic
```

CI (`.github/workflows/validate.yml`) also runs HACS validation and `hassfest` on the integration.

## HA integration architecture

- `protocol.py` — pure-Python port of the firmware protocol (whitening, CRC, encryption, command building, parsing of discovery broadcasts and heartbeats, human-readable descriptions). **Must stay free of Home Assistant imports**: the tests load it directly by file path. Same for `mgmt.py`.
- `mgmt.py` — raw Linux Bluetooth MGMT socket client (ctypes). Sends the 31-byte advertisement (flags `02 01 02` + manufacturer data `0xFFF0` + 24-byte command) via *Add Extended Advertising*. Needs `CAP_NET_ADMIN`.
- `advertiser.py` — tries MGMT first, falls back to BlueZ D-Bus `LEAdvertisement1` (which usually rejects the 31-byte packet, see spec §7.3). Do not add `from __future__ import annotations` here: dbus-fast reads the unquoted D-Bus signature annotations.
- `hub.py` — `FastconHub` owns everything stateful: device list persisted via HA `Store`, the Bluetooth callback (manufacturer ID `0xFFF0`, sender `11:22:...`), a send queue keyed by target (a newer command for the same light replaces an unsent one), heartbeat-based availability, auto-bind, pending manual binds, ESP32 transmitter fan-out (calls `esphome.<device>_send_brmesh` services), and the recent-broadcast log used by `diagnostics.py`. Entities talk to the hub and are updated through dispatcher signals defined in `const.py`.
- Platforms (`light.py`, `button.py`, `number.py`, `switch.py`) are thin wrappers over hub methods; `config_flow.py` holds setup and the options flow (phone key, durations, interval, transmitters, manual light add).

Protocol facts that are easy to get wrong (details in SPECIFICATION.md §7.3):
- Light commands are encrypted with the **phone key**; binds use the **device key**.
- A light only accepts a bind in discovery mode, i.e. right after a power cycle. Manual binds therefore stay pending and are resent when the light next announces itself.
- Device identity string is `NAME-DID-TYPE-KEY` (NAME = last 4 hex chars of DID).

## Conventions

- Bump `version` in `custom_components/fastcon/manifest.json` with every change to the integration (HACS uses it). After committing and pushing such a change, also create and push an annotated tag `vX.Y.Z` matching that version (e.g. `git tag -a v2.16.3 -m "v2.16.3"`).
- New user-facing options/entities need strings in `translations/en.json`.
- Behaviour changes to the integration are documented in `SPECIFICATION.md` §7.3 and, if user-visible, `README.md`.
- Commit messages: one short imperative sentence describing the user-visible effect (e.g. "Keep manual binds pending until the light is power cycled").
