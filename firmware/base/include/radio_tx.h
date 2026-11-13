// Radio: ESP-NOW sender to the rotor's MAC, quietest of channels 1/6/11 chosen at boot. Forwards the latest state and a 5 Hz heartbeat; receives StatusPackets.
#pragma once
#include <Arduino.h>
void radio_begin();
void radio_update(uint32_t now_ms);
uint16_t radio_rotor_rev_us();
