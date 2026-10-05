# FastConLight - Functional Specification

## 1. Executive Summary

FastConLight is an ESP32-based IoT gateway system that bridges BRMesh/Fastcon Bluetooth Low Energy (BLE) lighting devices with Home Assistant through MQTT. The system enables centralized control and automation of BLE mesh lighting networks through Home Assistant's user interface.

**Version:** 1.0.0  
**Platform:** ESP32 (Multiple board support)  
**Framework:** Arduino  
**Date:** February 24, 2026

---

## 2. System Overview

### 2.1 Purpose
The system acts as a protocol translator and bridge, allowing BRMesh/Fastcon BLE lighting products to be discovered, controlled, and automated through Home Assistant without requiring the proprietary BRMesh mobile application.

### 2.2 High-Level Architecture

```
BLE Mesh Lights <---> ESP32 Gateway <---> MQTT Broker <---> Home Assistant
                      (FastConLight)
```

### 2.3 Key Technologies
- **Hardware:** ESP32 with BLE 5.0 support
- **Communication Protocols:** 
  - BLE Extended Advertising (for light discovery and control)
  - WiFi (for network connectivity)
  - MQTT (for Home Assistant integration)
- **Integration:** ArduinoHA library for Home Assistant Auto-Discovery

---

## 3. Supported Hardware Platforms

The system supports multiple ESP32 board variants:

| Board | BLE Version | Programming Pin | Special Notes |
|-------|-------------|-----------------|---------------|
| Heltec WiFi LoRa 32 V3 | BLE 5.0 | GPIO 0 | Debug support, custom partition |
| TTGO T-Beam | BLE 5.0 | GPIO 0 | - |
| ESP32-C6 DevKitC-1 | BLE 5.0 | GPIO 0 | Custom partition table |
| Generic ESP32-POE | BLE 4.2 | GPIO 39 | Power-over-Ethernet variant |

---

## 4. Functional Requirements

### 4.1 Device Discovery

#### 4.1.1 BLE Scanning
- **FR-001:** The system SHALL continuously scan for BLE extended advertisements
- **FR-002:** The system SHALL filter devices with address prefix `0x11:0x22`
- **FR-003:** The system SHALL decode BLE payloads starting with `13FFF0FF`
- **FR-004:** The system SHALL decrypt device information using configured phone keys
- **FR-005:** Scan parameters:
  - Scan type: Active
  - Scan interval: 40 units
  - Scan window: 40 units
  - Both coded and uncoded PHY supported

#### 4.1.2 Device Information Parsing
Each discovered device contains:
- **DID (Device ID):** 6-byte unique identifier
- **Name:** 2-byte device name
- **Type:** 2-byte device type code
- **Key:** 4-byte encryption key
- **Address:** 1-byte mesh address (0-255)
- **Status:** Device binding status

#### 4.1.3 Supported Device Types
The system recognizes the following BRMesh device types:

| Device Type | Code | Description |
|-------------|------|-------------|
| Light_RGBCW | 43050 (0xA83A) | RGB + Cold/Warm White |
| Light_RGB | 43168 (0xA8A0) | RGB color |
| Light_CCT | 43051 (0xA83B) | Color temperature adjustable |
| Light_RGBW | 43169 (0xA8A1) | RGB + White |
| Light_PWR | 43049 (0xA839) | Power control |
| Panel_3/4/6/8 | Various | Switch panels |
| Relay_1/2/4 | Various | Relay switches |
| Curtain | 43499 (0xA9DB) | Curtain controller |
| Fan | 43531 (0xA9FB) | Fan controller |
| Gateway | 43500 (0xA9DC) | Mesh gateway |

### 4.2 Home Assistant Integration

#### 4.2.1 Device Registration
- **FR-010:** The system SHALL automatically register discovered devices with Home Assistant via MQTT discovery
- **FR-011:** Each device SHALL have a unique identifier: `{NAME}-{DID}-{TYPE}-{KEY}`
- **FR-012:** Device entities SHALL be created under the "FastconESP" device
- **FR-013:** Device metadata SHALL include:
  - Manufacturer: "Dodosoft"
  - Model: "BRMesh"
  - Software Version: "1.0.0"

