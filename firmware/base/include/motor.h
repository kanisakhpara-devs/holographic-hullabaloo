// Motor: 20 kHz PWM on PIN_MOTOR_PWM. Soft start, PI speed loop using rev_us reported by the rotor, hard PWM cap so the 775 can never exceed about 28 rev/s. Stops if the rotor goes silent.
#pragma once
#include <Arduino.h>
void motor_begin();
void motor_set_target(bool spin);
void motor_update(uint16_t rotor_rev_us);
