// USB serial to the laptop at 115200: receives full-state commands, checks CRC-8, sends back button, presence and rotor battery.
#pragma once
#include <Arduino.h>
void serial_begin();
bool serial_poll();
