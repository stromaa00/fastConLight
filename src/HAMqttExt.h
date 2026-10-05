#ifndef AHA_HAMQTTEXT_H
#define AHA_HAMQTTEXT_H

#include <ArduinoHA.h>
#include "FastconHALight.h"


class HAMqttExt : public HAMqtt
{

public:
  explicit HAMqttExt(
      Client &netClient,
      HADevice &device,
      const uint8_t maxDevicesTypesNb = HAMQTT_DEFAULT_DEVICES_LIMIT) : HAMqtt(netClient, device, maxDevicesTypesNb) {}


  /**
    * Binds all devices to the MQTT broker.
    */
    void BindAll()
    {
     for (int i = 0; i < getDevicesTypesNb()  /* _devicesTypesNb*/ ; i++)
     {
      ((FastconHALight*) getDevicesTypes()[i] )->bind(true);
     }
    }


  /**
   * Checks if a device with the given unique ID already exists.
   * 
   * @param uniqueId The unique ID of the device to check.
   * @return True if the device is unique, false otherwise.
   */
  bool isUniqueDevice(const char *uniqueId)
  {
    for (int i = 0; i < getDevicesTypesNb(); i++)
    {
      log_v("Comparing existing: " + String(getDevicesTypes()[i]->uniqueId()) + " with " + String(uniqueId));
      if (strcmp(getDevicesTypes()[i]->uniqueId(), uniqueId) == 0)
        return false;
    }
    return true;
  }

  HABaseDeviceType* getDeviceByName(const char *name)
  {
    Serial.println("getDeviceByName: " + String(name));
    for (int i = 0; i < getDevicesTypesNb(); i++)
    {
      log_v("Comparing existing: " + String(getDevicesTypes()[i]->uniqueId()) + " with " + String(uniqueId));
      if (strcmp(getDevicesTypes()[i]->getName(), name) == 0)
        return getDevicesTypes()[i];
    }
    return NULL;
  }

};

#endif
