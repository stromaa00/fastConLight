#include <WiFi.h>
#include <ArduinoHA.h>

#include <String>
#include <cstdio>
#include <BLEScan.h>
#include "fastcon.h"
#include "BLEDevice.h"
#include "BCBle.h"
#include "BLEAdvertisedDevice.h"
#include "tools.h"
#include "bletools.h"
#include <HAMqttExt.h>
#include <HASelectExt.h>
#include <FastconHALight.h>
#include "commands.h" // Include the new header

TaskHandle_t Task1;
TaskHandle_t Task2;
void loop(void *pvParameters);

//////////////////////////////////////////////////////
// CONFIGURATION
//////////////////////////////////////////////////////
// MQTT broker and WiFi settings live in credentials.h (not in git).
// Copy credentials.h.example to credentials.h and fill in your values.
#include "credentials.h"

byte mac[] = {0x24, 0x39, 0x28, 0x32, 0xb7, 0xb0}; // find in serial console upon reset, e.g. "start ESP32 DEVICEID - AABBCCDDEEFF"  (<-that's the MAC)
const std::vector<uint8_t> DEFAULT_PHONE_KEY = {0xA1, 0xA2, 0xA3, 0xA4};

// BCBle bcBle;

uint8_t DEF_PHONE_KEY[] = {0xA1, 0xA2, 0xA3, 0xA4};

int scanTime = 5; // In seconds

BLEScan *pBLEScan;

// no need to modify the next three lines
WiFiClient client;
HADevice haDevice(mac, sizeof(mac));
HAMqttExt mqtt(client, haDevice);
//

// BLEAdvertising *pAdvertising;   // BLE Advertisement type

HAButton scanBtn("scanBtn");
HAButton bindBtn("bindBtn");



// Adds a Fastcon device and its associated select to the system.
void addFastconDevice(FastconDevice* fcDevice) {
    FastconHALight *haLight = new FastconHALight(fcDevice->getUniqueFullname(), *fcDevice, HALight::BrightnessFeature | HALight::RGBFeature | HALight::WhiteFeature );

    haLight->setName(byte_2_str(fcDevice->name, 2));
    haLight->onStateCommand(onStateCommand);
    haLight->onBrightnessCommand(onBrightnessCommand);
    haLight->onColorTemperatureCommand(onColorTemperatureCommand);
    haLight->onRGBColorCommand(onRGBColorCommand);
    haLight->onWhiteCommand(onWhiteCommand);
    
    
    //String addName = "addr_" + fcDevice->Name();
    //mqtt.publish(addName.c_str(), "0", true);

    haLight->rebind();

    String selNAme = "sel_" + fcDevice->Name();
    
    HASelectExt *selExt = new HASelectExt(selNAme);
    selExt->setOptions({"0;1;2;3;4;5;6"});
    selExt->setName(selNAme.c_str());
    Serial.println("Adding select: " + String( selExt->uniqueId()));
    
    selExt->onCommand([]( int8_t idx, HASelect *sender)
                   {
                      Serial.println("Select changed :" + String(sender->getName()) + " : " + String(idx)); 
                      sender->setState(idx, true);
                       HABaseDeviceType* dev = mqtt.getDeviceByName(sender->getName()+4);
                      if (dev!= NULL)
                      {
                        Serial.println("Found device: " + String(dev->uniqueId()));
                        FastconHALight* fcLight = (FastconHALight*)dev;
                        fcLight->addr= idx;
                        fcLight->bind(true);
                      }
                      else
                      {
                        Serial.println("Device not found: " + String(sender->uniqueId()));
                      }
                  });

    selExt->rebind();
    
    Serial.println("Added HALight: " + String(haLight->uniqueId()));
    Serial.println("Number of devices " + String(mqtt.getDevicesTypesNb()));
}

// Callback for handling BLE extended advertising results.
class MyExtAdvertisedDeviceCallbacks : public BLEExtAdvertisingCallbacks
{

  void onResult(esp_ble_gap_ext_adv_report_t reportedDevice)
  {
    // Serial.println("Advertised Device found: ");
    if (reportedDevice.addr[0] == 0x11 && reportedDevice.addr[1] == 0x22)
    {
      String payloadStr = byte_2_str(reportedDevice.adv_data, reportedDevice.adv_data_len);

      // 13FFF0F F4E697A06EC0BF10A 52F2 A1A8 5E367BC4

      if (payloadStr.substring(6).startsWith("13FFF0FF"))
      {
        FastconDevice fcDevice = parse_ble_broadcast(reportedDevice.adv_data + 7, 23 - 7, DEF_PHONE_KEY);

        if (mqtt.isUniqueDevice(fcDevice.getUniqueFullname().c_str()))
        {
          Serial.println("Adding light from Scan: " + fcDevice.getUniqueFullname());
          addFastconDevice(&fcDevice);
        }
      }
    }
  }
};

