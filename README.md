# fastConLight

Control **BRMesh / Fastcon** Bluetooth lights from Home Assistant, without the BRMesh app.

## Choose Your Version

| Version | Best For | Setup Complexity | Features |
|---------|----------|------------------|----------|
| **Home Assistant Bluetooth** (HACS) | HA on Linux with a Bluetooth adapter in range of the lights | ⭐ Easiest | No extra hardware, UI setup, lights are added automatically |
| **ESPHome** | Lights out of range of the HA host | ⭐⭐ Easy | Native HA API, OTA, Web UI, YAML config |
| **Arduino/PlatformIO** | Advanced users | ⭐⭐⭐⭐ Complex | Full control, MQTT, Custom code |

Full details: [SPECIFICATION.md](SPECIFICATION.md)

---

## Home Assistant Bluetooth integration

Uses the Bluetooth adapter of the Home Assistant host, so no ESP32 is needed. Commands are broadcast through the Linux Bluetooth management API (MGMT) with the same 31-byte packets the ESP32 firmware sends. Tested on a Home Assistant Yellow.

### Requirements

- Home Assistant 2024.8 or newer on Linux (Home Assistant OS, Supervised, or Docker with `NET_ADMIN` and `/run/dbus` mounted)
- A local Bluetooth adapter (Bluetooth 4.0 or newer). Bluetooth proxies can receive but cannot send commands.

### Installation via HACS

1. HACS → ⋮ → **Custom repositories** → `https://github.com/stromaa00/fastConLight`, type **Integration**
2. Install **BRMesh / Fastcon** and restart Home Assistant
3. **Settings → Devices & Services → Add Integration → BRMesh / Fastcon**, pick the adapter and enter the phone key (default `A1A2A3A4`)
4. Press **Scan for devices**, then **Bind all devices**. Or turn on **Auto-bind discovered lights** to have every light found by a scan bound automatically.

Lights already set up in ESPHome can be added under the integration's **Configure → Add a light manually**.

**Replacing the BRMesh app:** enter the app's mesh key as the phone key (**Configure → Settings**), press **Scan for devices**, and stop using the app. New lights keep their app address if it's free; turn on **Auto-bind discovered lights** if Home Assistant should bind them itself. Details: [SPECIFICATION.md §7.3](SPECIFICATION.md).

---

## Quick Start (ESPHome)

Requires an ESP32 with Bluetooth 5.0 (ESP32-S3, -C3 or -C6).

```bash
# Copy to ESPHome folder
cp -r components /config/esphome/
cp fastcon-esp32.yaml /config/esphome/

# Flash
esphome run fastcon-esp32.yaml
```

Secrets: with the ESPHome add-on, add the keys to `/config/esphome/secrets.yaml` (Secrets button in the dashboard). Standalone: copy `secrets.yaml.template` to `secrets.yaml`.

**Full docs**: [README-ESPHOME.md](README-ESPHOME.md)

---

## Arduino/PlatformIO Version (Legacy)

The original Arduino implementation is in the `src/` directory. Copy `src/credentials.h.example` to `src/credentials.h` and enter your WiFi and MQTT settings.
