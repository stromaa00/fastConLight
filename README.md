<p align="center">
  <img src="https://raw.githubusercontent.com/stromaa00/fastConLight/main/custom_components/fastcon/brand/icon@2x.png" alt="fastConLight" width="128">
</p>

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

**Mesh addresses:** on a light's device page, set **Mesh address** and press **Bind**; nothing is sent before that. **Bound mesh address** shows the address in use and only changes once the light's heartbeat comes from the new address (power cycle the light if it doesn't). Several lights may get the same address, then they switch together.

Lights already set up in ESPHome can be added under the integration's **Configure → Add a light manually**.

**Groups:** under **Configure → Groups** create a group, give it a name and pick its lights; saving sends the memberships to the lights. Each group is its own device under the mesh, with its lights listed under it, and has a light entity that switches all its lights with one command per light type, like the BRMesh app. Pick an **Area** to control the group through it ("turn on the hallway lights"); keep the group's lights themselves out of that area, or the area also switches them one by one. A light is in at most one group. To take over a group from the app, use its id (the app's first group is usually 1).

**Effects:** under **Configure → Effects** build colour effects (name, fade or jump, speed, up to 9 colours from red, green, blue, yellow, magenta, cyan, white, off). They appear in the effect list of every colour light, group and *All lights*. Choosing a colour or white ends an effect; switching off and on keeps it. Starts with the BRMesh app's 21 built-in effects (Full color fade, Romantic, Fresh, Cozy, the flashes, Christmas, Winter, Halloween, Valentines day); **Add the BRMesh app's built-in effects** adds missing ones to an existing mesh.

**All lights at once:** every mesh has an **All lights** entity that switches all its lights with a single command, which is much faster than a group of single lights. Experimental: if your lights don't react to it, please open an issue.

**Lights out of range:** flash an ESP32 with [brmesh-transmitter.yaml](brmesh-transmitter.yaml) (it's also a Bluetooth proxy) and select its `send_brmesh` action under **Configure → Settings → ESP32 transmitters**. Commands are then sent from the ESP32 too.

**Replacing the BRMesh app:** enter the app's mesh key as the phone key (**Configure → Settings**), press **Scan for devices**, and stop using the app. New lights keep their app address if it's free; turn on **Auto-bind discovered lights** if Home Assistant should bind them itself. Details: [SPECIFICATION.md §7.3](SPECIFICATION.md).

**Several meshes:** each phone key is its own mesh. Add another one with **Settings → Devices & Services → BRMesh / Fastcon → Add entry** and give it a name and its phone key; it can use the same adapter. Newly discovered lights go to the mesh where you last pressed **Scan for devices** (for 2 minutes after the scan); otherwise to the mesh whose **Auto-bind discovered lights** is on, or to the first mesh. A light that already went to the wrong mesh: delete it there, power cycle it and scan again in the right mesh.

### Debugging with an ESP32 transmitter

[tools/brmesh_debug.py](tools/brmesh_debug.py) talks to an ESP32 running `brmesh-transmitter.yaml` directly, without Home Assistant: scan, bind, switch lights (also all at once) and watch the decoded BRMesh broadcasts and the ESP32 log.

```bash
pip install aioesphomeapi
python tools/brmesh_debug.py --host 192.168.1.50 --key <api encryption key> --phone-key A1A2A3A4
brmesh> scan
brmesh> bind found 5
brmesh> on 5 50
brmesh> off all
```

For a browser UI with the same functions (connection form, light control, discovered lights with Bind buttons, heartbeats, filterable live log):

```bash
pip install aioesphomeapi aiohttp
python tools/brmesh_web.py        # http://127.0.0.1:8099
```

Broadcast time per command and time between packets are adjustable in both; the packet interval needs the `set_brmesh_interval` action from [brmesh-transmitter.yaml](brmesh-transmitter.yaml) on the ESP32.

**Watch address** (shell: `watch 11:22`) shows everything an address sends, with all advertisement fields and BRMesh frames decrypted; **Decode** (`decode <hex>`) decodes a payload you copied from a log.

`--help` lists the one-shot commands (`info`, `scan`, `sniff`, `on`, …); `help` in the shell lists the shell commands. While the tool is connected, Home Assistant gets no Bluetooth advertisements from that ESP32 (ESPHome passes them to one client only) until it reconnects.

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

---

## License

[Apache License 2.0](LICENSE)
