#pragma once

#include "esphome/core/component.h"
#include "esphome/components/light/light_output.h"
#include "esphome/components/light/light_state.h"
#include "fastcon_protocol.h"

namespace esphome {
namespace fastcon {

class FastconComponent;  // Forward declaration

class FastconLight : public light::LightOutput, public Component {
 public:
  FastconLight() = default;

  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::HARDWARE; }

  // LightOutput interface
  light::LightTraits get_traits() override;
  void write_state(light::LightState *state) override;

  // Configuration
  void set_fastcon_parent(FastconComponent *parent) { this->parent_ = parent; }
  void set_device_id(const std::vector<uint8_t> &did);
  void set_device_type(const std::vector<uint8_t> &type);
  void set_device_key(const std::vector<uint8_t> &key);
  void set_mesh_address(uint8_t addr) { this->mesh_address_ = addr; }

  // Device info
  const FastconDeviceInfo &get_device_info() const { return this->device_info_; }
  std::string get_unique_id() const { return this->device_info_.get_unique_id(); }

  // Binding
  void bind();

 protected:
  void send_command_(const std::vector<uint8_t> &data);
  
  FastconComponent *parent_{nullptr};
  FastconDeviceInfo device_info_{};
  uint8_t mesh_address_{0};
  
  // Last known state
  bool last_state_{false};
  float last_brightness_{0.0f};
  float last_red_{0.0f};
  float last_green_{0.0f};
  float last_blue_{0.0f};
  float last_white_{0.0f};
};

}  // namespace fastcon
}  // namespace esphome
