#pragma once

#ifdef USE_ESP32

#include <string>

#include <esp_gap_ble_api.h>

#include "esphome/core/component.h"

namespace esphome {
namespace brmesh_tx {

// Broadcasts one BRMesh packet at a time for a given duration.
class BrmeshTx : public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_BLUETOOTH; }

  void set_interval(uint32_t interval_ms) { this->interval_ms_ = interval_ms; }

  // payload_hex: the 24 bytes after the 0xFFF0 company ID, as hex (48 chars)
  void send(const std::string &payload_hex, int32_t duration_ms);

 protected:
  uint32_t interval_ms_{100};
  esp_ble_adv_params_t params_{};
};

}  // namespace brmesh_tx
}  // namespace esphome

#endif  // USE_ESP32
