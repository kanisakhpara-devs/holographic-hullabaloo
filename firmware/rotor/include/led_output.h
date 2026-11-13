// LED output: ESP32-S3 LCD peripheral in 8-bit parallel mode with DMA. One clock, four data lines, so all 4 chains are written at once. Per column: 4-byte start frame, 36 LEDs x 4 bytes per chain, end frame. Two ping-pong DMA buffers. Also owns PIN_LED_EN (keep data/clock LOW while it is off).
#pragma once
#include <Arduino.h>
void led_begin();
void led_power(bool on);
void led_send_column(uint16_t column);
