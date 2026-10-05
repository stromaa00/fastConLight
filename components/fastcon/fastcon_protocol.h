#pragma once

#include <vector>
#include <string>
#include <cstdint>

namespace esphome {
namespace fastcon {

// BLE configuration constants
constexpr uint32_t BLE_CMD_RETRY_CNT = 1;
constexpr uint32_t BLE_CMD_ADVERTISE_LENGTH = 3000;  // 3 seconds
constexpr uint8_t WHITENING_SEED = 0x25;

// Device type enumeration
enum class DeviceType : uint16_t {
  CURTAIN = 43499,
  FAN = 43531,
  GATEWAY = 43500,
  GATEWAY_AC = 43756,
  GATEWAY_IHG = 10058,
  LIGHT_BURDEN_CW = 43754,
  LIGHT_BURDEN_W = 43759,
  LIGHT_CCT = 43051,
  LIGHT_COMPOSE = 43709,
  LIGHT_PWR = 43049,
  LIGHT_RGB = 43168,
  LIGHT_RGBCW = 43050,
  LIGHT_RGBW = 43169,
  LIGHT_W_CW = 43745,
  META_PAD = 43518,
  META_PAD_2 = 43974,
  PANEL_3 = 43463,
  PANEL_3_WIRELESS = 43462,
  PANEL_4 = 43473,
  PANEL_4_WIRELESS = 43472,
  PANEL_6 = 43461,
  PANEL_6_WIRELESS = 43459,
  PANEL_8 = 43733,
  PANEL_8_2 = 43734,
  RELAY_1 = 43525,
  RELAY_2 = 43474,
  RELAY_4 = 43680,
  SENSOR_DOOR = 43505,
  SENSOR_IR = 43516,
  SENSOR_RADAR = 43808,
  SENSOR_WATER = 43791,
  THERMOSTAT = 43919,
};

// Device information structure parsed from BLE broadcast
struct FastconDeviceInfo {
  uint8_t did[6];      // Device ID
  uint8_t name[2];     // Device name
  uint8_t type[2];     // Device type
  uint8_t key[4];      // Device encryption key
  uint8_t addr;        // Mesh address
  DeviceType device_type;
  
  std::string get_did_string() const;
  std::string get_name_string() const;
  std::string get_type_string() const;
  std::string get_key_string() const;
  std::string get_unique_id() const;
  bool is_light() const;
};

// Whitening context for BLE encoding
struct WhiteningContext {
  uint32_t f_0x0;
  uint32_t f_0x4;
  uint32_t f_0x8;
  uint32_t f_0xc;
  uint32_t f_0x10;
  uint32_t f_0x14;
  uint32_t f_0x18;
};

// Protocol functions

// BLE command generation
std::vector<uint8_t> generate_scan_command();
std::vector<uint8_t> generate_bind_command(const FastconDeviceInfo &device_info);
std::vector<uint8_t> generate_light_command(
    uint8_t addr,
    const std::vector<uint8_t> &key,
    const std::vector<uint8_t> &data);

// Light control commands
std::vector<uint8_t> create_on_command(uint8_t brightness);
std::vector<uint8_t> create_off_command();
std::vector<uint8_t> create_brightness_command(uint8_t brightness);
std::vector<uint8_t> create_rgb_command(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness, bool absolute);
std::vector<uint8_t> create_white_command(uint8_t whiteness);

// BLE broadcast parsing
bool parse_ble_broadcast(
    const uint8_t *data,
    size_t data_len,
    const std::vector<uint8_t> &phone_key,
    FastconDeviceInfo &device_info);

// Encryption and encoding
void fastcon_encrypt(const uint8_t *src, uint8_t *dst, size_t size, const uint8_t *key);
void whitening_init(uint32_t val, WhiteningContext *ctx);
void whitening_encode(std::vector<uint8_t> &data, WhiteningContext *ctx);
uint16_t crc16(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data);
uint8_t reverse_8(uint8_t value);

// Command building helpers
std::vector<uint8_t> get_rf_payload(
    const std::vector<uint8_t> &addr,
    const std::vector<uint8_t> &data);

std::vector<uint8_t> get_payload_with_inner_retry(
    uint8_t cmd_type,
    const std::vector<uint8_t> &data,
    uint8_t retry_count,
    const std::vector<uint8_t> *key,
    bool forward,
    bool use_22_data);

std::vector<uint8_t> do_generate_command(
    uint8_t cmd_type,
    const std::vector<uint8_t> &data,
    const std::vector<uint8_t> *key,
    int32_t retry_count,
    int32_t send_interval,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t extended_addr);

// Utility functions
std::string bytes_to_hex_string(const uint8_t *data, size_t len);
bool hex_string_to_bytes(const std::string &hex, std::vector<uint8_t> &bytes);

}  // namespace fastcon
}  // namespace esphome
