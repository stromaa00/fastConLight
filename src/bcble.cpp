#include "bcble.h"
#include <WiFi.h>
#include <esp32-hal-log.h>
#include <bletools.h>


const String bc_mqtt_topic = "bcble";
BCBle *BCBle::bcBleInstance = nullptr;

BCBle &BCBle::getInstance()
{
    if (nullptr == bcBleInstance)
        bcBleInstance = new BCBle;
    return *bcBleInstance;
}

void bcble_Callback(const char topic[], byte *payload, unsigned int length)

// void bcble_Callback2(const char topic[], byte *payload, unsigned int length)
{
    String payloadString = String(payload, length);
    String topicString = String(topic);
    Serial.println("bcBle: " + String(topic) + " " + payloadString);

    if (topicString == bc_mqtt_topic)
    {
        if (payloadString == "scan")
        {
            BCBle::getInstance().sendstartscan();
            Serial.println("Send Scan");
        }

        if (payloadString == "PerLvl")
        {
            BCBle::getInstance().sendstartscan();
            Serial.println("Send Scan");
        }

        if (payloadString == "list") // request for list
        {
            Serial.println("Send List");
            BCBle::getInstance().sendList_toMqtt();
        }

        if (payloadString == "clear") // request for list
        {
            Serial.println("Send List");
            BCBle::getInstance().sendList_toMqtt();
        }

        if (payloadString == "bind")
        {
            Serial.println("Bind");
            BCBle::getInstance().enumerate();
            BCBle::getInstance().bindAll();
        }

        if (payloadString == "rebind")
        {
            Serial.println("Bind");
            BCBle::getInstance().enumerate();
            BCBle::getInstance().bindAll();
        }
    }
    else
    {
   

        if (topicString == bc_mqtt_topic + "/list")
        {
           /* Serial.println("List sent");
            if (doc["Clear"] == "True")
            {
                Serial.println("Clear list");
                BCBle::getInstance().trackedDevices.clear();
            }

            if (doc["Rebind"] == "True")
            {
                Serial.println("Rebind");
                BCBle::getInstance().bindAll(true);
            }

            if (doc["OverwriteAddr"] == "True")
            {
                Serial.println("OverwriteAddr");
            }

            std::vector<HADevice> sendDevices;
            JsonArray array = doc["devices"];

            for (JsonVariant dev : array)
            {
                Serial.println("Dev added " + dev.as<String>());
              //  HADevice device = HADevice(dev);
                // device.fromJson(array[i]);
                //Serial.println("Device added " + device.toString());
                //sendDevices.push_back(device);
                //BCBle::getInstance().trackedDevices.push_back(device);
            }
                */
        }
        else
        {
            int pos = topicString.indexOf("@");
            if (pos != -1)
            {
                String deviceString = topicString.substring(pos + 1, topicString.indexOf("@", pos + 1));
                //HADevice device(deviceString);

                //if (BCBle::getInstance().isNewDevice(device))
                {
              //      BCBle::getInstance().trackedDevices.push_back(device);
                //    BCBle::getInstance().display->println(device.toBindString());
                  //  BCBle::getInstance().display->display();
                }             
            }
        }
    }
}

/**** sendstartscan *********************************/
bool BCBle::sendstartscan(void)
{
    Serial.println("BC Sendstartscan");
    std::vector<uint8_t> scancmd = command_start_scan();
    sendAdvertise(scancmd);
    return true;
}

/**** isNewDevice *******************************************************************/
HALight BCBle::getTrackedDevice(String name)
{
    for (int i = 0; i < trackedDevices.size(); i++)
    {
        if (strcmp(trackedDevices[i].getName(),name.c_str()) == 0)
        {
           return trackedDevices[i];
           break;
        }
    }
    return HALight("xx");
}

/**** isNewDevice *******************************************************************/
bool BCBle::isNewDevice(HALight device)
{
    Serial.println("isNewDevice");
    for (int i = 0; i < trackedDevices.size(); i++)
    {
        if (strcmp(trackedDevices[i].uniqueId(), device.uniqueId()) == 0)
        {
            return false;
            break;
        }
    }
    Serial.println("isNewDevice true");
    return true;
}


int BCBle::bindAll(boolean rebind)
{
 /*   for (int i = 0; i < trackedDevices.size(); i++)
    {
        if (rebind || trackedDevices[i].status == 1)
        {
            BLELight(trackedDevices[i]).bind();
            String topic = bc_blelight_discover_template;
            topic.replace("{1}", byte_2_str(trackedDevices[i].name, 2));
            mqtt_bcble.publish(topic.c_str(), getBLELightDiscoverString(trackedDevices[i]).c_str());
        }
    }*/
    return 1;
}

int BCBle::enumerate()
{
     /*  
    Serial.print("enumerate:");
    for (int i = 0; i < trackedDevices.size(); i++)
    {
        if (trackedDevices[i].status == 0)
        {
            Serial.println(";" + String(i + 1));
            trackedDevices[i].addr = i + 1;
            trackedDevices[i].status = 1;
        }
        
    }
*/
    return 1;
}
// Send a list of devices to mqtt
void BCBle::sendList_toMqtt()
{
  
}

