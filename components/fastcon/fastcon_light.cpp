#include "fastcon_light.h"
#include "fastcon_component.h"
#include "esphome/core/log.h"

namespace esphome {
namespace fastcon {

static const char *const TAG = "fastcon.light";

void FastconLight::setup() {
  ESP_LOGCONFIG(TAG, "Setting up Fastcon Light: %s", this->get_unique_id().c_str());
}

void FastconLight::dump_config() {
  ESP_LOGCONFIG(TAG, "Fastcon Light:");
  ESP_LOGCONFIG(TAG, "  Unique ID: %s", this->get_unique_id().c_str());
  ESP_LOGCONFIG(TAG, "  Device ID: %s", this->device_info_.get_did_string().c_str());
  ESP_LOGCONFIG(TAG, "  Device Type: %s", this->device_info_.get_type_string().c_str());
  ESP_LOGCONFIG(TAG, "  Device Key: %s", this->device_info_.get_key_string().c_str());
  ESP_LOGCONFIG(TAG, "  Mesh Address: %d", this->mesh_address_);
}

light::LightTraits FastconLight::get_traits() {
  auto traits = light::LightTraits();
  
  // Determine capabilities based on device type
  uint16_t type_val = static_cast<uint16_t>(this->device_info_.device_type);
  
  // All lights support brightness
  traits.set_supported_color_modes({light::ColorMode::BRIGHTNESS});
  
  // RGB lights
  if (type_val == 43168 || type_val == 43050 || type_val == 43169) {  // RGB, RGBCW, RGBW
    traits.set_supported_color_modes({light::ColorMode::RGB});
  }
  
  // CCT (color temperature) lights
  if (type_val == 43051 || type_val == 43050 || type_val == 43745) {  // CCT, RGBCW, W_CW
    traits.set_min_mireds(153);  // ~6500K
    traits.set_max_mireds(500);  // ~2000K
  }

  return traits;
}

void FastconLight::write_state(light::LightState *state) {
  float red, green, blue, white, brightness;
  state->current_values_as_rgbw(&red, &green, &blue, &white);
  state->current_values_as_brightness(&brightness);

  ESP_LOGD(TAG, "Light %s - State: %s, Brightness: %.2f, RGB: (%.2f, %.2f, %.2f), White: %.2f",
           this->get_unique_id().c_str(), ONOFF(state->current_values.is_on()),
           brightness, red, green, blue, white);

  std::vector<uint8_t> data;

  if (!state->current_values.is_on()) {
    // Turn off
    data = create_off_command();
    this->send_command_(data);
    this->last_state_ = false;
    return;
  }

  this->last_state_ = true;
  
  // Convert 0-1 range to 0-255
  uint8_t brightness_u8 = static_cast<uint8_t>(brightness * 255.0f);
  uint8_t red_u8 = static_cast<uint8_t>(red * 255.0f);
  uint8_t green_u8 = static_cast<uint8_t>(green * 255.0f);
  uint8_t blue_u8 = static_cast<uint8_t>(blue * 255.0f);
  uint8_t white_u8 = static_cast<uint8_t>(white * 255.0f);

  // Check what changed to send appropriate command
  bool color_changed = (red != this->last_red_ || green != this->last_green_ || blue != this->last_blue_);
  bool white_changed = (white != this->last_white_);
  bool brightness_changed = (brightness != this->last_brightness_);

  if (color_changed && (red_u8 > 0 || green_u8 > 0 || blue_u8 > 0)) {
    // RGB color command
    data = create_rgb_command(red_u8, green_u8, blue_u8, brightness_u8, false);
    this->send_command_(data);
  } else if (white_changed && white_u8 > 0) {
    // White command
    data = create_white_command(white_u8);
    this->send_command_(data);
  } else if (brightness_changed) {
    // Just brightness
    data = create_on_command(brightness_u8);
    this->send_command_(data);
  } else {
    // Default: turn on with brightness
    data = create_on_command(brightness_u8);
    this->send_command_(data);
  }

  // Update last known state
  this->last_brightness_ = brightness;
  this->last_red_ = red;
  this->last_green_ = green;
  this->last_blue_ = blue;
  this->last_white_ = white;
}

void FastconLight::set_device_id(const std::vector<uint8_t> &did) {
  if (did.size() == 6) {
    std::copy(did.begin(), did.end(), this->device_info_.did);
  }
}

void FastconLight::set_device_type(const std::vector<uint8_t> &type) {
  if (type.size() == 2) {
    std::copy(type.begin(), type.end(), this->device_info_.type);
    uint16_t type_val = (type[0] << 8) | type[1];
    this->device_info_.device_type = static_cast<DeviceType>(type_val);
  }
}

void FastconLight::set_device_key(const std::vector<uint8_t> &key) {
  if (key.size() == 4) {
    std::copy(key.begin(), key.end(), this->device_info_.key);
  }
}

void FastconLight::bind() {
  ESP_LOGI(TAG, "Binding light %s at address %d", this->get_unique_id().c_str(), this->mesh_address_);
  
  // Set the address in device info
  this->device_info_.addr = this->mesh_address_;
  
  // Generate and send bind command
  std::vector<uint8_t> bind_cmd = generate_bind_command(this->device_info_);
  
  if (this->parent_ != nullptr) {
    this->parent_->send_ble_command(bind_cmd);
  }
}

void FastconLight::send_command_(const std::vector<uint8_t> &data) {
  if (this->parent_ == nullptr) {
    ESP_LOGW(TAG, "No parent component set for light");
    return;
  }

  // Get device key as vector
  std::vector<uint8_t> key(this->device_info_.key, this->device_info_.key + 4);
  
  // Generate light command
  std::vector<uint8_t> command = generate_light_command(this->mesh_address_, key, data);
  
  // Send via parent component
  this->parent_->send_ble_command(command);
  
  ESP_LOGD(TAG, "Sent command to %s (addr: %d), data size: %d", 
           this->get_unique_id().c_str(), this->mesh_address_, data.size());
}

}  // namespace fastcon
}  // namespace esphome
