#include "framebuffer.h"

static fb_frame_t buf[2];
static volatile uint8_t front_i = 0;
static volatile bool pending = false;
static uint32_t ma[2] = {0, 0};

// Every LED shows some column all the time while spinning, so the average current is the average over the
// 200 columns of what one column draws, times 2 blades. Sum over all pixels / 200 gives one column's worth.
static uint32_t estimate_ma(const fb_frame_t& f) {
  uint32_t sum = 0;                                   // sum of all channel values, max 200*72*3*255 = 11 M
  for (int c = 0; c < COLUMNS_PER_REV; c++)
    for (int r = 0; r < ROWS; r++)
      sum += f[c][r][0] + f[c][r][1] + f[c][r][2];
  uint64_t lit = (uint64_t)sum * LED_MA_PER_CHANNEL * 2 / (255ULL * COLUMNS_PER_REV);
  return (uint32_t)lit + 2 * ROWS * LED_IDLE_MA;
}

void fb_begin() {
  memset(buf, 0, sizeof(buf));
  front_i = 0;
  pending = false;
  ma[0] = ma[1] = 2 * ROWS * LED_IDLE_MA;
}

fb_frame_t& fb_back() { return buf[front_i ^ 1]; }
const fb_frame_t& fb_front() { return buf[front_i]; }
bool fb_swap_pending() { return pending; }

void fb_commit() {
  uint8_t bi = front_i ^ 1;
  fb_frame_t& b = buf[bi];
  uint32_t est = estimate_ma(b);
  uint32_t idle = 2 * ROWS * LED_IDLE_MA;
  if (est > LED_CURRENT_CAP_MA && est > idle) {
    // scale only the lit part, the idle current doesn't change with colour
    uint32_t scale = (uint32_t)(LED_CURRENT_CAP_MA - idle) * 256 / (est - idle);   // 0..255 (8.8 fixed point)
    for (int c = 0; c < COLUMNS_PER_REV; c++)
      for (int r = 0; r < ROWS; r++)
        for (int k = 0; k < 3; k++)
          b[c][r][k] = (uint8_t)((b[c][r][k] * scale) >> 8);
    est = estimate_ma(b);
  }
  ma[bi] = est;
  pending = true;      // set last, so a swap never shows a half-written buffer
}

void IRAM_ATTR fb_swap() {
  if (!pending) return;
  front_i ^= 1;
  pending = false;
}

uint32_t fb_estimated_ma() { return ma[front_i]; }
