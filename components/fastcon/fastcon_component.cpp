#include "fastcon_component.h"
#include "esphome/core/log.h"

namespace esphome {
namespace fastcon {

static const char *const TAG = "fastcon.component";

// BLE Extended Advertising Callback
class FastconBLECallback : public BLEExtAdvertisingCallbacks {
 public:
  explicit FastconBLECallback(FastconComponent *parent) : parent_(parent) {}

  void onResult(esp_ble_gap_ext_adv_report_t reportedDevice) override {
    this->parent_->handle_ble_advertisement_(reportedDevice);
  }

 private:
  FastconComponent *parent_;
};

void FastconComponent::setup() {
  ESP_LOGCONFIG(TAG, "Setting up Fastcon component...");

  // Initialize BLE
  BLEDevice::init("FastconESP");
  
  this->setup_ble_scan_();
  
  this->ble_initialized_ = true;
  ESP_LOGCONFIG(TAG, "Fastcon component setup complete");
}

void FastconComponent::loop() {
  // BLE scanning is handled by callbacks
  // Check if we need to do any periodic tasks
  
  uint32_t now = millis();
  
  // Periodic scan restart every 60 seconds to ensure continuous operation
  if (now - this->last_scan_time_ > 60000) {
    ESP_LOGD(TAG, "Restarting BLE scan");
    if (this->ble_scan_ != nullptr) {
      this->ble_scan_->startExtScan(0, 0);
    }
    this->last_scan_time_ = now;
  }
}

void FastconComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "Fastcon:");
  ESP_LOGCONFIG(TAG, "  Phone Key: %02X%02X%02X%02X", 
                this->phone_key_[0], this->phone_key_[1], 
                this->phone_key_[2], this->phone_key_[3]);
  ESP_LOGCONFIG(TAG, "  Auto Discover: %s", YESNO(this->auto_discover_));
  ESP_LOGCONFIG(TAG, "  Registered Lights: %d", this->lights_.size());
  
  for (auto *light : this->lights_) {
    ESP_LOGCONFIG(TAG, "    - %s", light->get_unique_id().c_str());
  }
}

void FastconComponent::setup_ble_scan_() {
  ESP_LOGD(TAG, "Setting up BLE scan");
  
  this->ble_scan_ = BLEDevice::getScan();
  this->ble_scan_->setExtendedScanCallback(new FastconBLECallback(this));

  // Configure extended scan parameters
  esp_ble_ext_scan_params_t ext_scan_params = {
      .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
      .filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
      .scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE,
      .cfg_mask = ESP_BLE_GAP_EXT_SCAN_CFG_UNCODE_MASK | ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK,
      .uncoded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
      .coded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
  };

  this->ble_scan_->setExtScanParams(&ext_scan_params);
  this->ble_scan_->startExtScan(0, 0);  // Scan duration 0 = continuous
  
  this->last_scan_time_ = millis();
  
  ESP_LOGD(TAG, "BLE scan started");
}

void FastconComponent::handle_ble_advertisement_(esp_ble_gap_ext_adv_report_t report) {
  // Filter by BRMesh address prefix (0x11:0x22)
  if (report.addr[0] != 0x11 || report.addr[1] != 0x22) {
    return;
  }

  // Check payload header
  if (report.adv_data_len < 23) {
    return;
  }

  // Convert to hex string for checking
  std::string payload_hex = bytes_to_hex_string(report.adv_data + 7, 8);
  
  // Check for Fastcon payload header (13FFF0FF)
  if (payload_hex.substr(0, 8) != "13fff0ff" && payload_hex.substr(0, 8) != "13FFF0FF") {
    return;
  }

  // Parse device info
  FastconDeviceInfo device_info;
  uint8_t phone_key_arr[4] = {this->phone_key_[0], this->phone_key_[1], 
                               this->phone_key_[2], this->phone_key_[3]};
  
  if (parse_ble_broadcast(report.adv_data + 7, report.adv_data_len - 7, 
                          this->phone_key_, device_info)) {
    
    ESP_LOGI(TAG, "Discovered device: %s", device_info.get_unique_id().c_str());
    
    // Check if device already exists
    if (this->find_light_by_did(device_info.get_did_string()) == nullptr) {
      if (this->auto_discover_ && device_info.is_light()) {
        ESP_LOGI(TAG, "Auto-creating light for: %s", device_info.get_unique_id().c_str());
        this->create_light_from_discovery_(device_info);
      }
    }
  }
}

