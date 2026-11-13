// Face renderer: builds each frame from layers (head and hair, eyes, brows, mouth frame 0 to 4) for the current emotion. Idle state machine: blink, glance, sleep face after inactivity, dark after 10 min.
#pragma once
#include <Arduino.h>
void face_begin();
void face_update(uint32_t now_ms);
