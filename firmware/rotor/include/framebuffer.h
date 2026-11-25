// Framebuffer: 200 columns x 72 rows of RGB, double buffered (2 x 43 KB). Blade 2 shows column + 100
// (it is 180 degrees around). Swap buffers only at the Hall pulse so the image never tears. Also applies
// the LED current cap by scaling brightness. Both chains on a blade run upwards, so each LED is read from
// a column shifted by its position in its chain; that removes the half-column step where the two halves
// meet mid-blade (that part is done in led_output when it reads the front buffer).
//
// Writer (face.cpp, core 1 loop):  if (!fb_swap_pending()) { draw into fb_back(); fb_commit(); }
// Reader (Hall pulse):             fb_swap();  then led_output reads fb_front().
#pragma once
#include <Arduino.h>
#include "config.h"

typedef uint8_t fb_frame_t[COLUMNS_PER_REV][ROWS][3];   // [column][row][r,g,b], row 0 = top

void fb_begin();
fb_frame_t& fb_back();           // the buffer that is NOT on the LEDs; only write while no swap is pending
const fb_frame_t& fb_front();    // the buffer on the LEDs right now
void fb_commit();                // back buffer is finished: apply the current cap, then wait for the next swap
bool fb_swap_pending();
void fb_swap();                  // call at the Hall pulse (or any time the LEDs are off). Safe from an ISR
uint32_t fb_estimated_ma();      // average LED current of the front buffer while spinning, after the cap
