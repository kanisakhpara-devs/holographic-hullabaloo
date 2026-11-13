// Presence: two VL53L0X (front and back). Someone within about 1 m wakes the face; nobody for 10 min sends the rotor to dark mode and stops the motor.
#pragma once
#include <Arduino.h>
void sensors_begin();
bool sensors_someone_near();