void FastconComponent::create_light_from_discovery_(const FastconDeviceInfo &device_info) {
  // This would require dynamic light creation which is complex in ESPHome
  // For now, log that manual configuration is needed
  ESP_LOGW(TAG, "Auto-discovery found device %s - add to YAML config:", 
           device_info.get_unique_id().c_str());
  ESP_LOGW(TAG, "  - platform: fastcon");
  ESP_LOGW(TAG, "    name: \"%s\"", device_info.get_name_string().c_str());
  ESP_LOGW(TAG, "    device_id: \"%s\"", device_info.get_did_string().c_str());
  ESP_LOGW(TAG, "    device_type: \"%s\"", device_info.get_type_string().c_str());
  ESP_LOGW(TAG, "    device_key: \"%s\"", device_info.get_key_string().c_str());
}

void FastconComponent::start_scan() {
  ESP_LOGI(TAG, "Starting BLE scan");
  
  // Send scan command via BLE advertising
  std::vector<uint8_t> scan_cmd = generate_scan_command();
  this->send_ble_command(scan_cmd);
}

void FastconComponent::bind_all() {
  ESP_LOGI(TAG, "Binding all devices");
  
  for (auto *light : this->lights_) {
    light->bind();
    delay(100);  // Small delay between bindings
  }
}

void FastconComponent::send_ble_command(const std::vector<uint8_t> &command) {
  // Prepend BLE header
  std::vector<uint8_t> full_cmd;
  full_cmd.insert(full_cmd.end(), BLE_PREDATA.begin(), BLE_PREDATA.end());
  full_cmd.insert(full_cmd.end(), command.begin(), command.end());

  // Set up BLE advertising if not already done
  if (this->ble_adv_ == nullptr) {
    this->ble_adv_ = new BLEMultiAdvertising(4);
  }

  // Configure advertising parameters
  esp_ble_gap_ext_adv_params_t adv_params = {
      .type = ESP_BLE_GAP_PHY_1M_PREF_MASK | ESP_BLE_GAP_PHY_2M_PREF_MASK,
      .interval_min = 0x45,
      .interval_max = 0x45,
      .channel_map = ADV_CHNL_ALL,
      .own_addr_type = BLE_ADDR_TYPE_RANDOM,
      .filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
      .primary_phy = ESP_BLE_GAP_PHY_1M,
      .max_skip = 0,
      .secondary_phy = ESP_BLE_GAP_PHY_1M,
      .sid = 2,
      .scan_req_notif = false,
  };

  uint8_t addr_legacy[6] = {0xc0, 0xde, 0x52, 0x00, 0x00, 0x03};

  this->ble_adv_->setAdvertisingParams(0, &adv_params);
  this->ble_adv_->setAdvertisingData(0, full_cmd.size(), full_cmd.data());
  this->ble_adv_->setInstanceAddress(0, addr_legacy);
  this->ble_adv_->setDuration(0, 50, 10);
  this->ble_adv_->start(1, 0);

  ESP_LOGD(TAG, "BLE command sent, size: %d bytes", full_cmd.size());
  
  // Stop after duration
  delay(BLE_CMD_ADVERTISE_LENGTH);
  this->ble_adv_->stop(1, 0);
}

FastconLight *FastconComponent::find_light_by_did(const std::string &did) {
  for (auto *light : this->lights_) {
    if (light->get_device_info().get_did_string() == did) {
      return light;
    }
  }
  return nullptr;
}

}  // namespace fastcon
}  // namespace esphome
