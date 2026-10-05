#include "blelight.h"
#include "bletools.h"
#include "FastconDevice.h"


const std::vector<uint8_t> DEFAULT_PHONE_KEY = {0xA1, 0xA2, 0xA3, 0xA4};

enum class LightCommandType
{
    Colored,
    WarmWhite,
    Brightness,
    OnOff,
    Some5,
    Some6,
    Some7,
    Some8,
    Some9
};

enum class LightState
{
    Off,
    WarmWhite,
    RGB
};

struct LightCommand
{
    LightCommandType type;
    union
    {
        struct
        {
            bool on;
            uint8_t brightness;
            uint8_t r;
            uint8_t g;
            uint8_t b;
            bool abs;
        } colored;

        struct
        {
            bool on;
            uint8_t brightness;
            uint8_t i5;
            uint8_t i6;
        } warmWhite;

        struct
        {
            bool on;
            uint8_t val;
        } brightness;

        struct
        {
            bool on ;
            uint8_t brightness;
        } onOff;
        struct
        {
            bool someZ;
        } some5;
        struct
        {
            bool someZ;
            uint8_t someI;
        } some6;
        struct
        {
            bool on;
            uint8_t brightness;
            uint8_t r;
            uint8_t g;
            uint8_t b;
            bool absolute;
            uint8_t i5;
            uint8_t i6;
            bool z;
            uint8_t i7;
        } some7;
        struct
        {
            bool on;
            uint8_t brightness;
            bool z2;
            uint8_t i7;
        } some8;
        struct
        {
            uint8_t r;
            uint8_t g;
            uint8_t b;
            bool absolute;
        } some9;
    };
};


static std::vector<uint8_t> lightCommandToBytes(const LightCommand &command)
{
    switch (command.type)
    {
    case LightCommandType::Colored:
    {
        std::vector<uint8_t> arr(6, 0);
        const float colorNormalization = command.colored.abs ? 1.0f : 255.0f / (command.colored.r + command.colored.g + command.colored.b);
        arr[0] = (command.colored.on ? 128 : 0) + (command.colored.brightness & 127);
        arr[1] = static_cast<uint8_t>(command.colored.b * colorNormalization);
        arr[2] = static_cast<uint8_t>(command.colored.r * colorNormalization);
        arr[3] = static_cast<uint8_t>(command.colored.g * colorNormalization);
        arr[4] = 0;
        arr[5] = 0;
        return arr;
    }
    case LightCommandType::WarmWhite:
    {
        std::vector<uint8_t> arr(6, 0);
        arr[0] = (command.warmWhite.on ? 128 : 0) + (command.warmWhite.brightness & 127);
        arr[1] = 0;
        arr[2] = 0;
        arr[3] = 0;
        arr[4] = command.warmWhite.i5;
        arr[5] = command.warmWhite.i6;
        return arr;
    }
    case LightCommandType::Brightness:
    {
        std::vector<uint8_t> arr(1, 0);
        arr[0] = command.brightness.on ? command.brightness.val & 127 : 0;
        return arr;
    }

    case LightCommandType::OnOff:
    {
        std::vector<uint8_t> arr(1, 0);
        arr[0] = command.onOff.on ? 128 : 0 + (command.onOff.brightness & 127);
        return arr;
    }
    case LightCommandType::Some5:
    {
        std::vector<uint8_t> arr(7, 0);
        arr[0] = 0;
        arr[1] = 0;
        arr[2] = 0;
        arr[3] = 0;
        arr[4] = UINT8_MAX;
        arr[5] = UINT8_MAX;
        arr[6] = command.some5.someZ ? 128 : 0;
        return arr;
    }
    case LightCommandType::Some6:
    {
        std::vector<uint8_t> arr(7, 0);
        arr[0] = 0;
        arr[1] = 0;
        arr[2] = 0;
        arr[3] = 0;
        arr[4] = UINT8_MAX;
        arr[5] = UINT8_MAX;
        arr[6] = command.some6.someZ ? 128 : 0 + (command.some6.someI & 127);
        return arr;
    }
    case LightCommandType::Some7:
    {
        const float colorNormalization = command.some7.absolute ? 1.0f : 255.0f / (command.some7.r + command.some7.g + command.some7.b);
        std::vector<uint8_t> arr(7, 0);
        arr[0] = (command.some7.on ? 128 : 0) + (command.some7.brightness & 127);
        arr[1] = static_cast<uint8_t>(command.some7.r * colorNormalization);
        arr[2] = static_cast<uint8_t>(command.some7.g * colorNormalization);
        arr[3] = static_cast<uint8_t>(command.some7.b * colorNormalization);
        arr[4] = command.some7.i5;
        arr[5] = command.some7.i6;
        arr[6] = command.some7.z ? 128 : 0 + (command.some7.i7 & 127);
        return arr;
    }
    case LightCommandType::Some8:
    {
        std::vector<uint8_t> arr(7, 0);
        arr[0] = (command.some8.on ? 128 : 0) + (command.some8.brightness & 127);
        arr[1] = UINT8_MAX;
        arr[2] = UINT8_MAX;
        arr[3] = UINT8_MAX;
        arr[4] = UINT8_MAX;
        arr[5] = UINT8_MAX;
        arr[6] = command.some8.z2 ? 128 : 0 + (command.some8.i7 & 127);
        return arr;
    }
    case LightCommandType::Some9:
    {
        const float colorNormalization = command.some9.absolute ? 1.0f : 255.0f / (command.some9.r + command.some9.g + command.some9.b);
        std::vector<uint8_t> arr(7, 0);
        arr[0] = UINT8_MAX;
        arr[1] = static_cast<uint8_t>(command.some9.r * colorNormalization);
        arr[2] = static_cast<uint8_t>(command.some9.g * colorNormalization);
        arr[3] = static_cast<uint8_t>(command.some9.b * colorNormalization);
        arr[4] = UINT8_MAX;
        arr[5] = UINT8_MAX;
        // arr[6] = UINT8_MIN; //TPDP
        return arr;
    }
    }
    return {};
}


