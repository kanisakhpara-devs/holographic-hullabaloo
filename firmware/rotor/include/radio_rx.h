// Radio: ESP-NOW receiver on core 0, MAC-filtered to the base. Checks magic, version and CRC-8, keeps the newest StatePacket. Sends a StatusPacket back every revolution or so.
#pragma once
#include <Arduino.h>
void radio_begin();
bool radio_have_state();
uint32_t radio_last_packet_ms();
