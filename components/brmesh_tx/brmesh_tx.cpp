#include "brmesh_tx.h"

#ifdef USE_ESP32

#include <cstring>

#include "esphome/components/esp32_ble/ble.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

namespace esphome {
namespace brmesh_tx {

static const char *const TAG = "brmesh_tx";

static constexpr size_t PAYLOAD_LEN = 24;
// Flags (LE general discoverable), then manufacturer data with company 0xFFF0,
// exactly like the ESP32 firmware and the Home Assistant integration send it.
static const uint8_t PREFIX[] = {0x02, 0x01, 0x02, 0x1B, 0xFF, 0xF0, 0xFF};

void BrmeshTx::setup() {
  uint16_t interval = this->interval_ms_ * 1000 / 625;  // 0.625 ms units
  this->params_.adv_int_min = interval;
  this->params_.adv_int_max = interval;
  this->params_.adv_type = ADV_TYPE_NONCONN_IND;
  this->params_.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
  this->params_.channel_map = ADV_CHNL_ALL;
  this->params_.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
}

void BrmeshTx::dump_config() {
  ESP_LOGCONFIG(TAG, "BRMesh transmitter:");
  ESP_LOGCONFIG(TAG, "  Interval: %u ms", (unsigned) this->interval_ms_);
}

void BrmeshTx::send(const std::string &payload_hex, int32_t duration_ms) {
  if (esp32_ble::global_ble == nullptr || !esp32_ble::global_ble->is_active()) {
    ESP_LOGW(TAG, "Bluetooth is not active yet, dropping packet");
    return;
  }
  uint8_t adv[sizeof(PREFIX) + PAYLOAD_LEN];
  memcpy(adv, PREFIX, sizeof(PREFIX));
  if (payload_hex.size() != PAYLOAD_LEN * 2 ||
      !parse_hex(payload_hex, adv + sizeof(PREFIX), PAYLOAD_LEN)) {
    ESP_LOGE(TAG, "Payload must be %u bytes as hex, got '%s'", (unsigned) PAYLOAD_LEN,
             payload_hex.c_str());
    return;
  }
  if (duration_ms < 100)
    duration_ms = 100;

  // A newer packet replaces the one being broadcast
  this->cancel_timeout("start");
  this->cancel_timeout("stop");
  esp_ble_gap_stop_advertising();

  esp_err_t err = esp_ble_gap_config_adv_data_raw(adv, sizeof(adv));
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Setting advertising data failed: %s", esp_err_to_name(err));
    return;
  }
  // Give the stack a moment to apply the data before starting
  this->set_timeout("start", 20, [this]() {
    esp_err_t err = esp_ble_gap_start_advertising(&this->params_);
    if (err != ESP_OK)
      ESP_LOGE(TAG, "Starting advertising failed: %s", esp_err_to_name(err));
  });
  this->set_timeout("stop", 20 + duration_ms, []() { esp_ble_gap_stop_advertising(); });
  ESP_LOGD(TAG, "Broadcasting %s for %d ms", payload_hex.c_str(), (int) duration_ms);
}

}  // namespace brmesh_tx
}  // namespace esphome

#endif  // USE_ESP32
