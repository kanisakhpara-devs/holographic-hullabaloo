// Hall timing: MCPWM capture timestamps each falling edge on PIN_HALL. Spin time = average of the last 4 revolutions. Ignore pulses closer than half a revolution (noise from the coil).
#pragma once
#include <Arduino.h>
void hall_begin();
uint32_t hall_rev_us();
bool hall_spinning();
