// Numbers frozen in docs/calculations.md. Change them there first, then here.
#pragma once
#define COLUMNS_PER_REV   200   // 1.8 degrees each
#define LEDS_PER_CHAIN     36
#define CHAINS              4   // 2 blades x 2 chains
#define ROWS               72   // LEDs per blade
#define TARGET_REV_US   40000   // 25 rev/s
#define LED_CLOCK_HZ 12000000   // APA102-2020 max is 15 MHz
#define LED_CURRENT_CAP_MA 800  // firmware cap so the charger never runs out of input power
#define HEARTBEAT_TIMEOUT_MS 1000  // no packet for this long = fall back to local idle face

// LED current estimate (used by the framebuffer to enforce LED_CURRENT_CAP_MA).
// Adafruit 3341 datasheet: 18 mA max per colour channel, about 1 mA per LED doing nothing.
// These are worst case numbers, so the cap is on the safe side. Measure a white blade and replace them.
#define LED_MA_PER_CHANNEL 18
#define LED_IDLE_MA         1

// Face idle behaviour (face.cpp)
#define BLINK_MIN_MS      2500   // time between blinks is random in this range
#define BLINK_MAX_MS      6000
#define BLINK_LEN_MS       120
#define GLANCE_MIN_MS     6000   // time between glances (idle mode only)
#define GLANCE_MAX_MS    14000
#define GLANCE_HOLD_MIN_MS 600
#define GLANCE_HOLD_MAX_MS 1500
#define GLANCE_MAX_COLS      3   // how far a glance turns the head, in columns (1.8 degrees each)
#define SLEEP_AFTER_MS   120000  // no talking or face change for 2 min = sleepy face
#define DARK_AFTER_MS    600000  // 10 min = LEDs dark