static std::vector<uint8_t> get_OffCommand()
{
    LightCommand command;
    command.type = LightCommandType::OnOff;
    command.onOff.on = false;
    command.onOff.brightness = 0;
    return lightCommandToBytes(command);
}

static std::vector<uint8_t> get_OnCommand(char brightness ) {
    LightCommand command;
    command.type = LightCommandType::OnOff;
    command.onOff.on = true;
    command.onOff.brightness = brightness;
    return lightCommandToBytes(command);
}

static std::vector<uint8_t> get_brightnessCommand(char brightness ) {
    LightCommand command;
    command.type = LightCommandType::Brightness;
    command.brightness.on = true;
    command.brightness.val = brightness/2;
    return lightCommandToBytes(command);
}   

static std::vector<uint8_t> get_whiteCommand(char whiteness ) {
    LightCommand command;
    command.type = LightCommandType::WarmWhite;
    command.warmWhite.on = true;
    command.warmWhite.brightness = whiteness/2;
    command.warmWhite.i5 = 127;
    command.warmWhite.i6 = 127;
    return lightCommandToBytes(command);
}

/**
 * Returns a vector of 12 bytes representing a LightCommand for setting the color and brightness of an RGB light.
 * 
 * @param r The red value of the color (0-255).
 * @param g The green value of the color (0-255).
 * @param b The blue value of the color (0-255).
 * @param brightness The brightness of the light (0-255).
 * @param abs Whether the color values should be interpreted as absolute (true) or relative (false).
 * @return A vector of 12 bytes representing the LightCommand.
 * 
 *   // brg:128 r:0 g:255 b:0  =  800000800000
 *   // brg:128 r:255 g:0 b:0  =  8000ff000000
 *   // brg:128 r:0 g:0 b:255  =  80ff00000000
 */
static std::vector<uint8_t> get_rgbCommand(char r, char g, char b, char brightness, bool abs) {
  

    LightCommand command;
    command.type = LightCommandType::Colored;
    command.colored.abs = abs;
    command.colored.r = r;
    command.colored.g = g;
    command.colored.b = b;
    command.colored.brightness = brightness;
    return lightCommandToBytes(command);
}

