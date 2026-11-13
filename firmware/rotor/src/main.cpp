// Rotor firmware entry point. Core 0: radio. Core 1: timing and LED output.
#include <Arduino.h>
#include "pins.h"
#include "config.h"
#include "packet.h"
#include "hall_timing.h"
#include "column_timer.h"
#include "led_output.h"
#include "framebuffer.h"
#include "face.h"
#include "radio_rx.h"
#include "power.h"

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STATUS_LED, OUTPUT);
  power_begin();
  led_begin();        // LEDs stay OFF until spinning is stable
  fb_begin();
  face_begin();
  hall_begin();
  column_timer_begin();
  radio_begin();
}

void loop() {
  uint32_t now = millis();
  // TODO: if no base packet for HEARTBEAT_TIMEOUT_MS, run the local idle face
  face_update(now);
  led_power(hall_spinning());
  digitalWrite(PIN_STATUS_LED, (now / 500) % 2);  // slow blink = alive
  delay(1);
}
