// Column timer: hardware timer that fires COLUMNS_PER_REV times per revolution, re-synced at every Hall pulse. Each tick tells led_output which column to send. Runs on core 1.
#pragma once
#include <Arduino.h>
void column_timer_begin();
uint16_t column_timer_current();
