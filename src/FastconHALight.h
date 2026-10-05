#ifndef SDEVICELIGHT_H
#define SDEVICELIGHT_H

#include <vector>
#include <stdint.h>
#include <Arduino.h>
#include <tools.h>
#include <ArduinoHA.h>
#include "FastconDevice.h"


class FastconHALight : public HALight, public FastconDevice
{
    int status = 0;
    bool nameAllocated = false;

public:
    FastconHALight(const char *uniqueId, const uint8_t features = DefaultFeatures) : HALight(uniqueId, features){};
    FastconHALight(String uniqueId, const uint8_t features = DefaultFeatures) : HALight(allocateAndCopy(&uniqueId), features){};
    FastconHALight(String uniqueId, FastconDevice& devInfo, const uint8_t features = DefaultFeatures) : HALight(allocateAndCopy(&uniqueId), features) { this->copyFromFastconDevice(devInfo); };

    int bind(boolean rebind);

    void setName(String name);
    void parseDeviceInfo();
    inline void rebind() { onMqttConnected(); };

    void turn_off();
    void turn_on(char brightness);
    void set_brightness(char brightness);
    void set_white(char whiteness);
    void set_rgb(char r, char g, char b, char brightness, bool abs);

    ~FastconHALight()
    {
        if (nameAllocated)
        {
            free(name);
        }

        delete uniqueId();
    }


};

#endif