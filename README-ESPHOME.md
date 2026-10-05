# FastconLight - ESPHome Setup Guide

## Overview

FastconLight has been migrated to ESPHome as a custom component, providing native Home Assistant integration with improved features:

✅ **Native Home Assistant API** - No MQTT configuration needed  
✅ **YAML Configuration** - Easy to manage WiFi, credentials, and devices  
✅ **Over-the-Air (OTA) Updates** - Update firmware wirelessly  
✅ **Web Interface** - Built-in diagnostics and control  
✅ **Better Logging** - Enhanced debugging capabilities  
✅ **Auto-Discovery Support** - Automatically detect BRMesh lights

---

## Quick Start

### 1. Prerequisites

- **ESPHome** installed (via Home Assistant Add-on or standalone)
- **ESP32 board** with BLE 5.0 support (ESP32-C6, Heltec, etc.)
- **BRMesh/Fastcon lights** on your network
- **USB cable** for initial flashing

### 2. Installation Steps

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

#### Step 2: Create Secrets File

Copy the secrets template and edit with your credentials:

```bash
cp secrets.yaml.template secrets.yaml
nano secrets.yaml  # or use your preferred editor
```

Fill in your WiFi credentials and passwords:

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "your_wifi_password"
ap_password: "fallback_password"
ota_password: "ota_update_password"
```

#### Step 3: Choose Your Board Configuration

Select the YAML file matching your ESP32 board:

- **ESP32-C6 DevKitC-1**: `fastcon-esp32c6.yaml`
- **Heltec WiFi LoRa 32 V3**: `fastcon-heltec.yaml`
- **Generic ESP32**: `fastcon-esp32.yaml`

#### Step 4: Initial Flash

Connect your ESP32 via USB and flash:

```bash
# Using ESPHome command line
esphome run fastcon-esp32.yaml

# Or compile and upload separately
esphome compile fastcon-esp32.yaml
esphome upload fastcon-esp32.yaml
```

#### Step 5: Discover Devices

1. Open Home Assistant
2. The ESP32 device should auto-discover in **Settings → Devices & Services**
3. Click **CONFIGURE** and enter your API encryption key
4. Press the **"Scan for Devices"** button in Home Assistant
5. Watch the ESPHome logs for discovered devices

---

## Configuration Guide

### Basic Configuration

```yaml
esphome:
  name: fastcon-esp32
  platform: ESP32
  board: esp32dev

# Fastcon component
fastcon:
  id: fastcon_hub
  phone_key: "A1A2A3A4"  # Your BRMesh encryption key
  auto_discover: true     # Enable auto-discovery logging
```

### Phone Key Setup

The `phone_key` is a 4-byte encryption key used by your BRMesh app. To find it:

1. **If you know it**: Use the key from your BRMesh app (hex format)
2. **Default key**: Try `A1A2A3A4` (often works for testing)
3. **Extract from app**: Use ADB logcat on Android to capture it:
   ```bash
   adb logcat | grep -i "key\|encrypt"
   ```

### Adding Lights

After running a scan, check the ESPHome logs for discovered devices:

```
[I][fastcon.component:123]: Discovered device: 52F2-EC0BF10A52F2-A8A1-5E367BC4
[W][fastcon.component:145]: Auto-discovery found device - add to YAML config:
[W][fastcon.component:146]:   - platform: fastcon
[W][fastcon.component:147]:     name: "52F2"
[W][fastcon.component:148]:     device_id: "EC0BF10A52F2"
[W][fastcon.component:149]:     device_type: "A8A1"
[W][fastcon.component:150]:     device_key: "5E367BC4"
```

Copy this information to your YAML file:

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

### Device Types Reference

| Device Type Code | Description | Features |
|------------------|-------------|----------|
| `A8A0` (43168) | Light_RGB | RGB color control |
| `A83A` (43050) | Light_RGBCW | RGB + Cold/Warm white |
| `A8A1` (43169) | Light_RGBW | RGB + White |
| `A83B` (43051) | Light_CCT | Color temperature |
| `A839` (43049) | Light_PWR | On/Off only |

---

## Features & Usage

### Scan for Devices

Press the **"Scan for Devices"** button in Home Assistant to broadcast a BLE scan command:

```yaml
button:
  - platform: template
    name: "Scan for Devices"
    on_press:
      - fastcon.scan:
          id: fastcon_hub
