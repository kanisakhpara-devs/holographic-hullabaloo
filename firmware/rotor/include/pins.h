// Rotor (hub PCB) pin map. Must match pcb/hub schematic, sheet MCU_USB.
#pragma once

#define PIN_VBAT_SENSE  1   // ADC1: battery through 100k/100k divider (reads half of VBAT)
#define PIN_HALL        4   // DRV5023 output, open drain, 10k pull-up. Goes LOW when the magnet passes
#define PIN_PGOOD       5   // BQ24073 PGOOD, LOW = coil or USB power present
#define PIN_CHG         6   // BQ24073 CHG, LOW = charging
#define PIN_LED_EN      7   // HIGH = 5 V switched on to the blades (through Q3 and Q2)
#define PIN_STATUS_LED  8   // status LED through 1k, HIGH = on
#define PIN_LED_CLK     9   // LCD peripheral clock, buffered into 4 copies by the 74AHCT245
#define PIN_LED_D0     10   // blade 1 chain A data
#define PIN_LED_D1     11   // blade 1 chain B data
#define PIN_LED_D2     12   // blade 2 chain A data
#define PIN_LED_D3     13   // blade 2 chain B data
// IO19 / IO20 are native USB (flashing and Serial). IO0 is the BOOT button.
