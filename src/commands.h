#ifndef COMMANDS_H
#define COMMANDS_H

#include <ArduinoHA.h>

void onStateCommand(bool state, HALight *sender);
void onBrightnessCommand(uint8_t brightness, HALight *sender);
void onColorTemperatureCommand(uint16_t temperature, HALight *sender);
void onRGBColorCommand(HALight::RGBColor color, HALight *sender);
void onWhiteCommand(uint8_t whiteness, HALight *sender);

#endif // COMMANDS_H