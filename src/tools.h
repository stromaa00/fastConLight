#ifndef TOOLS
#define TOOLS

#include <Arduino.h>
#include <esp_gap_ble_api.h>
#include <vector>


std::vector<String> splitString(const String &str, char delimiter);
std::vector<String> split(String s, String delimiter);
String byte_2_str(char *bytes, int size, char separator = 0, bool = false);
String byte_2_str(unsigned char *bytes, int size, char separator = 0, bool = false);
char str_2_byte(String str);
void  string_2_byte(String str, char *bytes, int size);
char* string_2_byte(String str);
String bytevector_2_str(const std::vector<uint8_t> &bytes, char separator = 0, bool = false);
String typeToString(esp_ble_gap_adv_type_t type);

void parseBLEadvdate(u_int8_t *bytes, int size);

uint16_t reverse_16(uint16_t d);
uint8_t reverse_8(uint8_t d);
uint16_t crc16(const std::vector<uint8_t> &addr, const std::vector<uint8_t> &data);
void charArrayToStr(char *dst, const char *src, const uint16_t length);
char *charArrayToStr(const char *src, const uint16_t length);

static char *allocateAndCopy(String *input)
{
    char *uniqueIdChar = new char[input->length() + 1];
    log_v("allocateAndCopy: %s", input->c_str());
    input->toCharArray(uniqueIdChar, input->length() + 1);
    return uniqueIdChar;
}

#endif