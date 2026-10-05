#ifndef FASTCON_H
#define FASTCON_H

#include <Arduino.h>
#include "BLEUtils.h"

extern BLEAdvertising *pAdvertising;   // BLE Advertisement type
const uint8_t my_key[] = { 0x38, 0x35, 0x31, 0x33 }; //Unique key from BRMesh app (found using USB debugging and adb logcat)

int extractInteger(const char* inputString);
void single_control(const uint8_t* key, const uint8_t* result);
void send_scancommand();

#endif  // FASTCON_H