#### 4.2.2 MQTT Topics
Discovery topic format: `homeassistant/light/{uniqueId}/config`  
Command topic format: `aha/{uniqueId}/cmd_t`  
State topic format: `aha/{uniqueId}/state_t`

### 4.3 Light Control Features

#### 4.3.1 Basic Controls
- **FR-020:** ON/OFF control
- **FR-021:** Brightness control (0-255)
- **FR-022:** Default on brightness: 128 (50%)

#### 4.3.2 Color Controls
- **FR-023:** RGB color control (0-255 per channel)
- **FR-024:** White channel control (0-255)
- **FR-025:** Color temperature control (mireds)
- **FR-026:** RGB commands SHALL support both absolute and relative modes

#### 4.3.3 Command Transmission
- **FR-030:** Commands SHALL be transmitted via BLE extended advertising
- **FR-031:** Advertisement duration: 3000ms per command
- **FR-032:** Commands SHALL be encrypted using device-specific keys
- **FR-033:** Commands SHALL use whitening encoding with seed 0x25
- **FR-034:** BLE address for commands: `0xC1:0xC2:0xC3` (default)

### 4.4 Device Binding

#### 4.4.1 Binding Process
- **FR-040:** Each light SHALL have an assignable mesh address (0-255)
- **FR-041:** Binding SHALL send device discovery response to establish mesh address
- **FR-042:** The system SHALL provide a "Bind All" function to bind all discovered devices
- **FR-043:** Each device SHALL have an associated HASelect control for address selection

#### 4.4.2 Address Management
- **FR-044:** Address selector SHALL offer values 0-6
- **FR-045:** Changing address SHALL trigger automatic rebinding
- **FR-046:** Address format in topic: `sel_{deviceName}`

### 4.5 User Interface Controls

#### 4.5.1 Physical Button
- **FR-050:** A physical button (PRG_PIN) SHALL provide manual control
- **FR-051:** Short press (<1 second) SHALL trigger network scan
- **FR-052:** Long press (≥1 second) SHALL trigger "Bind All"
- **FR-053:** Button state SHALL be checked every 100ms

#### 4.5.2 Home Assistant Buttons
- **FR-054:** "Scan" button entity SHALL initiate BLE device discovery
- **FR-055:** "Bind" button entity SHALL bind all discovered devices
- **FR-056:** Buttons SHALL use icon: `mdi:magnify-scan`

### 4.6 Network Configuration

#### 4.6.1 WiFi Connection
- **FR-060:** The system SHALL connect to configured WiFi network at startup
- **FR-061:** Connection status SHALL be monitored and logged
- **FR-062:** The system SHALL wait indefinitely for WiFi connection

#### 4.6.2 MQTT Connection
- **FR-063:** The system SHALL connect to MQTT broker using configured credentials
- **FR-064:** MQTT broker address: Configurable IPv4
- **FR-065:** MQTT port: 1883 (default, non-TLS)
- **FR-066:** The system SHALL subscribe to `aha/#` topic on connection
- **FR-067:** Connection status SHALL be monitored continuously

### 4.7 Command Processing

#### 4.7.1 MQTT Message Handling
- **FR-070:** Incoming MQTT messages SHALL be parsed for topic and payload
- **FR-071:** Unknown devices in topics SHALL trigger automatic device creation
- **FR-072:** Device names SHALL be extracted from topic path: `aha/{uniqueId}/*`
- **FR-073:** Auto-created devices SHALL use uniqueId format validation

#### 4.7.2 Light Command Encoding
Commands are encoded with the following structure:
- **FR-080:** Payload generation with inner retry mechanism
- **FR-081:** RF payload encapsulation with mesh address
- **FR-082:** Whitening encoding for BLE transmission
- **FR-083:** BLE advertisement data prefix: `0x02,0x01,0x02,0x1b,0xff,0xf0,0xff`

---

## 5. Non-Functional Requirements

### 5.1 Performance
- **NFR-001:** BLE scan SHALL be continuous with minimal latency
- **NFR-002:** MQTT loop SHALL execute every 100ms
- **NFR-003:** Command transmission shall complete within 3 seconds
- **NFR-004:** System SHALL support minimum 10 concurrent light devices

