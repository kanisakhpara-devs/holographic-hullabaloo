// Base pin map. TBD: fill in once the perfboard wiring is decided.
#pragma once
#define PIN_MOTOR_PWM    25  // TBD: gate of the low-side logic-level MOSFET, 20 kHz
#define PIN_TALK_BUTTON  26  // TBD: 16 mm push button to GND, internal pull-up
#define PIN_I2C_SDA      21  // TBD: VL53L0X x2
#define PIN_I2C_SCL      22  // TBD
#define PIN_TOF1_XSHUT   32  // TBD: front sensor, used to give each sensor its own I2C address
#define PIN_TOF2_XSHUT   33  // TBD: back sensor
