#ifndef SDEVICEINFO_H
#define SDEVICEINFO_H

#include <vector>
#include <stdint.h>
#include <Arduino.h>
#include <tools.h>


enum EBLEDeviceTypes
{
    Curtain = 43499,
    Fan = 43531,
    Gateway = 43500,
    Gateway_AC = 43756,
    Gateway_IHG = 10058,
    Light_BURDEN_CW = 43754,
    Light_BURDEN_W = 43759,
    Light_CCT = 43051,
    Light_COMPOSE = 43709,
    Light_PWR = 43049,
    Light_RGB = 43168,
    Light_RGBCW = 43050,
    Light_RGBW = 43169,
    Light_W_CW = 43745,
    Meta_PAD = 43518,
    Meta_PAD_2 = 43974,
    Panel_3 = 43463,
    Panel_3_Wireless = 43462,
    Panel_4 = 43473,
    Panel_4_Wireless = 43472,
    Panel_6 = 43461,
    Panel_6_Wireless = 43459,
    Panel_8 = 43733,
    Panel_8_2 = 43734,
    Relay_1 = 43525,
    Relay_2 = 43474,
    Relay_4 = 43680,
    Sensor_Door = 43505,
    Sensor_IR = 43516,
    Sensor_Radar = 43808,
    Sensor_Water = 43791,
    ThermoStat = 43919,
};

class FastconDevice 
{
    
public:
    FastconDevice() = default;
    FastconDevice(const String deviceString);
    bool sendCommand2(byte bArr[]);
    void copyFromFastconDevice(FastconDevice devInfo);

    u_int8_t cnt = 1; // seems to be hardcoded to 1
    char key[4];
    u_int32_t key_val;
    unsigned char did[6];
    unsigned char name[2];
    unsigned char high[1];
    unsigned char addr = 0;
    char type[2];
    u_int16_t type_val;
    EBLEDeviceTypes deviceType;
    int status = 0;

    String Name() { return byte_2_str(name, 2); }
    String Did() { return byte_2_str(did, 6); }
    String Key() { return byte_2_str(key, 4); }

    String toString()
    {
        return "Key: " + byte_2_str(key, 4) + " Did: " + byte_2_str(did, 6) + " Name: " + byte_2_str(name, 2) + " High: " + byte_2_str(high, 1) + " Type: " + byte_2_str(type,2);
    };

    
    String toBindString()
    {
        return (status == 0 ? "*" : "# ") + byte_2_str(name, 2) + ":" + String(addr);
    };

    const char* toBindStringByte()
    {
        //byte result[11];
        
        return NULL; // byte_2_str(name, 2) + ":" + String(addr).c_str();
    };

     String getUniqueFullname()
    {
        String result("{0}-{1}-{2}-{3}");
        result.replace("{0}", byte_2_str(name, 2));
        result.replace("{1}", byte_2_str(did, 6));
        result.replace("{2}", byte_2_str(type, 2));
        result.replace("{3}", byte_2_str(key, 4));
        return result;
    };

    String getMQTTTCommandTopic()
    {
        String result("\"command_topic\":\"bcble/blelight/@{0}:{1}:{2}@/command\"");
        result.replace("{0}", byte_2_str(name, 2));
        result.replace("{1}", byte_2_str(did, 6));
        result.replace("{2}", String(addr));
        return result;
    };

    bool operator==(FastconDevice dev) { return name[0] == dev.name[0] && name[1] == dev.name[1]; }
    // int genSceneId(int i, int i2, int i3) { return (i << 16) | (i2 << 8) | i3;  }
    boolean isAc() { return deviceType == 43756 || deviceType == 43919; }
    boolean isCurtain() { return deviceType == 43499; }
    boolean isGateway() { return deviceType == 43500 || deviceType == 10058; }
    boolean isLight() { return deviceType == 43709 || deviceType == 43051 || deviceType == 43049 || deviceType == 43168 || deviceType == 43050 || deviceType == 43169 || deviceType == 43745 || deviceType == 43759 || deviceType == 43754; }
    boolean isPanel() { return deviceType == 43473 || deviceType == 43472 || deviceType == 43461 || deviceType == 43733 || deviceType == 43734 || deviceType == 43459 || deviceType == 43518 || deviceType == 43974; }
    boolean isRelayPanel() { return deviceType == 43474 || deviceType == 43525 || deviceType == 43463 || deviceType == 43462 || deviceType == 43680; }
    boolean isSensor() { return deviceType == 43505 || deviceType == 43516 || deviceType == 43791 || deviceType == 43808; }
    boolean isSupperPanel() { return deviceType == 43518 || deviceType == 43974; }
};

static String getDeviceName(int i)
{
    switch (i)
    {
    case 43499:
        return "Curtain";
        break;
    case 43531:
        return "Fan";
        break;
    case 43500:
        return "Gateway";
        break;
    case 43756:
        return "Gateway_AC";
        break;
    case 10058:
        return "Gateway_IHG";
        break;
    case 43754:
        return "Light_BURDEN_CW";
        break;
    case 43759:
        return "Light_BURDEN_W";
        break;
    case 43051:
        return "Light_CCT";
        break;
    case 43709:
        return "Light_COMPOSE";
        break;
    case 43049:
        return "Light_PWR";
        break;
    case 43168:
        return "Light_RGB";
        break;
    case 43050:
        return "Light_RGBCW";
        break;
    case 43169:
        return "Light_RGBW";
        break;
    case 43745:
        return "Light_W_CW";
        break;
    case 43518:
        return "Meta_PAD";
        break;
    case 43974:
        return "Meta_PAD_2";
        break;
    case 43463:
        return "Panel_3";
        break;
    case 43462:
        return "Panel_3_Wireless";
        break;
    case 43473:
        return "Panel_4";
        break;
    case 43472:
        return "Panel_4_Wireless";
        break;
    case 43461:
        return "Panel_6";
        break;
    case 43459:
        return "Panel_6_Wireless";
        break;
    case 43733:
        return "Panel_8";
        break;
    case 43734:
        return "Panel_8_2";
        break;
    case 43525:
        return "Relay_1";
        break;
    case 43474:
        return "Relay_2";
        break;
    case 43680:
        return "Relay_4";
        break;
    case 43505:
        return "Sensor_Door";
        break;
    case 43516:
        return "Sensor_IR";
        break;
    case 43808:
        return "Sensor_Radar";
        break;
    case 43791:
        return "Sensor_Water";
        break;
    case 43919:
        return "ThermoStat";
        break;
    default:
        return "Unknown";
        break;
    }
}

#endif
