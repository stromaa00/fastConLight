#ifndef BLELIGHT_H
#define BLELIGHT_H

#include <vector>
#include <algorithm>
#include "Fastcondevice.h"




void send_off(FastconDevice *deviceInfo);
void send_on(char brightness, FastconDevice *deviceInfo);
void send_brightness(char brightness, FastconDevice *deviceInfo);
void send_white(char whiteness, FastconDevice *deviceInfo);
void send_rgb(char r, char g, char b, char brightness, bool abs, FastconDevice *deviceInfo );
boolean sendDiscRes(FastconDevice *dev);

#endif
