#pragma once

#include "esphome/core/component.h"
#include "esphome/core/log.h"
#include "esphome/core/automation.h"
#include <vector>
#include <BLEScan.h>
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include "fastcon_light.h"
#include "fastcon_protocol.h"

namespace esphome {
namespace fastcon {

static const char *const TAG = "fastcon";

class FastconLight;  // Forward declaration

class FastconComponent : public Component {
 public:
  FastconComponent() = default;

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_BLUETOOTH; }

  // Configuration setters
  void set_phone_key(const std::vector<uint8_t> &key) { this->phone_key_ = key; }
  void set_auto_discover(bool auto_discover) { this->auto_discover_ = auto_discover; }

  // Light registration
  void register_light(FastconLight *light) { this->lights_.push_back(light); }

  // Actions
  void start_scan();
  void bind_all();

  // Get phone key for encryption
  const std::vector<uint8_t> &get_phone_key() const { return this->phone_key_; }

  // Send BLE command
  void send_ble_command(const std::vector<uint8_t> &command);

  // Find light by device ID
  FastconLight *find_light_by_did(const std::string &did);

 protected:
  void setup_ble_scan_();
  void handle_ble_advertisement_(esp_ble_gap_ext_adv_report_t report);
  void create_light_from_discovery_(const FastconDeviceInfo &device_info);

  std::vector<uint8_t> phone_key_{0xA1, 0xA2, 0xA3, 0xA4};  // Default phone key
  bool auto_discover_{true};
  std::vector<FastconLight *> lights_;
  
  BLEScan *ble_scan_{nullptr};
  BLEMultiAdvertising *ble_adv_{nullptr};
  
  uint32_t last_scan_time_{0};
  bool ble_initialized_{false};
};

// Automation actions
template<typename... Ts> class ScanAction : public Action<Ts...> {
 public:
  explicit ScanAction(FastconComponent *parent) : parent_(parent) {}

  void play(Ts... x) override { this->parent_->start_scan(); }

 protected:
  FastconComponent *parent_;
};

template<typename... Ts> class BindAllAction : public Action<Ts...> {
 public:
  explicit BindAllAction(FastconComponent *parent) : parent_(parent) {}

  void play(Ts... x) override { this->parent_->bind_all(); }

 protected:
  FastconComponent *parent_;
};

}  // namespace fastcon
}  // namespace esphome