### 5.2 Reliability
- **NFR-010:** System SHALL auto-reconnect to WiFi if connection lost
- **NFR-011:** System SHALL auto-reconnect to MQTT if connection lost
- **NFR-012:** Device state SHALL be persisted in Home Assistant
- **NFR-013:** Duplicate device registration SHALL be prevented

### 5.3 Security
- **NFR-020:** BLE commands SHALL be encrypted using device-specific keys
- **NFR-021:** Default phone key: `0xA1,0xA2,0xA3,0xA4`
- **NFR-022:** MQTT connection SHALL support username/password authentication
- **NFR-023:** WiFi credentials SHALL be stored in firmware (compile-time)

### 5.4 Maintainability
- **NFR-030:** Serial debug output SHALL be provided at 115200 baud
- **NFR-031:** Debug build type SHALL be enabled by default
- **NFR-032:** Code SHALL be modular with separate headers for:
  - BLE tools
  - Light commands
  - Device management
  - MQTT extensions

### 5.5 Compatibility
- **NFR-040:** Home Assistant auto-discovery protocol compliance
- **NFR-041:** MQTT 3.1.1 protocol support
- **NFR-042:** BLE 5.0 extended advertising support
- **NFR-043:** BLE 4.2 fallback for legacy hardware

---

## 6. System Constraints

### 6.1 Hardware Constraints
- **C-001:** Minimum 520KB RAM required for BLE + WiFi operation
- **C-002:** BLE must support extended advertising callbacks
- **C-003:** ESP32-C6 requires custom partition table for sufficient storage

### 6.2 Software Constraints
- **C-010:** Arduino framework required
- **C-011:** PlatformIO build system
- **C-012:** ArduinoBLE library v1.3.7+
- **C-013:** PubSubClient v2.8+
- **C-014:** ArduinoJson v7.0.4+

### 6.3 Network Constraints
- **C-020:** WiFi 2.4GHz network required
- **C-021:** MQTT broker must be accessible on local network
- **C-022:** Home Assistant instance required for full functionality

---

## 7. Data Models

### 7.1 FastconDevice Class
```cpp
Properties:
- cnt: uint8_t (command counter, typically 1)
- key[4]: char (encryption key)
- did[6]: unsigned char (device ID)
- name[2]: unsigned char (device name)
- high[1]: unsigned char (high byte data)
- addr: unsigned char (mesh address 0-255)
- type[2]: char (device type code)
- deviceType: EBLEDeviceTypes (enum)
- status: int (binding status)

Methods:
- Name(): String (returns hex name)
- Did(): String (returns hex DID)
- Key(): String (returns hex key)
- getUniqueFullname(): String (composite identifier)
- toString(): String (debug output)
- toBindString(): String (binding representation)
```

### 7.2 FastconHALight Class
Extends: HALight, FastconDevice

```cpp
Methods:
- bind(boolean rebind): int
- turn_on(char brightness): void
- turn_off(): void
- set_brightness(char brightness): void
- set_white(char whiteness): void
- set_rgb(r, g, b, brightness, abs): void
```

---

## 8. System States and Behaviors

### 8.1 Startup Sequence
1. Initialize serial communication (115200 baud)
2. Log ESP32 MAC address
3. Configure GPIO pins (PRG_PIN as input)
4. Initialize WiFi and connect to network
5. Configure Home Assistant device metadata
6. Initialize MQTT connection
7. Subscribe to `aha/#` topic
8. Initialize BLE device and scanner
9. Configure extended scan parameters
10. Start continuous BLE scanning
11. Register Scan and Bind button entities
12. Enter main loop

### 8.2 Operational States
- **Scanning:** Continuous BLE device discovery
- **Connected:** WiFi and MQTT connected, ready for commands
- **Disconnected:** Network connection lost, attempting reconnection
- **Binding:** Performing device address binding operation
- **Commanding:** Transmitting BLE command via advertising

### 8.3 Device Discovery Flow
```
BLE Advertisement Received
    ↓
Filter by Address Prefix (0x11:0x22)
    ↓
Check Payload Header (13FFF0FF)
    ↓
Decrypt Payload with Phone Key
    ↓
Parse Device Information
    ↓
Check if Device Already Exists
    ↓
Create HALight Entity
    ↓
Create Address Selector Entity
    ↓
Register with Home Assistant
    ↓
Log Success
```

