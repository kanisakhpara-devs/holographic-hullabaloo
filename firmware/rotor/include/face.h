// Face renderer: copies the rebaked frames from faces.bin (face columns) and base_back.bin (hair all the way
// round) into the framebuffer. One frame per emotion x mouth shape, plus a blink frame per emotion.
// Idle state machine: blink, glance, sleepy face after inactivity, dark after 10 min.
// The radio calls face_set_state() with every StatePacket. With no packet for HEARTBEAT_TIMEOUT_MS the
// face falls back to local idle (neutral, mouth closed, still blinking and glancing).
#pragma once
#include <Arduino.h>

void face_begin();
void face_update(uint32_t now_ms);
// mode = Mode, emotion = Emotion 0..11, mouth = Viseme 0..5, look = head turn in columns (negative = left),
// brightness 0..255. Out of range values are clamped. Safe to call from the radio callback on core 0.
void face_set_state(uint8_t mode, uint8_t emotion, uint8_t mouth, int8_t look, uint8_t brightness);
bool face_data_ok();   // false if faces.bin / base_back.bin are missing or the wrong size
