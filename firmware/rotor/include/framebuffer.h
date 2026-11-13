// Framebuffer: 200 columns x 72 rows, double buffered. Blade 2 shows column + 100 (it is 180 degrees around). Swap buffers only at the Hall pulse so the image never tears. Also applies the LED current cap by scaling brightness.
#pragma once
#include <Arduino.h>
void fb_begin();
void fb_swap();
uint32_t fb_estimated_ma();