### 8.4 Command Processing Flow
```
MQTT Command Received
    ↓
Parse Topic for Device ID
    ↓
Lookup Device or Auto-Create
    ↓
Extract Command Type & Parameters
    ↓
Call Device Method (turn_on/off, set_brightness, etc.)
    ↓
Generate BLE Command Payload
    ↓
Encrypt & Encode Command
    ↓
Transmit as BLE Extended Advertisement (3s)
    ↓
Update Home Assistant State
```

---

## 9. Configuration Parameters

### 9.1 Compile-Time Configuration
Located in: `src/main.cpp`

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| MQTT_BROKER_ADDR | 192.168.1.111 | MQTT broker IP address |
| MQTT_BROKER_USER | "homeassistant" | MQTT username |
| MQTT_BROKER_PASS | (configured) | MQTT password |
| WIFI_SSID | (configured) | WiFi network name |
| WIFI_PASS | (configured) | WiFi password |
| DEFAULT_PHONE_KEY | 0xA1,0xA2,0xA3,0xA4 | BLE device encryption key |
| PRG_PIN | (board-specific) | Physical button GPIO |

### 9.2 BLE Configuration
Located in: `src/bletools.h` and `src/bletools.cpp`

| Parameter | Value | Description |
|-----------|-------|-------------|
| BLE_CMD_ADVERTISE_LENGTH | 3000 ms | Advertisement duration |
| BLE_CMD_SEND_TIME | 3000 ms | Command send time |
| BLE_CMD_RETRY_CNT | 1 | Number of retries |
| DEFAULT_BLE_FASTCON_ADDRESS | 0xC1,0xC2,0xC3 | BLE command address |
| WHITENING_SEED | 0x25 | Whitening algorithm seed |

---

## 10. Error Handling

### 10.1 WiFi Connection Errors
- **E-001:** If WiFi connection fails, system waits indefinitely
- **E-002:** Connection status logged to serial every 500ms
- **E-003:** WiFi status code displayed for diagnostic purposes

### 10.2 MQTT Errors
- **E-010:** MQTT connection status checked continuously
- **E-011:** Failed connection logged to serial
- **E-012:** Automatic reconnection attempted on loop()

### 10.3 BLE Errors
- **E-020:** Invalid BLE address prefix ignored silently
- **E-021:** Payload parsing failures logged to serial
- **E-022:** Unknown device types still registered (generic handling)

### 10.4 Command Errors
- **E-030:** Unknown MQTT topics logged and device auto-created if valid format
- **E-031:** Invalid uniqueId format results in no device creation
- **E-032:** Unsupported command types throw runtime_error (logged)

---

## 11. Logging and Diagnostics

### 11.1 Startup Logs
- ESP32 MAC address (Device ID)
- WiFi connection status and IP address
- MQTT connection status
- BLE initialization status

### 11.2 Operational Logs
- Device discovery events (with device details)
- MQTT message reception (topic + payload)
- Command execution (with parameters)
- Button press events (short/long)
- Binding operations
- Number of registered devices

### 11.3 Debug Information
All logs output to Serial at 115200 baud with format:
```
[Event Type]: [Details]
```

---

## 12. Extension Points

### 12.1 Adding New Device Types
1. Add enum entry to `EBLEDeviceTypes` in `FastconDevice.h`
2. Device automatically discovered and created as generic light
3. Custom behavior requires subclassing `FastconHALight`

### 12.2 Custom Commands
1. Add command function to `blelight.cpp`
2. Register callback in device initialization
3. Implement BLE payload generation
4. Call `sendAdvertise()` with generated payload

### 12.3 Additional Controls
1. Create new `HASelect` or `HAButton` entity
2. Register with `mqtt` object
3. Implement `onCommand` callback
4. Command processing similar to existing controls

---

## 13. Known Limitations

### 13.1 Current Limitations
- **L-001:** No TLS support for MQTT (unencrypted communication)
- **L-002:** WiFi credentials hardcoded at compile time
- **L-003:** No web interface implementation (index.html empty)
- **L-004:** Maximum address selector range: 0-6 (limited by implementation)
- **L-005:** No persistent storage of device bindings (lost on reboot)
- **L-006:** Single MQTT broker support (no failover)

