// Power: reads VBAT_SENSE (x2 for the divider), PGOOD and CHG. Turns LEDs off below a safe battery voltage.
#pragma once
#include <Arduino.h>
void power_begin();
uint16_t power_battery_mv();
bool power_good();
bool power_charging();