// Handles incoming MQTT messages and processes them.
void handleMqttMessage(const char *topic, const uint8_t *payload, const uint16_t length)
{
  Serial.print("Received message on topic: ");
  Serial.println(topic);
  Serial.print("Payload: ");
  String payloadStr = String((char *)payload, length);
  Serial.println(payloadStr);

  std::vector<String> topicParts = splitString(topic, '/');
  if (topicParts.size() >= 3)
  {
    if (mqtt.isUniqueDevice(topicParts[2].c_str()))
    {
      Serial.println("Unknown device : " + topicParts[2]);
      std::vector<String> deviceParts = splitString(topicParts[2], '-');
      if (deviceParts.size() == 4)
      {
        Serial.print("Added halight from mqtt: ");
        FastconDevice fcDevice(topicParts[2]);

        addFastconDevice(&fcDevice);
      }
    }
  }
}

// Callback function triggered at the end of a BLE scan.
void EndofScan()
{
  Serial.println("EndofScan");
  pBLEScan->start(5, EndofScan);
}

// Task function for continuously scanning BLE devices.
void scan(void *pvParameters)
{
  while (1)
  {
    Serial.println("scan task started");
    pBLEScan->start(1);
  }
}

// Sets up the initial configuration for WiFi, MQTT, BLE, and other components.
void setup()
{
  // BLE STUFF
  Serial.begin(115200);
  Serial.printf("start ESP32 DEVICEID - %llX\n", ESP.getEfuseMac());
  pinMode(PRG_PIN, INPUT);

  Serial.printf("adverstiding started\n");
  // HOME ASSISTANT MQTT STUFF
  //  you don't need to verify return status
  WiFi.macAddress(mac);
  WiFi.mode(WIFI_STA);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500); // waiting for the connection
    Serial.print(".");
    Serial.println(WiFi.status());
  }

  Serial.printf("Connected to %s\n", WIFI_SSID);

  haDevice.setName("FastconESP");
  haDevice.setManufacturer("Dodosoft");
  haDevice.setModel("BRMesh");
  haDevice.setSoftwareVersion("1.0.0");

  scanBtn.setName("ScanBtn");
  scanBtn.setObjectId("scanBtn");
  scanBtn.setIcon("mdi:magnify-scan");
  scanBtn.onCommand([](HAButton *sender)
                    {
        Serial.println("Scan Button pressed");
        std::vector<uint8_t> scancmd = command_start_scan();
        sendAdvertise(scancmd); });

  bindBtn.setName("bindBtn");
  bindBtn.setObjectId("bindBtn");
  bindBtn.setIcon("mdi:magnify-scan");
  bindBtn.onCommand([](HAButton *sender) { // mqtt.subscribe("aha/14392832a7b0/#");
    mqtt.BindAll();
    Serial.println("Bind Button pressed");
  });

  Serial.println("Starting MQTT");
  mqtt.begin(MQTT_BROKER_ADDR, 1883, MQTT_BROKER_USER, MQTT_BROKER_PASS);

  mqtt.onConnected([]()
                   { mqtt.subscribe("aha/#"); });

  mqtt.onMessage(handleMqttMessage);

  if (mqtt.isConnected())
  {
    Serial.println("MQTT connected");
  }
  else
  {
    Serial.println("MQTT not connected");
  }

  BLEDevice::init("bcBle");
  pBLEScan = BLEDevice::getScan(); // create new scan
  pBLEScan->setExtendedScanCallback(new MyExtAdvertisedDeviceCallbacks());

  esp_ble_ext_scan_params_t ext_scan_params = {
      .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
      .filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
      .scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE,
      .cfg_mask = ESP_BLE_GAP_EXT_SCAN_CFG_UNCODE_MASK | ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK,

      .uncoded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
      .coded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
  };
  pBLEScan->setExtScanParams(&ext_scan_params);
  pBLEScan->startExtScan(0, 0);

  // pBLEScan->start(5, EndofScan);

  Serial.println("Setup done");
}

static uint32_t buttonpress_ms = millis();
static uint32_t lastreconnect_ms = millis();
bool last_prgButtonState = false;
const int keep_display_lines = 1; // default 8

// Main loop function that handles button presses and MQTT looping.
void loop()
{
  mqtt.loop();
  static uint32_t prev_ms = millis();

  // check if the pushbutton is pressed. If it is, the buttonState is HIGH:

  if (digitalRead(PRG_PIN) == HIGH) // release
  {

    if (last_prgButtonState == true)
    {
      Serial.println("button press " + String(millis()) + " : " + String(buttonpress_ms));
      if ((millis() - buttonpress_ms) < 1000)
      {
        Serial.println("Scan");
        sendAdvertise(command_start_scan());
        last_prgButtonState = false;
      }
      else
      {
        Serial.println("Bind");
        mqtt.BindAll();

        last_prgButtonState = false;
      }
      buttonpress_ms = millis();
    }
  }
  else
  {
    if (last_prgButtonState == false)
    {
      buttonpress_ms = millis();
      last_prgButtonState = true;
    }
  };
  delay(100);
}
