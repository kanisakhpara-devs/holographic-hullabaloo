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
