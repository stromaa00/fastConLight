# fastConLight - Technical Specification & User Guide

> **Version:** 2.1.0 (HA Bluetooth) / 2.0.0 (ESPHome) / 1.0.0 (Arduino Legacy)  
> **Platform:** ESP32 with Bluetooth 5.0, or the Home Assistant host's own Bluetooth adapter  
> **Last Updated:** August 19, 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Hardware Requirements](#3-hardware-requirements)
4. [Protocol Specification](#4-protocol-specification)
5. [Device Types](#5-device-types)
6. [ESPHome Component](#6-esphome-component)
7. [Home Assistant Integration](#7-home-assistant-integration)
8. [Configuration Reference](#8-configuration-reference)
9. [Command Reference](#9-command-reference)
10. [User Guide](#10-user-guide)
11. [Known Limitations](#11-known-limitations)
12. [Testing](#12-testing)

---

## 1. Executive Summary

fastConLight is an ESP32-based IoT gateway that bridges **BRMesh/Fastcon** Bluetooth Low Energy (BLE) lighting devices to **Home Assistant**. It enables centralized control and automation of BLE mesh lighting networks without requiring the proprietary BRMesh mobile application.

The project provides three implementations:

| Version | Best For | Setup Complexity | Features |
|---------|----------|------------------|----------|
| **HA Bluetooth** (`custom_components/fastcon`) | HA on Linux with a Bluetooth adapter in range | ⭐ Easiest | No extra hardware, UI setup, auto-adds discovered lights, persistent bindings |
| **ESPHome** | Lights out of range of the HA host | ⭐⭐ Easy | Native HA API, OTA, Web UI, YAML config |
| **Arduino/PlatformIO** | Advanced users | ⭐⭐⭐⭐ Complex | Full control, MQTT, Custom code |

### Key Capabilities

- **BLE Extended Advertising** scanning and transmission
- **Device discovery** and automatic parsing of BRMesh broadcasts
- **Encrypted command transmission** using device-specific keys
- **Home Assistant integration** via native API (ESPHome) or MQTT (Arduino)
- **Device binding** with configurable mesh addresses
- **Multiple light types** support (RGB, RGBCW, RGBW, CCT, PWR)

---

## 2. System Architecture

### 2.1 High-Level Diagram

```
┌─────────────────┐     BLE 5.0      ┌──────────────────┐     WiFi      ┌─────────────────────┐
│                 │  Extended Adv.   │                  │               │                     │
│  BRMesh Lights  │◄────────────────►│  ESP32 Gateway   │◄─────────────►│  Home Assistant     │
│  (BLE Mesh)     │                   │  (fastConLight)  │               │  (Native API/MQTT)  │
│                 │                   │                  │               │                     │
└─────────────────┘                   └──────────────────┘               └─────────────────────┘
```

### 2.2 Data Flow

```
BLE Advertisement Received
    ↓
Filter by Address Prefix (0x11:0x22)
    ↓
Check Payload Header (13FFF0FF)
    ↓
Decrypt Payload with Phone Key
    ↓
Parse Device Information (DID, Name, Type, Key)
    ↓
Check if Device Already Exists
    ↓
Create Light Entity / Log Discovery
    ↓
Register with Home Assistant
```

### 2.3 Command Flow

```
Home Assistant Command
    ↓
ESPHome API / MQTT Message
    ↓
Parse Command Type & Parameters
    ↓
Generate BLE Command Payload
    ↓
Encrypt & Encode (whitening + CRC)
    ↓
Transmit as BLE Extended Advertisement (3s)
    ↓
Update Home Assistant State
```

---

## 3. Hardware Requirements

### 3.1 Supported Boards

The ESP32 firmware uses the ESP-IDF extended advertising API, which only exists on chips with Bluetooth 5.0 (ESP32-S3, -C3, -C6, -H2). Boards built on the original ESP32 (Bluetooth 4.2) do not support it.

| Board | Chip | Bluetooth | Programming Pin | Supported | Notes |
|-------|------|-----------|-----------------|-----------|-------|
| Heltec WiFi LoRa 32 V3 | ESP32-S3 | 5.0 | GPIO 0 | ✅ | Debug support, custom partition |
| ESP32-C6 DevKitC-1 | ESP32-C6 | 5.0 | GPIO 0 | ✅ | Custom partition table required |
| TTGO T-Beam | ESP32 | 4.2 | GPIO 0 | ❌ | No extended advertising |
| Generic ESP32-POE | ESP32 | 4.2 | GPIO 39 | ❌ | No extended advertising |

BRMesh packets are 31 bytes and fit a legacy (Bluetooth 4.x) advertisement, which is why the HA Bluetooth option (§7.3) works with ordinary adapters.

### 3.2 Minimum Requirements

- **RAM:** 520KB minimum (BLE + WiFi operation)
- **BLE:** Extended advertising callbacks support
- **WiFi:** 2.4GHz network
- **Storage:** Custom partition table for ESP32-C6

### 3.3 ESPHome Configuration Files

| File | Target Board |
|------|--------------|
| `fastcon-esp32.yaml` | Generic ESP32 (needs a Bluetooth 5.0 chip, see §3.1) |
| `fastcon-esp32c6.yaml` | ESP32-C6 DevKitC-1 |
| `fastcon-heltec.yaml` | Heltec WiFi LoRa 32 V3 |

---

## 4. Protocol Specification

### 4.1 BLE Scanning

- **Scan Type:** Active
- **Scan Interval:** 40 units
- **Scan Window:** 40 units
- **PHY:** Both coded and uncoded supported
- **Address Filter:** Devices with prefix `0x11:0x22`
- **Payload Header:** `13FFF0FF`

### 4.2 Encryption

- **Phone Key:** 4-byte encryption key (default: `0xA1, 0xA2, 0xA3, 0xA4`)
- **Header Encryption:** XOR with `DEFAULT_ENCRYPT_KEY` (`0x5E, 0x36, 0x7B, 0xC4`)
- **Data Encryption:** XOR with device-specific key (cycled every 4 bytes)
- **Command Encryption:** XOR with device key

### 4.3 Whitening Encoding

- **Seed:** `0x25`
- **Purpose:** Ensures signal spectrum distribution for BLE transmission
- **Implementation:** 7-state LFSR-based bit manipulation

### 4.4 CRC Calculation

- **Algorithm:** CRC-16/X-25 (polynomial `0x1021` reflected, initial value `0xFFFF`, final XOR `0xFFFF`)
- **Input:** Address bytes + data bytes
- **Output:** 16-bit CRC appended to payload, low byte first

Confirmed from commands relayed by real lights (October 2026). The ESP32 firmware (Arduino and ESPHome) uses CRC-16/CCITT-FALSE (not reflected, no final XOR) instead; lights accept those frames too, so they apparently don't check the CRC, but the HA integration now sends exactly what the lights produce.

### 4.5 BLE Command Structure

```
┌─────────────────────────────────────────────────────────────┐
│ BLE_PREDATA (7 bytes)                                       │
│ 0x02, 0x01, 0x02, 0x1b, 0xff, 0xf0, 0xff                   │
├─────────────────────────────────────────────────────────────┤
│ RF Payload (whitened + CRC)                                 │
│ Header (0x71, 0x0f, 0x55) + Address + Data + CRC(2 bytes)  │
├─────────────────────────────────────────────────────────────┤
│ BLE Fastcon Body (encrypted)                                │
│ Control Byte + Sequence + Safe Key + Checksum + Data        │
└─────────────────────────────────────────────────────────────┘
```

### 4.6 BLE Advertising Parameters

| Parameter | Value |
|-----------|-------|
| Advertisement Duration | 3000 ms |
| Command Retry Count | 1 |
| BLE Address | `0xC1:0xC2:0xC3` (default) |
| Advertising Interval | 0x45 |
| Channel Map | All channels |
| Own Address Type | Random |

---

## 5. Device Types

### 5.1 Light Types

| Device Type | Code (Dec) | Code (Hex) | Description |
|-------------|------------|------------|-------------|
| Light_RGBCW | 43050 | 0xA83A | RGB + Cold/Warm White |
| Light_RGB | 43168 | 0xA8A0 | RGB color |
| Light_CCT | 43051 | 0xA83B | Color temperature adjustable |
| Light_RGBW | 43169 | 0xA8A1 | RGB + White |
| Light_PWR | 43049 | 0xA839 | Power control |
| Light_W_CW | 43745 | 0xAAE1 | White + Cold/Warm |
| Light_BURDEN_W | 43759 | 0xAAEF | White burden |
| Light_BURDEN_CW | 43754 | 0xAAEA | Cold/Warm burden |
| Light_COMPOSE | 43709 | 0xAABD | Composed light |

### 5.2 Other Device Types

| Device Type | Code (Dec) | Code (Hex) | Description |
|-------------|------------|------------|-------------|
| Curtain | 43499 | 0xA9DB | Curtain controller |
| Fan | 43531 | 0xA9FB | Fan controller |
| Gateway | 43500 | 0xA9DC | Mesh gateway |
| Gateway_AC | 43756 | 0xAAEC | AC gateway |
| Gateway_IHG | 10058 | 0x274A | IHG gateway |
| Panel_3 | 43463 | 0xA9C7 | 3-button panel |
| Panel_3_Wireless | 43462 | 0xA9C6 | 3-button wireless panel |
| Panel_4 | 43473 | 0xA9D1 | 4-button panel |
| Panel_4_Wireless | 43472 | 0xA9D0 | 4-button wireless panel |
| Panel_6 | 43461 | 0xA9C5 | 6-button panel |
| Panel_6_Wireless | 43459 | 0xA9C3 | 6-button wireless panel |
| Panel_8 | 43733 | 0xAAD5 | 8-button panel |
| Panel_8_2 | 43734 | 0xAAD6 | 8-button panel v2 |
| Relay_1 | 43525 | 0xA9E5 | Single relay |
| Relay_2 | 43474 | 0xA9D2 | Dual relay |
| Relay_4 | 43680 | 0xAAA0 | Quad relay |
| Sensor_Door | 43505 | 0xA9D9 | Door sensor |
| Sensor_IR | 43516 | 0xA9E4 | IR sensor |
| Sensor_Radar | 43808 | 0xAB20 | Radar sensor |
| Sensor_Water | 43791 | 0xAB0F | Water sensor |
| Thermostat | 43919 | 0xAB8F | Thermostat |
| Meta_PAD | 43518 | 0xA9E6 | Meta pad |
| Meta_PAD_2 | 43974 | 0xABC6 | Meta pad v2 |

---

## 6. ESPHome Component

### 6.1 Component Structure

```
components/fastcon/
├── __init__.py                  # Component registration & Python config
├── light.py                     # Light platform registration
├── fastcon_component.h          # Main component header
├── fastcon_component.cpp        # Main component implementation
├── fastcon_light.h              # Light entity header
├── fastcon_light.cpp            # Light entity implementation
├── fastcon_protocol.h           # BRMesh protocol definitions
└── fastcon_protocol.cpp         # Protocol implementation
```

### 6.2 Component Configuration

```yaml
fastcon:
  id: fastcon_hub              # Required: Component ID
  phone_key: "A1A2A3A4"        # Optional: BRMesh encryption key (default: A1A2A3A4)
  auto_discover: true          # Optional: Log discovered devices (default: true)
```

### 6.3 Light Platform Configuration

```yaml
light:
  - platform: fastcon
    name: "Light Name"                # Required: Display name
    fastcon_id: fastcon_hub          # Required: Parent component ID
    device_id: "AABBCCDDEEFF"        # Required: 6-byte device ID (12 hex chars)
    device_type: "A8A1"              # Required: 2-byte device type (4 hex chars)
    device_key: "11223344"           # Required: 4-byte device key (8 hex chars)
    mesh_address: 1                  # Optional: Mesh address 0-255 (default: 0)
```

### 6.4 Actions

**Scan for devices:**
```yaml
- fastcon.scan:
    id: fastcon_hub
```

**Bind all devices:**
```yaml
- fastcon.bind_all:
    id: fastcon_hub
```

### 6.5 Light Capabilities

| Device Type | On/Off | Brightness | RGB | White | CCT |
|-------------|--------|------------|-----|-------|-----|
| Light_RGB (A8A0) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Light_RGBCW (A83A) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Light_RGBW (A8A1) | ✅ | ✅ | ✅ | ✅ | ❌ |
| Light_CCT (A83B) | ✅ | ✅ | ❌ | ❌ | ✅ |
| Light_PWR (A839) | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 7. Home Assistant Integration

### 7.1 ESPHome Version (Recommended)

- **Native API** - No MQTT configuration needed
- **Auto-Discovery** - Device appears in Settings → Devices & Services
- **API Encryption** - Secure communication with Home Assistant
- **OTA Updates** - Wireless firmware updates
- **Web Interface** - Built-in diagnostics on port 80

### 7.2 Arduino Version (Legacy)

- **MQTT Discovery** - Uses `homeassistant/light/{uniqueId}/config` topic
- **Command Topic:** `aha/{uniqueId}/cmd_t`
- **State Topic:** `aha/{uniqueId}/state_t`
- **Device Metadata:**
  - Manufacturer: "Dodosoft"
  - Model: "BRMesh"
  - Software Version: "1.0.0"

### 7.3 Home Assistant Bluetooth (no ESP32)

The `custom_components/fastcon` integration runs inside Home Assistant and uses the host's Bluetooth adapter instead of an ESP32.

**How it works**

- **Receiving:** registers with HA's `bluetooth` integration for manufacturer ID `0xFFF0` from addresses starting `11:22:`. Discovery broadcasts are parsed and new devices are added automatically with the next free mesh address (1-255). Broadcasts heard by ESPHome Bluetooth proxies are received too.
- **Sending:** HA's Bluetooth stack can only scan, so commands are broadcast through the Linux Bluetooth management API (MGMT, *Add Extended Advertising Parameters/Data*) with the same 31 bytes the firmware sends (flags `02 01 02` + manufacturer data `0xFFF0` + 24-byte command), at a 100 ms interval for the configured duration (default 3 s).
  - BlueZ's D-Bus `LEAdvertisement1` API is only a fallback: it reserves space for its own flags, so the kernel rejects the 31-byte packet with `Invalid Parameters (0x0d)` (seen on a Home Assistant Yellow).
  - MGMT needs `CAP_NET_ADMIN`, which the Home Assistant OS core container has.
- **Queue:** one command is on air at a time. A newer command for the same light replaces an unsent one, so dragging a slider doesn't build a backlog.
- **Storage:** discovered/added devices and their mesh addresses are saved in HA storage and survive restarts.

**Requirements**

- Home Assistant 2024.8 or newer on Linux (Home Assistant OS, Supervised, or Docker with `NET_ADMIN` and `/run/dbus` mounted).
- A **local** Bluetooth adapter that supports LE advertising (Bluetooth 4.0+). Bluetooth proxies can receive but cannot send commands.

**Entities**

| Entity | Purpose |
|--------|---------|
| `button.<hub>_scan_for_devices` | Broadcasts the scan command |
| `button.<hub>_bind_all_devices` | Sends a bind (discovery response) to every known device |
| `number.brmesh_<name>_mesh_address` | The light's mesh address (1-255). Changing it binds the light to the new address; addresses used by another light are refused |
| `button.brmesh_<name>_bind` | Binds just this light |
| `switch.<hub>_auto_bind_discovered_lights` | When on, lights found by a scan are bound automatically (off by default, saved) |
| `light.brmesh_<name>` | One per light; assumed state, restored after restart |

**Setup**

1. Copy `custom_components/fastcon` to `/config/custom_components/` (or add the repository to HACS as a custom integration) and restart HA.
2. **Settings → Devices & Services → Add Integration → BRMesh / Fastcon**. Pick the adapter and enter the phone key.
3. Press **Scan for devices**. Discovered lights appear automatically.
4. Press **Bind all devices** so each light learns its mesh address and the phone key.
5. Lights already set up in ESPHome can be added via the integration's **Configure → Add a light manually** with the same device ID, type, key and mesh address.

**Protocol notes (from the Arduino firmware)**

- Light commands are encrypted with the **phone key**, not the device key.
- Bind is command type 2 (not forwarded), encrypted with the device key, with data `DID(6) + mesh address + 0x01 + phone key(4)`.
- A light only accepts a bind while it is in discovery mode, i.e. a few seconds after a scan request. Binds sent at other times are ignored (the light keeps its old address), so manual binds are always preceded by a scan.
- In discovery broadcasts the 6-byte DID is at payload bytes 4-9 (the last 2 bytes are the name), the type at 10-11 (little endian) and the key at 12-15.
- Colour temperature is not mapped yet; CCT lights get brightness only.

**Replacing the BRMesh app**

Lights set up in the BRMesh app already know the app's mesh key (its "phone key"). Entering that key in the integration lets Home Assistant take over without resetting the lights:

1. Find the app's key, e.g. from a diagnostics download while the app sends a command: in the decoded control frames the zero padding reveals it (it was `34333739` in the first real setup).
2. **Configure → Settings → Phone key**: enter the app's key.
3. Turn on **Auto-bind discovered lights** if Home Assistant should bind lights by itself, then press **Scan for devices**. Each light answers with a discovery broadcast and waits for a bind (discovery response). New lights keep the mesh address they report (header byte 2) if it's free. With auto-bind on, every discovered light is bound right away (at most once a minute per light), and known lights are bound back to the address Home Assistant stores. With it off, nothing is bound until **Bind all devices** is pressed; a log entry notes lights whose reported address differs.
4. Stop using the app: opening it re-applies its own addresses. If that happens, a scan (with auto-bind on) or **Bind all devices** binds the lights back.

With the app's key, heartbeats decode (header type 3, data subtype 4) and drive availability: the integration learns each light's heartbeat interval and marks it unavailable after 4 missed heartbeats (at least 5 minutes).

### 7.4 Device Identification

Each device has a unique identifier:
```
{NAME}-{DID}-{TYPE}-{KEY}
```

Example: `52F2-EC0BF10A52F2-A8A1-5E367BC4`

---

## 8. Configuration Reference

### 8.1 ESPHome YAML Configuration

```yaml
# WiFi configuration
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:
    ssid: "fastcon-esp32 Fallback"
    password: !secret ap_password

# Logging
logger:
  level: DEBUG

# Home Assistant API
api:
  encryption:
    key: !secret api_encryption_key

# OTA updates (ESPHome 2024.6+ format)
ota:
  - platform: esphome
    password: !secret ota_password

# Web server
web_server:
  port: 80

# Fastcon component
fastcon:
  id: fastcon_hub
  phone_key: "A1A2A3A4"
  auto_discover: true

# Lights
light:
  - platform: fastcon
    name: "Living Room Light"
    fastcon_id: fastcon_hub
    device_id: "EC0BF10A52F2"
    device_type: "A8A1"
    device_key: "5E367BC4"
    mesh_address: 1

# Buttons
button:
  - platform: template
    name: "Scan for Devices"
    icon: "mdi:magnify-scan"
    on_press:
      - fastcon.scan:
          id: fastcon_hub

  - platform: template
    name: "Bind All Devices"
    icon: "mdi:link-variant"
    on_press:
      - fastcon.bind_all:
          id: fastcon_hub
```

### 8.2 Secrets Template

Only the ESPHome version reads secrets. The HA Bluetooth integration (§7.3) is configured in the Home Assistant UI and needs no secrets file.

Where the file lives:

| ESPHome install | Secrets file |
|-----------------|--------------|
| Home Assistant ESPHome add-on | `/config/esphome/secrets.yaml`, shared by all devices. Edit it with the **Secrets** button in the add-on dashboard. |
| Standalone ESPHome | `secrets.yaml` next to the board YAML (copy `secrets.yaml.template`) |

All five keys below are used by every board YAML. To skip the secrets file, replace each `!secret` with the actual value. Removing the `api: encryption:` and `ota:` password lines leaves only the WiFi values.

```yaml
# WiFi credentials
wifi_ssid: "Your_WiFi_SSID"
wifi_password: "your_wifi_password"

# Fallback Access Point password
ap_password: "fallback_ap_password"

# Home Assistant API encryption key
api_encryption_key: "your_api_encryption_key_here"

# OTA update password
ota_password: "your_ota_password"
```

### 8.3 Arduino Compile-Time Configuration

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| MQTT_BROKER_ADDR | 192.168.1.111 | MQTT broker IP address |
| MQTT_BROKER_USER | "homeassistant" | MQTT username |
| MQTT_BROKER_PASS | (configured) | MQTT password |
| WIFI_SSID | (configured) | WiFi network name |
| WIFI_PASS | (configured) | WiFi password |
| DEFAULT_PHONE_KEY | 0xA1,0xA2,0xA3,0xA4 | BLE device encryption key |
| PRG_PIN | (board-specific) | Physical button GPIO |

---

## 9. Command Reference

### 9.1 Light Commands

| Command | Payload | Description |
|---------|---------|-------------|
| Turn On | `128 \| (brightness & 127)` | Turn on with brightness (0-255) |
| Turn Off | `0` | Turn off |
| Brightness | `brightness & 127` | Set brightness only |
| RGB Color | 6 bytes | RGB + brightness with normalization |
| White | 6 bytes | White channel control |

### 9.2 RGB Command Format

```
Byte 0: 128 (on) | brightness & 127
Byte 1: blue * normalization
Byte 2: red * normalization
Byte 3: green * normalization
Byte 4: 0
Byte 5: 0
```

### 9.3 White Command Format

```
Byte 0: 128 (on) | 127 (max brightness)
Byte 1: 0
Byte 2: 0
Byte 3: 0
Byte 4: whiteness
Byte 5: whiteness
```

### 9.4 Command Types

| Command Type | Value | Description |
|--------------|-------|-------------|
| Scan | 0 | Start device discovery |
| Single Control | 5 | Control a single device |
| Bind | 5 | Bind device to mesh address |

---

## 10. User Guide

### 10.1 Prerequisites

This guide covers the ESPHome version. For the HA Bluetooth integration, which needs no ESP32, ESPHome, USB flashing or secrets file, follow the setup steps in §7.3 instead.

Before you begin, ensure you have:

- **ESPHome** installed (via Home Assistant Add-on or standalone)
- **ESP32 board** with Bluetooth 5.0 (ESP32-S3, -C3 or -C6, e.g. Heltec V3 or ESP32-C6 DevKitC-1)
- **BRMesh/Fastcon lights** on your network
- **USB cable** for initial flashing
- **Home Assistant** instance (for full functionality)

### 10.2 Installation

#### Step 1: Copy Project Files

Copy the entire `fastConLight` directory to your ESPHome config location:

```bash
# If using Home Assistant Add-on
cp -r components /config/esphome/
cp fastcon-*.yaml /config/esphome/

# If using standalone ESPHome
cp -r components ~/esphome/
cp fastcon-*.yaml ~/esphome/
```

#### Step 2: Add Secrets

**Home Assistant ESPHome add-on:** open the ESPHome dashboard, click **Secrets** (top right) and add the keys below to the existing `/config/esphome/secrets.yaml`. Don't copy `secrets.yaml.template`; the add-on has its own file.

**Standalone ESPHome:**

```bash
cp secrets.yaml.template secrets.yaml
nano secrets.yaml  # or use your preferred editor
```

Keys every board YAML needs:

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "your_wifi_password"
ap_password: "fallback_password"
api_encryption_key: "32-byte base64 key"   # generate at https://esphome.io/components/api.html
ota_password: "ota_update_password"
```

See §8.2 for running without a secrets file.

#### Step 3: Choose Your Board Configuration

Select the YAML file matching your ESP32 board:

- **ESP32-C6 DevKitC-1**: `fastcon-esp32c6.yaml`
- **Heltec WiFi LoRa 32 V3**: `fastcon-heltec.yaml`
- **Other Bluetooth 5.0 ESP32 (S3/C3)**: `fastcon-esp32.yaml`, with the `board` changed to match. The original ESP32 is not supported (§3.1).

#### Step 4: Initial Flash

Connect your ESP32 via USB and flash:

```bash
# Using ESPHome command line
esphome run fastcon-esp32.yaml

# Or compile and upload separately
esphome compile fastcon-esp32.yaml
esphome upload fastcon-esp32.yaml
```

### 10.3 Discovering Devices

1. Open Home Assistant
2. The ESP32 device should auto-discover in **Settings → Devices & Services**
3. Click **CONFIGURE** and enter your API encryption key
4. Press the **"Scan for Devices"** button in Home Assistant
5. Watch the ESPHome logs for discovered devices

```
[I][fastcon.component:123]: Discovered device: 52F2-EC0BF10A52F2-A8A1-5E367BC4
[W][fastcon.component:145]: Auto-discovery found device - add to YAML config:
[W][fastcon.component:146]:   - platform: fastcon
[W][fastcon.component:147]:     name: "52F2"
[W][fastcon.component:148]:     device_id: "EC0BF10A52F2"
[W][fastcon.component:149]:     device_type: "A8A1"
[W][fastcon.component:150]:     device_key: "5E367BC4"
```

### 10.4 Adding Lights to Configuration

Copy the discovered device information to your YAML file:

```yaml
light:
  - platform: fastcon
    name: "Living Room Light"
    fastcon_id: fastcon_hub
    device_id: "EC0BF10A52F2"      # From discovery log
    device_type: "A8A1"             # From discovery log
    device_key: "5E367BC4"          # From discovery log
    mesh_address: 1                 # Assign unique address 0-255
```

### 10.5 Binding Devices

Binding assigns mesh addresses to lights. Press **"Bind All Devices"** in Home Assistant, or use the physical button (long press ≥1 second).

### 10.6 Controlling Lights

Lights appear in Home Assistant as standard light entities with full support for:

- ✅ On/Off
- ✅ Brightness (0-100%)
- ✅ RGB Color (for RGB lights)
- ✅ White Channel (for RGBW/RGBCW lights)
- ✅ Color Temperature (for CCT/RGBCW lights)

### 10.7 Example Automation

```yaml
automation:
  - alias: "Sunset Lighting"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: light.turn_on
        target:
          entity_id: light.living_room_light
        data:
          brightness_pct: 70
          rgb_color: [255, 147, 41]  # Warm orange
```

### 10.8 Physical Button Control

| Action | Duration | Function |
|--------|----------|----------|
| Short press | < 1 second | Trigger network scan |
| Long press | ≥ 1 second | Bind all devices |

### 10.9 Troubleshooting

#### Device Not Discovered

**Problem:** Lights not appearing in discovery logs

**Solutions:**
1. Check phone key is correct
2. Ensure lights are powered on and in range
3. Verify BLE address filter (should start with `0x11:0x22`)
4. Check logs for BLE scan errors
5. Try manual scan button press

```bash
# Check logs
esphome logs fastcon-esp32.yaml
```

#### Lights Not Responding

**Problem:** Lights don't respond to commands

**Solutions:**
1. Verify mesh address is set correctly
2. Check device key matches discovery
3. Ensure device is bound (press "Bind All")
4. Verify BLE advertising is working
5. Check WiFi/Home Assistant connection

#### Home Assistant Integration Issues

**Problem:** Device not appearing in Home Assistant

**Solutions:**
1. Check API encryption key matches
2. Verify Home Assistant can reach ESP32 IP
3. Check firewall settings (port 6053)
4. Try manual integration:
   - Go to **Settings → Devices & Services**
   - Click **+ ADD INTEGRATION**
   - Search for **ESPHome**
   - Enter ESP32 IP address

#### Compilation Errors

**Problem:** ESPHome fails to compile

**Solutions:**
1. Verify component files are in correct location
2. Check board configuration matches your hardware
3. Update ESPHome to latest version
4. Check logs for specific errors:

```bash
esphome compile fastcon-esp32.yaml --verbose
```

### 10.10 Best Practices

#### Security

1. **Use strong passwords** for OTA and AP
2. **Enable API encryption** (automatically generated)
3. **Keep firmware updated** for security patches
4. **Change default phone key** if possible
5. **Hide secrets.yaml** from version control

#### Reliability

1. **Assign static IP** to ESP32 in router
2. **Use quality power supply** (5V 2A minimum)
3. **Keep firmware updated**
4. **Monitor WiFi signal strength**
5. **Test after power outages**

#### Organization

1. **Use meaningful names** for devices
2. **Group lights by zone** using mesh addresses
3. **Document custom configurations**
4. **Use substitutions** for repeated values
5. **Comment complex automations**

---

## 11. Known Limitations

### 11.1 Current Limitations

- **L-001:** No TLS support for MQTT (Arduino version, unencrypted communication)
- **L-002:** WiFi credentials hardcoded at compile time (Arduino version)
- **L-003:** No web interface implementation (Arduino version)
- **L-004:** Maximum address selector range: 0-6 (Arduino version)
- **L-005:** No persistent storage of device bindings (lost on reboot)
- **L-006:** Single MQTT broker support (no failover)
- **L-007:** Dynamic device creation requires manual YAML addition (ESPHome limitation)
- **L-008:** Single phone key globally (can be overridden per device)
- **L-009:** Lights must be defined in YAML (cannot add via HA UI)

### 11.2 Platform Limitations

- **L-010:** ESP32 firmware requires Bluetooth 5.0 extended advertising (ESP32-S3/C3/C6/H2)
- **L-011:** Original ESP32 boards (T-Beam, ESP32-POE) are not supported by the ESP32 firmware; use the HA Bluetooth option instead
- **L-016:** HA Bluetooth option needs Linux, `CAP_NET_ADMIN` and a local adapter; it cannot send through Bluetooth proxies
- **L-017:** HA Bluetooth option sends one command at a time (default 3 s each)
- **L-012:** Custom partition table required for ESP32-C6

### 11.3 Protocol Limitations

- **L-013:** Lights don't report their on/off/brightness state. They relay every command with the forward bit set (from address `11:22:33:44:55:66`, as a whitened 24-byte frame) and send heartbeats encrypted with the mesh key, which only tell that a light is powered
- **L-014:** State reported in Home Assistant may not reflect actual light state
- **L-015:** Commands may be lost (~80% reliability without redundancy)

---

## 12. Testing

### 12.1 Compilation Testing

- ✅ Compiles without errors on ESP32
- ✅ Compiles without errors on ESP32-C6
- ✅ Compiles without errors on Heltec board
- ✅ No warnings with pedantic flags

### 12.2 Runtime Testing (Requires Hardware)

- ⏳ BLE scanning detects devices
- ⏳ Device parsing works correctly
- ⏳ Light on/off commands work
- ⏳ Brightness control works
- ⏳ RGB color control works
- ⏳ White channel control works
- ⏳ Binding process completes
- ⏳ Scan button triggers discovery
- ⏳ Physical button works (if configured)
- ⏳ Home Assistant integration works
- ⏳ OTA updates work

### 12.3 Integration Testing (Requires Hardware + HA)

- ⏳ Lights appear in Home Assistant
- ⏳ State changes reflect in HA
- ⏳ HA commands control lights
- ⏳ Automations trigger correctly
- ⏳ Multiple lights work simultaneously
- ⏳ Network reconnection recovery

### 12.4 HA Bluetooth Integration (Home Assistant Yellow, October 2026)

- ✅ Sending through MGMT without errors
- ✅ Lights discovered and added automatically
- ✅ Bind all devices
- ✅ Lights respond to commands from Home Assistant
- ✅ Brightness, RGB and white individually confirmed
- ✅ All 7 lights replace the BRMesh app: binding from Home Assistant sets both the mesh address and the phone key (heartbeats afterwards come from Home Assistant's addresses, encrypted with its key)
- ⚠️ Binds don't always arrive the first time for weak lights (about −85 to −90 dBm); pressing **Bind all devices** again fixed it
- ⏳ Behaviour after host reboot

Problems found and fixed on the way: BlueZ D-Bus rejects the 31-byte packet (`Invalid Parameters`); non-connectable advertising needs a random address the controller refuses while scanning (`Opcode 0x2005 failed: -16`); unread MGMT events filled the socket buffer (`ENOMEM`).

---

## Appendix A: Migration from Arduino to ESPHome

### What Changed

| Feature | Arduino Version | ESPHome Version |
|---------|----------------|-----------------|
| **Configuration** | Hardcoded in `main.cpp` | YAML file |
| **WiFi Setup** | Compile-time | YAML + Secrets |
| **MQTT** | Manual setup required | Native API (no MQTT needed) |
| **OTA Updates** | Manual implementation | Built-in |
| **Logging** | Serial only | Serial + Network + HA |
| **Web UI** | Not included | Built-in |
| **Home Assistant** | MQTT discovery | Native integration |

### Migration Steps

1. **Note your current devices**: Document device IDs, keys, and types from logs
2. **Flash ESPHome**: Upload one of the ESPHome configs
3. **Add devices to YAML**: Copy device info from old logs or re-scan
4. **Test functionality**: Verify all lights work
5. **Update Home Assistant**: Remove old MQTT devices, add ESPHome entities

---

## Appendix B: Obtaining the Phone Key

The `phone_key` is a 4-byte encryption key used by your BRMesh app. To find it:

1. **If you know it**: Use the key from your BRMesh app (hex format)
2. **Default key**: Try `A1A2A3A4` (often works for testing)
3. **Extract from app**: Use ADB logcat on Android to capture it:
   ```bash
   adb logcat | grep -i "key\|encrypt"
   ```

Example output:
```
11-27 21:25:23.309  7827  7827 I jyq_helper: getPayloadWithInnerRetry---> payload:22035b000000000000000000,  key: 31323334
```

The key `31323334` in hex means you'll input `{ 0x31, 0x32, 0x33, 0x34 }` or `"31323334"` in YAML.

---

## Appendix C: Resource Usage

### ESPHome Version

- **Flash:** ~800KB (component code + ESPHome core)
- **RAM:** ~200KB (BLE + WiFi + component)
- **CPU:** <5% average (periodic BLE scanning)

### BLE Communication

- **Scan Interval:** Continuous (60s restart safety)
- **Command Duration:** 3 seconds per command
- **Range:** ~10-30 meters (typical BLE range)

### Network Traffic

- **API:** Minimal (state updates only)
- **Logging:** Configurable (disable for production)
- **OTA:** Only during updates

---

## Appendix D: References

### External Documentation

- Home Assistant MQTT Discovery: https://www.home-assistant.io/integrations/mqtt/
- ESP32 BLE Documentation: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/bluetooth/
- PlatformIO Documentation: https://platformio.org/
- ESPHome Documentation: https://esphome.io/

### Internal Documentation

- `README.md` - Project overview
- `README-ESPHOME.md` - ESPHome setup guide
- `FUNCTIONAL_SPECIFICATION.md` - Original functional specification
- `MIGRATION-SUMMARY.md` - Migration details
- `src/README.md` - Original Arduino documentation

---

**Document Status:** Active  
**Component Version:** 2.0.0  
**Compatible ESPHome:** 2023.12.0+