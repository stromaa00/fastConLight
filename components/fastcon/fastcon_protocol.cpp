#include "fastcon_protocol.h"
#include "esphome/core/log.h"
#include <cstring>
#include <sstream>
#include <iomanip>

namespace esphome {
namespace fastcon {

static const char *const TAG = "fastcon.protocol";

// Constants
static const std::vector<uint8_t> DEFAULT_ENCRYPT_KEY = {0x5e, 0x36, 0x7b, 0xc4};
static const std::vector<uint8_t> DEFAULT_BLE_FASTCON_ADDRESS = {0xC1, 0xC2, 0xC3};
static const std::vector<uint8_t> BLE_PREDATA = {0x02, 0x01, 0x02, 0x1b, 0xff, 0xf0, 0xff};

// Static sequence tracking
static uint32_t SEND_SEQ = 0;
static int32_t SEND_COUNT = 0;

// Utility functions
std::string bytes_to_hex_string(const uint8_t *data, size_t len) {
  std::stringstream ss;
  ss << std::hex << std::setfill('0');
  for (size_t i = 0; i < len; i++) {
    ss << std::setw(2) << static_cast<int>(data[i]);
  }
  return ss.str();
}

bool hex_string_to_bytes(const std::string &hex, std::vector<uint8_t> &bytes) {
  if (hex.length() % 2 != 0)
    return false;
    
  bytes.clear();
  for (size_t i = 0; i < hex.length(); i += 2) {
    std::string byte_str = hex.substr(i, 2);
    bytes.push_back(static_cast<uint8_t>(std::stoi(byte_str, nullptr, 16)));
  }
  return true;
}

uint8_t reverse_8(uint8_t value) {
  uint8_t result = 0;
  for (int i = 0; i < 8; i++) {
    result |= ((value >> i) & 1) << (7 - i);
  }
  return result;
}

uint16_t crc16(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data) {
  const uint16_t polynomial = 0x1021;
  uint16_t crc = 0xFFFF;

  // Process address bytes
  for (uint8_t byte : addr) {
    crc ^= (byte << 8);
    for (int i = 0; i < 8; i++) {
      if (crc & 0x8000) {
        crc = (crc << 1) ^ polynomial;
      } else {
        crc = crc << 1;
      }
    }
  }

  // Process data bytes
  for (uint8_t byte : data) {
    crc ^= (byte << 8);
    for (int i = 0; i < 8; i++) {
      if (crc & 0x8000) {
        crc = (crc << 1) ^ polynomial;
      } else {
        crc = crc << 1;
      }
    }
  }

  return crc;
}

// FastconDeviceInfo methods
std::string FastconDeviceInfo::get_did_string() const {
  return bytes_to_hex_string(this->did, 6);
}

std::string FastconDeviceInfo::get_name_string() const {
  return bytes_to_hex_string(this->name, 2);
}

std::string FastconDeviceInfo::get_type_string() const {
  return bytes_to_hex_string(this->type, 2);
}

std::string FastconDeviceInfo::get_key_string() const {
  return bytes_to_hex_string(this->key, 4);
}

std::string FastconDeviceInfo::get_unique_id() const {
  return get_name_string() + "-" + get_did_string() + "-" + get_type_string() + "-" + get_key_string();
}

bool FastconDeviceInfo::is_light() const {
  uint16_t type_val = static_cast<uint16_t>(this->device_type);
  return (type_val == 43709 || type_val == 43051 || type_val == 43049 || 
          type_val == 43168 || type_val == 43050 || type_val == 43169 || 
          type_val == 43745 || type_val == 43759 || type_val == 43754);
}

// Encryption functions
void fastcon_encrypt(const uint8_t *src, uint8_t *dst, size_t size, const uint8_t *key) {
  for (size_t i = 0; i < size; i++) {
    dst[i] = key[i & 3] ^ src[i];
  }
}

// Whitening functions
void whitening_init(uint32_t val, WhiteningContext *ctx) {
  uint32_t v0[4] = {(val >> 5), (val >> 4), (val >> 3), (val >> 2)};

  ctx->f_0x0 = 1;
  ctx->f_0x4 = v0[0] & 1;
  ctx->f_0x8 = v0[1] & 1;
  ctx->f_0xc = v0[2] & 1;
  ctx->f_0x10 = v0[3] & 1;
  ctx->f_0x14 = (val >> 1) & 1;
  ctx->f_0x18 = val & 1;
}

void whitening_encode(std::vector<uint8_t> &data, WhiteningContext *ctx) {
  for (size_t i = 0; i < data.size(); ++i) {
    uint32_t varC = ctx->f_0xc;
    uint32_t var14 = ctx->f_0x14;
    uint32_t var18 = ctx->f_0x18;
    uint32_t var10 = ctx->f_0x10;
    uint32_t var8 = var14 ^ ctx->f_0x8;
    uint32_t var4 = var10 ^ ctx->f_0x4;
    uint32_t _var = var18 ^ varC;
    uint32_t var0 = _var ^ ctx->f_0x0;

    uint8_t c = data[i];
    data[i] = ((c & 0x80) ^ ((var8 ^ var18) << 7)) + ((c & 0x40) ^ (var0 << 6)) + 
              ((c & 0x20) ^ (var4 << 5)) + ((c & 0x10) ^ (var8 << 4)) + 
              ((c & 0x08) ^ (_var << 3)) + ((c & 0x04) ^ (var10 << 2)) + 
              ((c & 0x02) ^ (var14 << 1)) + ((c & 0x01) ^ (var18 << 0));

    ctx->f_0x8 = var4;
    ctx->f_0xc = var8;
    ctx->f_0x10 = var8 ^ varC;
    ctx->f_0x14 = var0 ^ var10;
    ctx->f_0x18 = var4 ^ var14;
    ctx->f_0x0 = var8 ^ var18;
    ctx->f_0x4 = var0;
  }
}

// RF payload generation
std::vector<uint8_t> get_rf_payload(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data) {
  const int data_offset = 0x12;
  const int inverse_offset = 0x0f;
  const int result_data_size = data_offset + addr.size() + data.size();
  std::vector<uint8_t> resultbuf(result_data_size + 2, 0);

  // Hardcoded header values
  resultbuf[0x0f] = 0x71;
  resultbuf[0x10] = 0x0f;
  resultbuf[0x11] = 0x55;

  // Reverse copy the address
  for (size_t i = 0; i < addr.size(); i++) {
    resultbuf[data_offset + addr.size() - i - 1] = addr[i];
  }

  // Copy data
  std::copy(data.begin(), data.end(), resultbuf.begin() + data_offset + addr.size());

  // Reverse bits for specific bytes
  for (size_t i = inverse_offset; i < inverse_offset + addr.size() + 3; i++) {
    resultbuf[i] = reverse_8(resultbuf[i]);
  }

  // Calculate and append CRC
  uint16_t crc = crc16(addr, data);
  resultbuf[result_data_size] = static_cast<uint8_t>(crc);
  resultbuf[result_data_size + 1] = static_cast<uint8_t>(crc >> 8);
  
  return resultbuf;
}

// Package BLE Fastcon body
std::vector<uint8_t> package_ble_fastcon_body(
    uint8_t i,
    uint8_t i2,
    uint32_t sequence,
    uint8_t safe_key,
    bool forward,
    const std::vector<uint8_t> &data,
    const std::vector<uint8_t> *key) {
  
  std::vector<uint8_t> body(data.size() + 4, 0);
  
  // bit 7 is forward, bit 6-4 is i2, bit 3-0 is i
  body[0] = ((i2 & 0b1111) << 0) | ((i & 0b111) << 4) | (static_cast<uint8_t>(forward) << 7);
  body[1] = static_cast<uint8_t>(sequence);
  body[2] = safe_key;
  body[3] = 0; // checksum placeholder

  std::copy(data.begin(), data.end(), body.begin() + 4);

  // Calculate checksum
  uint8_t checksum = 0;
  for (size_t cnt = 0; cnt < body.size(); ++cnt) {
    if (cnt == 3) continue; // skip checksum itself
    checksum = static_cast<uint8_t>(checksum + body[cnt]);
  }
  body[3] = checksum;

  // Encrypt header (first 4 bytes)
  for (size_t i = 0; i < 4; ++i) {
    body[i] = DEFAULT_ENCRYPT_KEY[i & 3] ^ body[i];
  }

  // Encrypt data payload
  const std::vector<uint8_t> &real_key = key != nullptr ? *key : DEFAULT_ENCRYPT_KEY;
  for (size_t i = 0; i < data.size(); ++i) {
    body[4 + i] = real_key[i & 3] ^ body[4 + i];
  }

  return body;
}

// Get payload with inner retry
std::vector<uint8_t> get_payload_with_inner_retry(
    uint8_t i,
    const std::vector<uint8_t> &data,
    uint8_t i2,
    std::vector<uint8_t> *key,
    bool forward,
    bool use_22_data) {
  
  if (use_22_data) {
    ESP_LOGE(TAG, "use_22_data not implemented");
    return {};
  }

  int32_t send_cnt = SEND_COUNT;
  uint8_t some_sequence;

  if (send_cnt >= 5 || i2 <= 1) {
    uint32_t next = SEND_SEQ + 1;
    SEND_SEQ = next;
    if (next == 0 || next == 256) {
      SEND_SEQ = 1; // reset sequence
    }
    some_sequence = SEND_SEQ;
  } else {
    some_sequence = (SEND_SEQ + 10) % 255;
  }

  uint8_t safe_key = (key != nullptr) ? (*key)[3] : 255;

  return package_ble_fastcon_body(i, i2, some_sequence, safe_key, forward, data, key);
}

// Command generation
std::vector<uint8_t> do_generate_command(
    uint8_t cmd_type,
    const std::vector<uint8_t> &data,
    const std::vector<uint8_t> *key,
    int32_t retry_count,
    int32_t send_interval,
    bool forward,
    bool use_default_adapter,
    bool use_22_data,
    uint8_t extended_addr) {
  
  if (use_22_data) {
    ESP_LOGE(TAG, "use_22_data not implemented");
    return {};
  }

  if (!use_default_adapter) {
    ESP_LOGE(TAG, "non-default adapter not implemented");
    return {};
  }

  extended_addr = std::max(extended_addr, static_cast<uint8_t>(0));
  
  std::vector<uint8_t> key_copy;
  if (key != nullptr) {
    key_copy = *key;
  }
  
  std::vector<uint8_t> payload = get_payload_with_inner_retry(
      cmd_type, data, extended_addr, key != nullptr ? &key_copy : nullptr, forward, use_22_data);
  
  payload = get_rf_payload(DEFAULT_BLE_FASTCON_ADDRESS, payload);

  WhiteningContext context;
  whitening_init(WHITENING_SEED, &context);
  whitening_encode(payload, &context);

  // Drop the first 0x0f bytes
  return std::vector<uint8_t>(payload.begin() + 0x0f, payload.end());
}

// Scan command
std::vector<uint8_t> generate_scan_command() {
  ESP_LOGD(TAG, "Generating scan command");
  return do_generate_command(
      0,  // command type
      {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},  // empty data
      nullptr,  // no key
      BLE_CMD_RETRY_CNT,
      -1,  // send interval
      false,  // not forward
      true,  // use default adapter
      false,  // not use_22_data
      0);  // extended addr
}

// Light command helpers
std::vector<uint8_t> create_on_command(uint8_t brightness) {
  std::vector<uint8_t> data(1);
  data[0] = 128 | (brightness & 127);
  return data;
}

std::vector<uint8_t> create_off_command() {
  return {0};
}

std::vector<uint8_t> create_brightness_command(uint8_t brightness) {
  std::vector<uint8_t> data(1);
  data[0] = brightness & 127;
  return data;
}

std::vector<uint8_t> create_rgb_command(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness, bool absolute) {
  std::vector<uint8_t> arr(6, 0);
  const float color_norm = absolute ? 1.0f : 255.0f / (r + g + b);
  arr[0] = 128 | (brightness & 127);  // on + brightness
  arr[1] = static_cast<uint8_t>(b * color_norm);
  arr[2] = static_cast<uint8_t>(r * color_norm);
  arr[3] = static_cast<uint8_t>(g * color_norm);
  arr[4] = 0;
  arr[5] = 0;
  return arr;
}

std::vector<uint8_t> create_white_command(uint8_t whiteness) {
  std::vector<uint8_t> arr(6, 0);
  arr[0] = 128 | 127;  // on + max brightness
  arr[1] = 0;
  arr[2] = 0;
  arr[3] = 0;
  arr[4] = whiteness;
  arr[5] = whiteness;
  return arr;
}

// Single control command
std::vector<uint8_t> generate_light_command(
    uint8_t addr,
    const std::vector<uint8_t> &key,
    const std::vector<uint8_t> &data) {
  
  std::vector<uint8_t> result_data(12, 0);
  result_data[0] = 2 | (((0xfffffff & (data.size() + 1)) << 4) & 0xFF);
  result_data[1] = addr & 0xFF;
  std::copy(data.begin(), data.end(), result_data.begin() + 2);

  std::vector<uint8_t> key_copy = key;
  
  return do_generate_command(
      5,  // command type for single control
      result_data,
      &key_copy,
      BLE_CMD_RETRY_CNT,
      BLE_CMD_ADVERTISE_LENGTH,
      true,  // forward
      true,  // use default adapter
      addr > 256,  // use_22_data
      static_cast<uint8_t>(addr / 256));  // extended addr
}

// Bind command
std::vector<uint8_t> generate_bind_command(const FastconDeviceInfo &device_info) {
  // Discovery response command
  std::vector<uint8_t> data(12, 0);
  data[0] = 0x12;  // Discovery response type
  data[1] = device_info.addr;
  std::copy(std::begin(device_info.name), std::end(device_info.name), data.begin() + 2);
  
  std::vector<uint8_t> key(device_info.key, device_info.key + 4);
  
  return do_generate_command(
      5,  // command type
      data,
      &key,
      BLE_CMD_RETRY_CNT,
      BLE_CMD_ADVERTISE_LENGTH,
      true,  // forward
      true,  // use default adapter
      false,
      0);
}

// Parse BLE broadcast
bool parse_ble_broadcast(
    const uint8_t *data,
    size_t data_len,
    const std::vector<uint8_t> &phone_key,
    FastconDeviceInfo &device_info) {
  
  if (data_len < 16) {
    ESP_LOGW(TAG, "BLE broadcast too short: %d bytes", data_len);
    return false;
  }

  // Decrypt header
  uint8_t header[4];
  for (int i = 0; i < 4; i++) {
    header[i] = DEFAULT_ENCRYPT_KEY[i & 3] ^ data[i];
  }

  uint8_t header_type = (header[0] >> 4) & 7;

  switch (header_type) {
    case 1: {
      // Device discovery broadcast
      // Format: DID(6) + Name(2) + Type(2) + Key(4)
      std::memcpy(device_info.did, &data[4], 6);
      std::memcpy(device_info.name, &data[10], 2);
      std::memcpy(device_info.type, &data[12], 2);
      std::memcpy(device_info.key, &data[14], 4);
      
      // Parse device type
      uint16_t type_val = (device_info.type[0] << 8) | device_info.type[1];
      device_info.device_type = static_cast<DeviceType>(type_val);
      device_info.addr = 0;
      
      ESP_LOGD(TAG, "Parsed device: %s", device_info.get_unique_id().c_str());
      return true;
    }
    
    case 3: {
      // Heartbeat or other status - not used for discovery
      ESP_LOGV(TAG, "Received status broadcast (type 3)");
      return false;
    }
    
    default:
      ESP_LOGD(TAG, "Unknown broadcast header type: %d", header_type);
      return false;
  }
}

}  // namespace fastcon
}  // namespace esphome
