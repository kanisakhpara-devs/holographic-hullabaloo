// USB CDC serial to the laptop over the ESP32-S3's native USB (shares the cable with the USB sound card): receives full-state commands, checks CRC-8, sends back button, presence and rotor battery.
#pragma once
#include <Arduino.h>
void serial_begin();
bool serial_poll();
