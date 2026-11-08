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

### What I picked
- Rotor is a U frame made of aluminium: a bottom plate on the motor, the blade post 50 mm out, a counter post on the other side, and a top bar joining the two posts
- Blade PCB is bolted to a 10 x 10 x 1 mm aluminium angle with M2 screws, nylon washers and Kapton tape in between (no straps, they creep)
- All the aluminium is matte dark grey or black (black anodised, or self-etching primer plus matte black spray)
- The LiPo sits on the counter post at the same height as the middle of the blade, so it doubles as the counterweight
- Trim weights are M3 screws and washers on the counter side
- Hub PCB sits on standoffs on the bottom plate and carries no load; the ESP32-S3 antenna sticks out past the metal with about 15 mm clear around it
- Motor is a 12 V brushed DC motor with ball bearings, about 3000 RPM with no load, 5 mm shaft, rigid flange coupling under 22 mm across
- Base ESP32 drives the motor with PWM through a logic level MOSFET and a flyback diode
- The rotor sends its spin time to the base over ESP-NOW every spin, and the base runs a PI loop to hold 25 rev/s
- No 3D printed parts (for now)

### What that works out to
- Spin speed: 2 x pi x 25 = about 157 rad/s
- Pull at 50 mm: 157 x 157 x 0.05 = about 1230 m/s^2, which is about 126 g
- Tip speed: 157 x 0.05 = about 7.9 m/s
- Blade mass: PCB about 5 g + aluminium angle about 8 g = about 13 g
- Force on the blade: 0.013 x 1230 = about 16 N
- Bare PCB blade would bend about 5 mm held at both ends, about 47 mm held only at the bottom
- With the aluminium angle in the U frame: about 0.05 mm
- Balance: 13 g x 50 mm = about 650 g mm, so the counter side needs about 650 g mm at the same height
- Leftover imbalance target: under 20 g mm, which is about 0.5 N on the motor bearing
- Whole rotor: about 70 g, about 0.7 J stored when spinning
- Rotor sweep is about 104 mm, so the cover is about 125 mm across and about 190 mm tall above the base
- Motor runs at about half its no load speed, so the PI loop has room to push

### Does it work?
- Bending: yes, 0.05 mm is nothing and the LED solder joints won't flex
- Balance: yes once it's trimmed; spin up slowly and add washers until the shaking stops
- Speed: the PI loop plus the rotor's own inertia should hold 0.25 percent spin to spin, but I'll only know for sure when I check the hall pulse on the scope
- Paint: adds almost no weight; paint before balancing, and keep the Kapton because paint isn't a reliable insulator
- Safety: 7.9 m/s and 0.7 J is low, and the cover catches anything that comes loose
- Still to pick: exact motor and coupling part numbers (step 2)
## 4. Power
## 5. Wireless
