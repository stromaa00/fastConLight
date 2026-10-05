#include "FastconDevice.h"

#include "bletools.h"

const std::vector<uint8_t> DEFAULT_PHONE_KEY = {0xA1, 0xA2, 0xA3, 0xA4};


void FastconDevice::copyFromFastconDevice(FastconDevice devInfo)
{
    memccpy(key, devInfo.key, 0, 4);
    memccpy(did, devInfo.did, 0, 6);
    memccpy(name, devInfo.name, 0, 2);
    memccpy(high, devInfo.high, 0, 1);
    addr = devInfo.addr;
    memccpy(type, devInfo.type, 0, 2);
    type_val = strtol(byte_2_str(type, 2).c_str(), nullptr, 16);
    deviceType = (EBLEDeviceTypes)type_val;
}

FastconDevice::FastconDevice(const String deviceString)
{
    std::vector<String> devParts = split(deviceString, "-");
    if (devParts.size() == 4)
    {
        String deviceName = devParts.at(0);
        String deviceDid = devParts.at(1);
        String deviceTypeStr = devParts.at(2);
        String deviceKey = devParts.at(3);
        Serial.println("deviceName: " + deviceName + " deviceDid: " + deviceDid + " deviceKey:" + deviceKey + " deviceType: " + String(deviceTypeStr));

        did[0] = str_2_byte(deviceDid.substring(0, 2));
        did[1] = str_2_byte(deviceDid.substring(2, 4));
        did[2] = str_2_byte(deviceDid.substring(4, 6));
        did[3] = str_2_byte(deviceDid.substring(6, 8));
        did[4] = str_2_byte(deviceDid.substring(8, 10));
        did[5] = str_2_byte(deviceDid.substring(10, 12));
        
        name[0] = str_2_byte(deviceName.substring(0, 2));
        name[1] = str_2_byte(deviceName.substring(2, 4));

        type[0] = str_2_byte(deviceTypeStr.substring(0, 2));
        type[1] = str_2_byte(deviceTypeStr.substring(2, 4));
      
        if (deviceKey.length()==8)
        {
        key[0] = str_2_byte(deviceKey.substring(0, 2));
        key[1] = str_2_byte(deviceKey.substring(2, 4));
        key[2] = str_2_byte(deviceKey.substring(4, 6));
        key[3] = str_2_byte(deviceKey.substring(6, 8));
        }
        Serial.println ("Uniquefillname : " + this->getUniqueFullname());
        type_val = strtol(byte_2_str(type, 2).c_str(), nullptr, 16);
        deviceType = (EBLEDeviceTypes)type_val;
    }
}






 