```

Or use automation:

```yaml
automation:
  - alias: "Daily Light Scan"
    trigger:
      - platform: time
        at: "02:00:00"
    action:
      - button.press: scan_for_devices
```

### Bind All Devices

Binding assigns mesh addresses to lights. Press **"Bind All Devices"** to bind all configured lights:

```yaml
button:
  - platform: template
    name: "Bind All Devices"
    on_press:
      - fastcon.bind_all:
          id: fastcon_hub
```

### Physical Button Control (Optional)

Map physical buttons to scan/bind actions:

```yaml
binary_sensor:
  - platform: gpio
    pin:
      number: GPIO0
      inverted: true
      mode:
        input: true
        pullup: true
    name: "Boot Button"
    on_click:
      # Short press: Scan
      - min_length: 50ms
        max_length: 1000ms
        then:
          - fastcon.scan:
              id: fastcon_hub
      # Long press: Bind all
      - min_length: 1000ms
        max_length: 5000ms
        then:
          - fastcon.bind_all:
              id: fastcon_hub
```

### Light Control

Lights appear in Home Assistant as standard light entities with full support for:

- ✅ On/Off
- ✅ Brightness (0-100%)
- ✅ RGB Color (for RGB lights)
- ✅ White Channel (for RGBW/RGBCW lights)
- ✅ Color Temperature (for CCT/RGBCW lights)

Example automation:

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

---

## Advanced Configuration

### Custom Mesh Addresses

Assign specific mesh addresses to organize your lights:

```yaml
light:
  # Zone 1: Living Room (addresses 1-10)
  - platform: fastcon
    name: "Living Room Main"
    mesh_address: 1
    # ... other config
    
  - platform: fastcon
    name: "Living Room Accent"
    mesh_address: 2
    # ... other config
    
  # Zone 2: Bedroom (addresses 11-20)
  - platform: fastcon
    name: "Bedroom Main"
    mesh_address: 11
    # ... other config
```

### Multiple Phone Keys

If you have lights with different encryption keys:

```yaml
# Main component with default key
fastcon:
  id: fastcon_main
  phone_key: "A1A2A3A4"

light:
  - platform: fastcon
    name: "Light Group 1"
    fastcon_id: fastcon_main
    device_key: "11223344"  # Device-specific key
    # ... other config
```

### Status Monitoring

Add sensors to monitor system health:

```yaml
sensor:
  - platform: wifi_signal
    name: "Fastcon WiFi Signal"
    update_interval: 60s
    
  - platform: uptime
    name: "Fastcon Uptime"
    
  - platform: internal_temperature
    name: "ESP32 Temperature"

binary_sensor:
  - platform: status
    name: "Fastcon Status"
```

### Debug Logging

Enable detailed logging for troubleshooting:

```yaml
logger:
  level: DEBUG
  logs:
    fastcon: VERBOSE
    fastcon.component: VERBOSE
    fastcon.light: VERBOSE
    fastcon.protocol: DEBUG
