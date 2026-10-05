#include "FastconHALight.h"
#include "ArduinoHa.h"
#include "bletools.h"
#include "blelight.h"



const std::vector<uint8_t> DEFAULT_PHONE_KEY = {0xA1, 0xA2, 0xA3, 0xA4};

/**
 * Binds the FastconHALight object to the network.
 *
 * @param rebind If true, the object will be rebound even if it is already bound.
 * @return 1 if the binding was successful, 0 otherwise.
 */
int FastconHALight::bind(boolean rebind)
{
    if (rebind || status == 1)
    {
        sendDiscRes(this);
    }
    return 1;
}

/**
 * Sets the name of the FastconHALight object.
 *
 * @param name The name to set for the FastconHALight object.
 */
void FastconHALight::setName(String name)
{
    char *uniqueIdChar = allocateAndCopy(&name);
    HALight::setName(uniqueIdChar);
    nameAllocated = true;
}


void FastconHALight::turn_off()
{
    send_off(this);
}

void FastconHALight::turn_on(char brightness)
{
   
    send_on(brightness, this);
}

void FastconHALight::set_brightness(char brightness)
{
    send_brightness(brightness, this);
}

void FastconHALight::set_white(char whiteness)
{
    send_white(whiteness, this);
}
void FastconHALight::set_rgb(char r, char g, char b, char brightness, bool abs)
{
    send_rgb(r, g, b, brightness, abs, this);
}
