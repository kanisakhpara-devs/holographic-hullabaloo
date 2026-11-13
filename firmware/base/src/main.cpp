// Base firmware entry point: motor, presence, button, laptop link, radio to the rotor.
#include <Arduino.h>
#include "pins.h"
#include "packet.h"
#include "motor.h"
#include "sensors.h"
#include "serial_link.h"
#include "radio_tx.h"

void setup() {
  pinMode(PIN_TALK_BUTTON, INPUT_PULLUP);
  serial_begin();
  sensors_begin();
  radio_begin();
  motor_begin();
}

void loop() {
  uint32_t now = millis();
  serial_poll();
  motor_set_target(sensors_someone_near());  // TODO: 10 min timeout before stopping
  motor_update(radio_rotor_rev_us());
  radio_update(now);
  delay(1);
}