```

---

## Troubleshooting

### Device Not Discovered

**Problem**: Lights not appearing in discovery logs

**Solutions**:
1. Check phone key is correct
2. Ensure lights are powered on and in range
3. Verify BLE address filter (should start with `0x11:0x22`)
4. Check logs for BLE scan errors
5. Try manual scan button press

```bash
# Check logs
esphome logs fastcon-esp32.yaml
```

### Lights Not Responding

**Problem**: Lights don't respond to commands

**Solutions**:
1. Verify mesh address is set correctly
2. Check device key matches discovery
3. Ensure device is bound (press "Bind All")
4. Verify BLE advertising is working
5. Check WiFi/Home Assistant connection

### Compilation Errors

**Problem**: ESPHome fails to compile

**Solutions**:
1. Verify component files are in correct location
2. Check board configuration matches your hardware
3. Update ESPHome to latest version
4. Check logs for specific errors:

```bash
esphome compile fastcon-esp32.yaml --verbose
```

### BLE 5.0 Not Supported

**Problem**: ESP32 board doesn't support extended advertising

**Solutions**:
- Use ESP32-C6, ESP32-S3, or ESP32-H2 (BLE 5.0 capable)
- Check board specifications
- Update ESP-IDF framework version

### Home Assistant Integration Issues

**Problem**: Device not appearing in Home Assistant

**Solutions**:
1. Check API encryption key matches
2. Verify Home Assistant can reach ESP32 IP
3. Check firewall settings (port 6053)
4. Try manual integration:
   - Go to **Settings → Devices & Services**
   - Click **+ ADD INTEGRATION**
   - Search for **ESPHome**
   - Enter ESP32 IP address

---

## Migration from Arduino/PlatformIO

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

### Preserving Device State

ESPHome maintains device state in Home Assistant automatically. No manual state management needed.

---

## Performance

### Resource Usage

- **Flash**: ~800KB (component code + ESPHome core)
- **RAM**: ~200KB (BLE + WiFi + component)
- **CPU**: <5% average (periodic BLE scanning)

### BLE Communication

- **Scan Interval**: Continuous (60s restart safety)
- **Command Duration**: 3 seconds per command
- **Range**: ~10-30 meters (typical BLE range)

### Network Traffic

- **API**: Minimal (state updates only)
- **Logging**: Configurable (disable for production)
- **OTA**: Only during updates

---

## Best Practices

### Security

1. **Use strong passwords** for OTA and AP
2. **Enable API encryption** (automatically generated)
3. **Keep firmware updated** for security patches
4. **Change default phone key** if possible
5. **Hide secrets.yaml** from version control

### Reliability

1. **Assign static IP** to ESP32 in router
2. **Use quality power supply** (5V 2A minimum)
3. **Keep firmware updated**
4. **Monitor WiFi signal strength**
5. **Test after power outages**

### Organization

1. **Use meaningful names** for devices
2. **Group lights by zone** using mesh addresses
3. **Document custom configurations**
4. **Use substitutions** for repeated values
5. **Comment complex automations**

---

## API Reference

### Fastcon Component

```yaml
fastcon:
  id: fastcon_hub              # Required: Component ID
  phone_key: "A1A2A3A4"        # Optional: BRMesh encryption key (default: A1A2A3A4)
  auto_discover: true          # Optional: Log discovered devices (default: true)
```

### Fastcon Light

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

### Actions

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

---

## Support & Resources

### Documentation

- **ESPHome Docs**: https://esphome.io/
- **Home Assistant**: https://www.home-assistant.io/
- **BLE on ESP32**: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/ble.html

### Community

- **Home Assistant Community**: https://community.home-assistant.io/
- **ESPHome Discord**: https://discord.gg/KhAMKrd

### Reporting Issues

When reporting issues, include:
1. **Board type** and ESPHome version
2. **Full YAML configuration** (redact secrets)
3. **Complete logs** with DEBUG level
4. **Steps to reproduce**

---

## Future Enhancements

Planned features for future releases:

- [ ] Scene support
- [ ] Group control
- [ ] Firmware version detection
- [ ] Signal strength (RSSI) reporting
- [ ] Dynamic device discovery entities
- [ ] Mesh network mapping
- [ ] Timer programming
- [ ] Effects and transitions

---

## License

This ESPHome component maintains the same license as the original fastConLight project.

---

## Changelog

### v2.0.0 (ESPHome Migration)
- Migrated from Arduino/PlatformIO to ESPHome
- Added native Home Assistant integration
- Implemented YAML-based configuration
- Added OTA update support
- Added web interface
- Improved logging and diagnostics
- Simplified setup process

---

**Last Updated**: February 24, 2026  
**Component Version**: 2.0.0  
**Compatible ESPHome**: 2023.12.0+
