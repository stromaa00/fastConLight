#include "commands.h"
#include <Arduino.h>
#include "FastconHALight.h"

void onStateCommand(bool state, HALight *sender)
{
    Serial.println(sender->uniqueId());
    Serial.print("State: ");
    Serial.println(state);
    if (state == true)
    {
        ((FastconHALight *)sender)->turn_on(128);
    }
    else
    {
        ((FastconHALight *)sender)->turn_off();
    }
    sender->setState(state); // report state back to the Home Assistant
}

void onBrightnessCommand(uint8_t brightness, HALight *sender)
{
    Serial.print("Brightness: ");
    Serial.println(brightness);
    Serial.print("Light:");
    Serial.print(sender->getName());

    ((FastconHALight *)sender)->set_brightness(brightness);
    sender->setBrightness(brightness); // report brightness back to the Home Assistant
}

void onColorTemperatureCommand(uint16_t temperature, HALight *sender)
{
    Serial.print("Color temperature: ");
    Serial.println(temperature);
    sender->setColorTemperature(temperature); // report color temperature back to the Home Assistant
}

void onRGBColorCommand(HALight::RGBColor color, HALight *sender)
{
    Serial.print("Light:");
    Serial.print(sender->getName());
    Serial.print("Red: ");
    Serial.println(color.red);
    Serial.print("Green: ");
    Serial.println(color.green);
    Serial.print("Blue: ");
    Serial.println(color.blue);

    sender->setRGBColor(color); // report color back to the Home Assistant
    ((FastconHALight *)sender)->set_rgb(color.red, color.green, color.blue, 128, false);
}


void onWhiteCommand(uint8_t whiteness, HALight *sender)
{
    Serial.print("Light:");
    Serial.print(sender->getName());
    Serial.print("White: ");
    Serial.println(String(whiteness));

    sender->setWhite(whiteness); // report color back to the Home Assistant
    ((FastconHALight *)sender)->set_white(whiteness);
}