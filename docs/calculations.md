# Calculations

## 1. Display
Status: Frozen, Nov 8 2026

What I picked
- One blade with a counterweight on the other side. Cheapest option and the fewest parts.
- APA102-2020 LEDs. They have a separate clock line so they update way faster than WS2812, and they don't smear when spinning.
- 72 LEDs tall. Enough to show expressions properly, and 72 divides by 8, which keeps the data tidy.
- 2 mm between LEDs. That's the smallest APA102 I can still hand-solder.
- 50 mm from the axis to the LEDs. This makes the face wide enough to actually look like a head.
- 200 columns per spin. More columns means sharper curves sideways, and it costs zero extra hardware.
- 25 spins per second (1500 RPM). That's about the slowest one blade can go without flickering.

What that works out to
- Height: 72 LEDs x 2 mm = 144 mm tall.
- Width: 50 mm x 2 = 100 mm across.
- Each column is 2 x pi x 50 / 200 = about 1.57 mm wide.
- Each column gets 1 / (200 x 25) = 200 microseconds before the next one.
- Each column is 72 x 4 bytes plus a bit of overhead, so about 300 bytes.
- Pushing that out every 200 us needs about 12 Mbit/s over SPI.
- One full frame is 72 x 200 x 3 bytes = about 43 KB.
- Everything on the blade feels about 125 g at this speed, so balance really matters.

Does it work?
- SPI: I need 12 Mbit/s and APA102 is happy up to about 20. Yes.
- RAM: two frame buffers are 86 KB and the ESP32-S3 has 512 KB. Easily.

## 2. Position sensing
Status: Frozen, Nov 8 2026 (except speed stability, which depends on section 3)

What I picked
- A DRV5023 hall sensor on the hub PCB. It senses all the time instead of sampling, runs on 3.3 V, and only needs one magnet.
- One N52 neodymium magnet (6 x 3 mm) stuck in the base. Every time the sensor passes it, that's angle zero.
- Sensor sits 15 mm from the axis with a 3 mm gap to the magnet.
- The ESP32-S3's capture unit timestamps the pulse in hardware, so radio stuff can't mess up the timing.
- A hardware timer on core 1 handles the columns. The radio lives on core 0.
- I guess the next spin's length by averaging the last 4 spins.
- The magnet sits just before where the face starts, so any timing drift ends up on the hair at the back where nobody notices.

What that works out to 
- One spin takes 1 / 25 = 40 ms.
- Each column is 360 / 200 = 1.8 degrees.
- The sensor moves at 2 x pi x 0.015 x 25 = about 2.36 m/s.
- So the pulse lasts roughly 6 mm / 2.36 m/s = about 2.5 ms.
- The sensor has about 13 us of delay, which is 0.07 of a column. It's always the same, so I just shift the image to cancel it.
- If the motor speed changes between spins, the error at the end of the spin is (speed change) x 200 columns.
- 1 percent change = 2 columns off. You'd see a tear.
- 0.25 percent change = half a column off. Fine.

Does it work?
- Jitter: I want it under a quarter column (50 us). The hardware timestamp is accurate to about 12.5 ns. Way under.
- Pulse length: 2.5 ms is way longer than a 200 us column, so the edge is clean. Yes.
- Speed stability: the motor has to stay within 0.25 percent between spins. Not sorted yet, that's section 3.

## 3. Mechanics
## 4. Power
## 5. Wireless
