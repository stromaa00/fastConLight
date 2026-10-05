
#include "tools.h"

#define ENDIAN_CHANGE_U16(x) ((((x)&0xFF00) >> 8) + (((x)&0xFF) << 8))

char const hex[16] = {'0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F'};

// for string delimiter



std::vector<String> split(String s, String delimiter)
{
    size_t pos_start = 0, pos_end, delim_len = delimiter.length();
    std::vector<String> res;

    while ((pos_end = s.indexOf(delimiter, pos_start)) != -1)
    {
        res.push_back(s.substring(pos_start, pos_end));
        pos_start = pos_end + delim_len;
    }
    res.push_back(s.substring(pos_start, s.length()));
    return res;
}

char str_2_byte(String str)
{
    assert(str.length() == 2);
    //Serial.println("str_2_byte: " + str + " -> " + String(atoi(str.c_str())));
    return strtol(str.c_str(), nullptr, 16);
};

char* string_2_byte(String str)
{
    assert(str.length() % 2 == 0);
    
    char *bytes = new char[str.length()];
    for (size_t i = 0; i < str.length(); i+=2)
    {
        bytes[i] =  atoi(str.substring(i, i+2).c_str());
    }
    return bytes;
};

void string_2_byte(String str, char *bytes, int size)
{
    assert(str.length() % 2 == 0);   
    assert(str.length()  == size * 2);   
    
    for (size_t i = 0; i < size; i++)
    {
        bytes[i] =  str_2_byte(str.substring(i*2, i*2+2).c_str());
    }
};


std::vector<String> splitString(const String &data, char delimiter)
{
    std::vector<String> tokens;
    size_t start = 0;
    size_t end = data.indexOf(delimiter);

    while (end != -1)
    {
        tokens.push_back(data.substring(start, end));
        start = end + 1;
        end = data.indexOf(delimiter, start);
    }

    tokens.push_back(data.substring(start));
    return tokens;
}

String byte_2_str(char *bytes, int size, char separator, bool addLength)
{
    String str;
    if (addLength)
        str = "[" + String(size) + "] ";

    for (int i = 0; i < size; ++i)
    {
        const char ch = bytes[i];
        str += hex[(ch & 0xF0) >> 4];
        str += hex[ch & 0xF];
        if (separator != 0 && i < size)            str += separator;
    }
    return str;
}

String byte_2_str(unsigned char *bytes, int size, char separator, bool addLength)
{
    String str;
    if (addLength)
        str = "[" + String(size) + "] ";

    for (int i = 0; i < size; ++i)
    {
        const char ch = bytes[i];
        str += hex[(ch & 0xF0) >> 4];
        str += hex[ch & 0xF];
        if (separator != 0 && i < size)
            str += separator;
    }
    return str;
}

String bytevector_2_str(const std::vector<uint8_t> &bytes, char separator, bool addLength)
{
    String str;
    if (addLength)
        str = "[" + String(bytes.size()) + "] ";

    for (int i = 0; i < bytes.size(); ++i)
    {
        const char ch = bytes[i];
        str += hex[(ch & 0xF0) >> 4];
        str += hex[ch & 0xF];
        if (separator != 0 && i < bytes.size())
            str += separator;
    }
    return str;
}

String typeToString(esp_ble_gap_adv_type_t type)
{
    if (type == 0x13)
        return "ADV_IND        ";
    if (type == 0x15)
        return "ADV_DIRECT_IND ";
    if (type == 0x12)
        return "ADV_SCAN_IND   ";
    if (type == 0x10)
        return "ADV_NONCON_IND ";
    if (type == 0x1b)
        return "ADV_SCAN_RSP_TO_ADV_IND      ";
    if (type == 0x1a)
        return "ADV_SCAN_RSP_TO_ADV_SCAN_IND ";
    return "n/a";
};

uint16_t reverse_16(uint16_t d)
{
    uint16_t result = 0;
    for (int i = 0; i < 16; ++i)
    {
        result |= ((d >> i) & 1) << (15 - i);
    }
    return result;
}

uint8_t reverse_8(uint8_t d)
{
    uint8_t result = 0;
    for (int i = 0; i < 8; ++i)
    {
        result |= ((d >> i) & 1) << (7 - i);
    }
    return result;
}

uint16_t crc16(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data)
{
    uint16_t crc = 0xffff;

    // iterate over address in reverse
    for (auto it = addr.rbegin(); it != addr.rend(); ++it)
    {
        crc ^= static_cast<uint16_t>(*it) << 8;
        for (int i = 0; i < 4; ++i)
        {
            uint16_t tmp = crc << 1;
            if (crc & 0x8000)
            {
                tmp ^= 0x1021;
            }
            crc = tmp << 1;
            if (tmp & 0x8000)
            {
                crc ^= 0x1021;
            }
        }
    }

    for (size_t i = 0; i < data.size(); ++i)
    {
        crc ^= static_cast<uint16_t>(reverse_8(data[i])) << 8;
        for (int j = 0; j < 4; ++j)
        {
            uint16_t tmp = crc << 1;
            if (crc & 0x8000)
            {
                tmp ^= 0x1021;
            }
            crc = tmp << 1;
            if (tmp & 0x8000)
            {
                crc ^= 0x1021;
            }
        }
    }

    crc = ~reverse_16(crc);
    return crc;
}


void charArrayToStr(
    char* dst,
    const char* src,
    const uint16_t length
)
{
    for (uint8_t i = 0; i < length; i++) {
       // dst[i*2] = pgm_read_byte(&HAHexMap[((char)src[i] & 0XF0) >> 4]);
        //dst[i*2+1] = pgm_read_byte(&HAHexMap[((char)src[i] & 0x0F)]);
    }

    dst[length * 2] = 0;
}

char* charArrayToStr(
    const char* src,
    const uint16_t length
)
{
    char* dst = new char[(length * 2) + 1]; // include null terminator
    charArrayToStr(dst, src, length);

    return dst;
}