bool sendLightCommand(std::vector<uint8_t> bArr, FastconDevice* dev)
{
    Serial.println("BLELight::sendLightCommand :" + byte_2_str(dev->name, 4) + " addr: " + dev->addr + " cmd : " + bytevector_2_str(bArr));

    // package_device_control
    std::vector<uint8_t> data = {(unsigned char)(2 | (((0xfffffff & (bArr.size() + 1)) << 4))), dev->addr};
    for (int i = 0; i < bArr.size(); i++)
    {
        data.push_back(bArr[i]);
    }

    while (data.size() < 12)
        data.push_back(0);

    /*    uint64_t len_add_1 = ((uint64_t)(src_len + 1)).
    *(int8_t*)result = (2 | ((int8_t)((0xfffffff & len_add_1) << 4))).
    result[1] = device_id.
    memcpy(&Ergebnis[2], src_buf, ((int64_t)src_len)).*/

    boolean z = true;
    if (dev->addr <= 256 && dev->type_val != 43756)
    {
        z = false;
    }

    std::vector<uint8_t> key = std::vector<uint8_t>(DEFAULT_PHONE_KEY);
    std::vector<uint8_t> cmd = command_with_no_delay(
        5,
        data,
        &key,
        BLE_CMD_RETRY_CNT,
        BLE_CMD_SEND_TIME,
        true,
        USE_DEFAULT_BLE_ADAPTER,
        z,
        dev->addr / 256);

    sendAdvertise(cmd);
    return true;
}


bool sendCommand2(byte bArr[], FastconDevice* dev)
{
    boolean z = true;
    if (dev->addr <= 256 && dev->type_val != 43756)
    {
        z = false;
    }

    std::vector<uint8_t> key = std::vector<uint8_t>(dev->key, dev->key + sizeof(dev->key) / sizeof(dev->key[0]));
    
    std::vector<uint8_t> cmd = command_with_no_delay(
        2,
        std::vector<uint8_t>(bArr, bArr + 12),
        &key,
        BLE_CMD_RETRY_CNT,
        BLE_CMD_SEND_TIME,
        false,
        USE_DEFAULT_BLE_ADAPTER,
        z,
        dev->addr / 256);

    sendAdvertise(cmd);
    return true;
}


void send_off(FastconDevice *deviceInfo)
{
    sendLightCommand(get_OffCommand(), deviceInfo);
}

void send_on(char brightness, FastconDevice *deviceInfo)
{
    sendLightCommand(get_OnCommand( brightness), deviceInfo);
}

void send_brightness(char brightness, FastconDevice *deviceInfo)
{
    sendLightCommand(get_brightnessCommand(brightness), deviceInfo);
}

void send_white(char whiteness, FastconDevice *deviceInfo)
{
    sendLightCommand(get_whiteCommand(whiteness), deviceInfo);
}
void send_rgb(char r, char g, char b, char brightness, bool abs, FastconDevice *deviceInfo)
{
    sendLightCommand(get_rgbCommand(r, g, b, brightness, abs), deviceInfo);
}

boolean sendDiscRes(FastconDevice *dev)
{
    byte bArr[12];
    boolean z = true;
    if (dev->addr > 256 || dev->type_val == 43756)
    {
        // TODO
        //     bArr = new byte[18];
        //   BLEUtil.package_disc_res2(parseStringToByte(bLEDeviceInfo.did), bLEDeviceInfo.addr, bLEDeviceInfo.groupId, 1, this.mPhoneKey, bArr);
    }
    else
    {
        memccpy(bArr, dev->did, 0, 6);
        bArr[6] = (byte)dev->addr;
        bArr[7] = 0x01;
        bArr[8] = DEFAULT_PHONE_KEY[0];
        bArr[9] = DEFAULT_PHONE_KEY[1];
        bArr[10] = DEFAULT_PHONE_KEY[2];
        bArr[11] = DEFAULT_PHONE_KEY[3];

        Serial.println("BLEFastConHelper.sendDiscRes: DID : " + byte_2_str(dev->did, 6) + " addr: " + dev->addr);
    }

    return sendCommand2(bArr, dev);
}


