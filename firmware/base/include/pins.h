// Base pin map for the custom ESP32-S3-WROOM-1-N8 base board (pcb/base, Nov 19 revision).
// Matches the base pin map in the README (firmware section) and pcb/base/base.kicad_sch. Keep in sync with the schematic.
// Avoid strapping pins (IO0, IO3, IO45, IO46) and the USB pins (IO19, IO20).
#pragma once

// Motor (AO4406A low-side MOSFET, 33R gate + 100k pull-down, 20 kHz PWM)
#define PIN_MOTOR_PWM     4

// Talk button (to GND, internal pull-up, active low)
#define PIN_TALK_BUTTON   5

// VL53L0X distance sensors (front and back). XSHUT lines give each sensor its own I2C address.
#define PIN_TOF1_XSHUT    6   // front sensor
#define PIN_TOF2_XSHUT    7   // back sensor
#define PIN_I2C_SDA       8   // VL53L0X x2
#define PIN_I2C_SCL       9

// MAX98357A speaker amp (I2S out). SD_MODE tied through 1M to this pin (mono).
#define PIN_AMP_BCLK      12
#define PIN_AMP_LRC       13
#define PIN_AMP_DIN       14
#define PIN_AMP_EN        15

// INMP441 mic (I2S in)
#define PIN_MIC_SCK       16
#define PIN_MIC_WS        17
#define PIN_MIC_SD        18

// Status LED
#define PIN_STATUS_LED    21

// USB (native USB: USB audio + CDC serial to the laptop). Do not reuse.
#define PIN_USB_DN        19
#define PIN_USB_DP        20