### 13.2 Platform Limitations
- **L-010:** BLE 5.0 extended advertising required for full functionality
- **L-011:** ESP32-POE limited to BLE 4.2 (reduced capabilities)
- **L-012:** Custom partition table required for ESP32-C6

---

## 14. Future Enhancements

### 14.1 Planned Features
1. Web-based configuration interface
2. OTA (Over-The-Air) firmware updates
3. Persistent device storage (SPIFFS/LittleFS)
4. TLS/SSL support for MQTT
5. WiFi Manager for runtime configuration
6. Multiple MQTT broker support
7. Extended address range (0-255)
8. Scene support
9. Device groups
10. Firmware status reporting

### 14.2 Potential Improvements
- Rate limiting for BLE commands
- Command queuing system
- Device health monitoring
- Signal strength reporting (RSSI)
- Network diagnostics dashboard
- LED status indicators
- Factory reset functionality

---

## 15. Testing Requirements

### 15.1 Unit Testing
- Device discovery and parsing
- Command encoding and encryption
- MQTT message handling
- Whitening/encryption algorithms

### 15.2 Integration Testing
- End-to-end light control from Home Assistant
- Multiple device concurrent operation
- Network reconnection scenarios
- Physical button operation
- Device binding process

### 15.3 Performance Testing
- Maximum supported devices
- Command latency measurements
- BLE range testing
- Memory usage profiling
- Long-term stability testing (24+ hours)

---

## 16. Dependencies

### 16.1 Core Libraries
- **ArduinoBLE** v1.3.7+ (BLE functionality)
- **PubSubClient** v2.8+ (MQTT client)
- **ArduinoJson** v7.0.4+ (JSON parsing/generation)
- **WiFi** (built-in, ESP32 WiFi stack)

### 16.2 Custom Components
- **arduino-home-assistant** (included in lib/)
  - HADevice
  - HAMqtt
  - HALight
  - HAButton
  - HASelect

### 16.3 Platform Dependencies
- ESP32 Arduino Core
- ESP-IDF BLE stack
- LWIP networking stack

---

## 17. Deployment

### 17.1 Build Configuration
1. Select appropriate environment in `platformio.ini`
2. Configure WiFi/MQTT credentials in `main.cpp`
3. Set phone key if different from default
4. Build using PlatformIO: `pio run -e [environment]`
5. Upload to device: `pio run -e [environment] -t upload`

### 17.2 Initial Setup
1. Flash firmware to ESP32 device
2. Device connects to configured WiFi
3. Device registers with Home Assistant automatically
4. Press physical button to scan for lights
5. Devices appear in Home Assistant as they're discovered
6. Long-press button or use Bind button to bind all devices

### 17.3 Home Assistant Configuration
- No manual configuration required (auto-discovery)
- Devices appear under MQTT integration
- FastconESP device with child light entities
- Control through standard Home Assistant light interface

---

## 18. Glossary

| Term | Definition |
|------|------------|
| BRMesh | Proprietary BLE mesh networking protocol for smart lighting |
| Fastcon | Brand/protocol name for BRMesh-based devices |
| Extended Advertising | BLE 5.0 feature allowing longer advertisement payloads |
| Whitening | BLE encoding technique to ensure signal spectrum distribution |
| DID | Device ID, unique 6-byte identifier for each device |
| HAMqtt | Home Assistant MQTT integration class |
| Mesh Address | Logical address (0-255) assigned to device in mesh network |
| Phone Key | 4-byte encryption key used to encrypt/decrypt commands |
| Binding | Process of assigning mesh address to device |
| Mireds | Unit for color temperature (micro reciprocal degrees) |

---

## 19. References

### 19.1 External Documentation
- Home Assistant MQTT Discovery: https://www.home-assistant.io/integrations/mqtt/
- ESP32 BLE Documentation: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/bluetooth/
- PlatformIO Documentation: https://docs.platformio.org/

### 19.2 Internal Documentation
- ArduinoHA Library: `lib/arduino-home-assistant/docs/`
- BRMesh Protocol: Reverse-engineered from BRMesh mobile app

---

## 20. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-02-24 | System Analysis | Initial functional specification |

---

**Document Status:** Draft  
**Approval Status:** Pending Review  
**Next Review Date:** TBD
