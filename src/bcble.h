#ifndef BC_BLE
#define BC_BLE


#include <vector>
#include "tools.h"
#include "ArduinoHA.h"

std::vector<uint8_t> command_start_scan();

class BCBle
{
public:
    //  bool  sendCommand(u_int8_t i, byte data[12], byte key[4], u_int32_t retry_count, u_int32_t send_time, bool z, bool use_default_adapter, bool use_22_data, u_int8_t i2);


    static BCBle *bcBleInstance;
    BCBle() = default;  // no public constructor
    ~BCBle() = default; // no public destructor
    

public:
    BCBle(const BCBle &) = delete; // rule of three
    BCBle &operator=(const BCBle &) = delete;
    static void destruct()
    {
        delete bcBleInstance;
        bcBleInstance = nullptr;
    }

    std::vector<HALight> trackedDevices;
    int mSendCnt = 0;
    int sSendSeq = 0;

    bool initMqtt(const char *mqtt_server, const char *mqtt_user, const char *mqtt_pass);
    void mqttLoop();

    bool isNewDevice(HALight device);
    String getBLELightDiscoverString(HALight device);
    HALight getLastDevice() { return trackedDevices.back(); }
    HALight getTrackedDevice(String name);
    // void bcble_Callback(const char topic[], byte *payload, unsigned int length);
    static BCBle &getInstance();
    bool sendstartscan(void);
    int enumerate(void);
    void sendList_toMqtt(void);
    int bindAll(void) { return bindAll(false); }
    int bindAll(boolean rebind);
   

    /* boolean setPhoneKey(byte[] bArr)
     {
         memcpy(phone_key, bArr, 4);
     }*/

private:
};

#endif