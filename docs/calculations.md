# Calculations

## 1. Display
Status: Frozen Nov 8 2026, reworked Nov 9 2026 (2 blades, 2.2 mm pitch, parallel LED chains)

### What I picked
- Two blades opposite each other, 50 mm from the axis. One blade at 25 spins/s flickers, two blades give 50 Hz and balance each other.
- APA102-2020 LEDs. They have a separate clock line so they update way faster than WS2812, and they don't smear when spinning.
- 72 LEDs tall on each blade. Enough to show expressions properly.
- 2.2 mm between LEDs. The LEDs are 2.0 mm wide, so 2.0 mm pitch would have them touching.
- 200 columns per spin. More columns means sharper curves sideways, and it costs zero extra hardware.
- 25 spins per second (1500 RPM).
- Both blades show the same picture, blade 2 is just 100 columns ahead of blade 1.
- Each blade is split into 2 chains of 36 LEDs. Both chains start at the middle of the blade, one runs up and one runs down.
- All 4 chains get sent at the same time by the ESP32-S3's LCD parallel peripheral, with one shared clock.
- Brightness only uses the 8-bit colour values. The 5-bit global brightness stays at max (31) because it's a slow PWM that would chop each column into dashes.

### What that works out to
- Height: 72 LEDs x 2.2 mm = about 158 mm tall.
- Width: 50 mm x 2 = 100 mm across.
- Each column is 2 x pi x 50 / 200 = about 1.57 mm wide, so a pixel is 2.2 mm tall by 1.57 mm wide.
- Each column gets 1 / (200 x 25) = 200 microseconds before the next one.
- Every spot on the cylinder gets passed by a blade 2 x 25 = 50 times a second.
- Each spot is only lit 2 x 200 us out of every 40 ms, so 1 percent of the time.
- One chain per column: 36 x 4 bytes + 4 start bytes + about 3 end bytes = about 151 bytes = about 1210 bits.
- At 12 MHz that takes about 100 us, so the bus is busy half the column.
- The LEDs at the tips update about 100 us after the ones in the middle, which is half a column (about 0.8 mm). Both halves bend the same way, so a vertical line gets a very slight bend with no break in the middle.
- The LCD peripheral sends one byte per clock tick, one bit per chain, so each column is about 1210 bytes in the DMA buffer. Two of them take turns: core 1 fills one while the other is being sent.
- One full frame is 72 x 200 x 3 bytes = about 43 KB.
- The colour PWM runs at about 20 kHz, so about 4 PWM cycles fit in each column. No visible dashes.
- Everything on the blades feels about 126 g at this speed.

### Does it work?
- Flicker: 50 Hz is around where flicker stops being obvious. Yes.
- Clock: 12 MHz against a 15 MHz max in the 2020 datasheet, so only 1.25x headroom. If it glitches I drop to 10 MHz (about 121 us, 61 percent busy). Still works.
- RAM: two frame buffers are 86 KB plus about 2.4 KB of DMA buffers, and the ESP32-S3 has 512 KB. Easily.
- Blade alignment: if blade 2 isn't exactly opposite, the face doubles up. 0.5 mm off is about 0.3 of a column, so the firmware gets an angle trim per blade and the blade mounts get slotted holes to line up the rows.
- Pitch: 0.2 mm gap between LEDs. Need to check JLC's minimum part spacing when picking parts.
- Soldering: 2020s have their pads underneath, so they need JLC assembly or hot air, not a soldering iron.

## 2. Position sensing
Status: Frozen Nov 8 2026, reworked Nov 9 2026 (moved outside the coil)

### What I picked
- A DRV5023FAQDBZR hall sensor on the underside of the hub PCB, facing down, 30 mm from the axis. It senses all the time instead of sampling, runs on 3.3 V, and only needs one magnet.
- It sits at 30 mm so it's outside the wireless power coil. At 15 mm it would be right on top of it.
- One N52 neodymium magnet (6 x 3 mm) in the top of the base, also at 30 mm, with a 3 mm air gap and nothing in between. Every time the sensor passes it, that's angle zero.
- 10 kOhm pull-up to 3.3 V on the output, 0.1 uF cap right next to VCC.
- The output goes LOW when the magnet is under it (open drain), so the capture triggers on the falling edge, which is the magnet's entry point.
- It only reacts to a south pole, so the magnet's south face points up at the chip.
- The ESP32-S3's capture unit timestamps the pulse in hardware, so radio stuff can't mess up the timing.
- A hardware timer on core 1 handles the columns. The radio lives on core 0.
- I guess the next spin's length by averaging the last 4 spins.
- The magnet sits just before where the face starts, so any timing drift ends up on the hair at the back where nobody notices.
- One magnet is enough for both blades, because blade 2 is always 180 degrees from blade 1.

### What that works out to
- One spin takes 1 / 25 = 40 ms.
- Each column is 360 / 200 = 1.8 degrees.
- The sensor moves at 2 x pi x 0.030 x 25 = about 4.7 m/s.
- So the pulse lasts roughly 6 mm / 4.7 m/s = about 1.3 ms.
- The magnet gives about 100 mT at 3.6 mm (gap plus the chip's package), and the sensor needs 6.8 mT at most to trigger.
- The sensor has 13 us of delay (25 us max), which is 0.07 to 0.13 of a column. It's always the same, so I just shift the image to cancel it.
- If the motor speed changes between spins, the error at the end of the spin is (speed change) x 200 columns.
- 1 percent change = 2 columns off. You'd see a tear.
- 0.25 percent change = half a column off. Fine.

### Does it work?
- Jitter: I want it under a quarter column (50 us). The hardware timestamp is accurate to about 12.5 ns. Way under.
- Pulse length: 1.3 ms is way longer than a 200 us column, so the edge is clean. Yes.
- Field: about 15x more than it needs. Yes.
- Coil: the coil's outer edge has to stay inside about 20 mm radius so the sensor has 10 mm of clearance. Check on the scope with the coil running that there are no extra pulses.
- Speed stability: the motor has to stay within 0.25 percent between spins. Section 3.

## 3. Mechanics
Status: Frozen Nov 8 2026, reworked Nov 9 2026 (2 blades, battery on the axis, coil stack)

### What I picked
- Rotor is a U frame made of aluminium: a bottom plate on the motor, a blade post 50 mm out on each side, and a top bar joining the two posts
- Each blade PCB is bolted to a 10 x 10 x 1 mm aluminium angle with M2 screws, nylon washers and Kapton tape in between (no straps, they creep), with slotted holes so the two blades can be lined up
- All the aluminium is matte dark grey or black (black anodised, or self-etching primer plus matte black spray)
- The two blades balance each other; trim weights are M3 screws and washers
- The LiPo sits on top of the top bar, centred on the axis, so it adds no imbalance and feels almost no spinning force
- The bottom plate gets a hole in the middle bigger than the coil, so the aluminium stays out of the coil's field
- The hub PCB hangs under the bottom plate on standoffs and carries no load
- On the underside of the hub: the receive coil, a ferrite sheet between the coil and the PCB, and the hall sensor at 30 mm
- The transmit coil sits in the top of the base facing up, with its own ferrite under it and a 3 mm air gap to the receive coil
- The ESP32-S3 antenna sticks out past the edge of the plate with about 15 mm clear, away from the coil
- Motor is a 12 V brushed DC motor with ball bearings, about 3000 RPM with no load, 5 mm shaft, rigid flange coupling under 22 mm across
- Base ESP32 drives the motor with PWM through a logic level MOSFET and a flyback diode
- The rotor sends its spin time to the base over ESP-NOW every spin, and the base runs a PI loop to hold 25 rev/s
- No 3D printed parts on the rotor; base parts get printed in PETG

### What that works out to
- Spin speed: 2 x pi x 25 = about 157 rad/s
- Pull at 50 mm: 157 x 157 x 0.05 = about 1230 m/s^2, which is about 126 g
- Tip speed: 157 x 0.05 = about 7.9 m/s
- Each blade: PCB about 5.5 g + aluminium angle about 8 g (158 mm long) = about 14 g
- Force on each blade: 0.014 x 1230 = about 17 N
- With the aluminium angle in the U frame each blade bends about 0.07 mm
- Balance: each blade is about 14 g x 50 mm = 700 g mm, and they cancel each other out
- Leftover imbalance target: under 20 g mm, which is about 0.5 N on the motor bearing
- Battery on the axis: a 25 g battery 1 mm off centre is already 25 g mm, so it has to sit within about 0.5 mm of the axis or get trimmed out
- Whole rotor: about 110 g, about 1.4 J stored when spinning
- Rotor sweep is about 104 mm, so the cover is about 125 mm across and about 220 mm tall above the base
- Motor runs at about half its no load speed, so the PI loop has room to push

### Does it work?
- Bending: yes, 0.07 mm is nothing and the LED solder joints won't flex
- Balance: yes once it's trimmed; two matching blades start out close to balanced, then spin up slowly and add washers until the shaking stops
- Coil: no aluminium in the field and ferrite behind both coils, so no eddy current heating; the exact hole size comes from the coil I pick
- Speed: the PI loop plus the rotor's own inertia should hold 0.25 percent spin to spin, but I'll only know for sure when I check the hall pulse on the scope
- Paint: adds almost no weight; paint before balancing, and keep the Kapton because paint isn't a reliable insulator
- Safety: 7.9 m/s and 1.4 J is low, the battery barely feels the spin, and the cover catches anything that comes loose
- Still to pick: exact motor, coupling and coil part numbers (step 2)

## 4. Power
Status: Frozen Nov 9 2026

### What I picked
- Main power is wireless: a fixed transmit coil in the base and a spinning receive coil under the hub, both centred on the axis
- The 12 V wall adapter (12 V 3 A) runs the motor driver and the coil transmitter
- The laptop USB only carries data and powers the base ESP32, it can't power the motor or the rotor
- On the rotor, the coil's 5 V goes into a power-path charger: it runs the rotor and charges the battery at the same time
- The battery is a 1S LiPo, about 1000 to 1500 mAh, with a protection board, on the axis, and it's only backup: it fills in for short peaks and takes over if the coil stops
- After the charger: boost to 5 V, then a 3.3 V LDO for the ESP32-S3 and hall sensor, and a P-MOSFET load switch for both blades
- Battery voltage goes through a resistor divider into an ADC so the base knows the charge level, cutoff at 3.4 V
- An 8-channel 74AHCT buffer running off 5 V level-shifts the 4 data lines and the clock to the LEDs
- Firmware caps both blades together at 1.0 A
- Hub PCB keeps a USB-C port for flashing and debugging the rotor ESP32, which can charge the battery too
- Motor: low side logic level N-MOSFET, flyback Schottky diode, 20 kHz PWM, one direction only so no H-bridge

### What that works out to
- APA102-2020 max is 18 mA per colour, so 54 mA per LED at full white; real 2020s run closer to 10 mA per colour
- All 144 LEDs at full white would be about 7.8 A (39 W) on paper, which the firmware cap never allows
- Each LED draws 0.7 to 1 mA even when off, about 0.14 A for both blades, so the load switch cuts it in sleep
- With two blades every spot gets lit twice per spin, so each LED only needs about half brightness to look the same as one blade
- A typical talking face lights about 25 percent of the LEDs at about 15 mA each: 36 x 15 mA = about 0.54 A, plus 0.14 A idle = about 0.7 A
- ESP32-S3: about 0.1 A average, 0.35 A in radio bursts
- Typical rotor total: about 0.8 A at 5 V = 4 W, about 4.4 W before the boost
- Peak rotor total with the cap: about 6.75 W at 5 V, about 7.5 W before the boost
- Sleep (LEDs cut, radio listening): about 0.55 W
- The coil receiver should give 5 V 1.5 A so the battery mostly rests; 5 V 1 A is the minimum
- With a 1200 mAh battery, the backup runs about 50 minutes at a typical load
- The coil transmitter draws about 10 W from the 12 V side because wireless power loses a chunk on the way
- Motor plus coil is about 15 W, and the 12 V 3 A adapter gives 36 W
- The boost has to give 5 V at 1.5 A or more from a 3.0 V input, so cheap MT3608 or SX1308 boards are too weak
- The LDO drops 1.7 V, so at 0.35 A it burns about 0.6 W and needs a SOT-223 package, not a SOT-23

### Does it work?
- Yes: the coil covers typical use, the battery covers peaks and outages, and nothing needs plugging in to charge
- Idle current is a big chunk of the budget, so the load switch has to actually cut the blades when it sleeps
- Decoupling: a 0.1 uF cap next to every LED, on the front beside the LED column because the back is bolted to the angle; 10 uF every 18 LEDs, about 220 uF bulk at the hub
- Power goes up each blade from the bottom on wide copper, under 30 mV drop
- The battery is on the axis, so it barely feels the spin, and the switch slides vertically so nothing can flip it
- Still open: coil module rating, boost and charger chips, motor current, all decided when picking parts

## 5. Wireless
Status: Frozen Nov 9 2026

### What I picked
- Laptop to base: USB serial at 115200 baud through the base dev board's USB chip
- Base to rotor and back: ESP-NOW on one fixed Wi-Fi channel, no router, no venue Wi-Fi
- Every packet starts with a magic byte, a version byte, a type byte and a sequence number; serial packets also get a length byte and a CRC-8 because USB serial has no checksum of its own (ESP-NOW already has one)
- Commands always carry the whole state (mode, emotion, mouth level 0 to 4, look angle, brightness), never "change X by Y", so one lost packet gets fixed by the next one
- Sequence numbers let the rotor throw away old or repeated packets
- Laptop sends a command whenever something changes, mouth levels at 25 per second while talking (one per frame, faster is pointless), and a heartbeat with the full state 5 times a second
- The rotor sends a status packet once every spin: spin time, battery voltage, whether the coil is powering it
- The base sends the laptop button presses, both distance sensor readings, the rotor's battery and whether the link is up
- The base and rotor only accept packets from each other's MAC address, and ESP-NOW encryption is on, because other people at the faire might be using ESP-NOW too
- On boot the base scans for the quietest channel out of 1, 6 and 11 and uses it; the rotor tries channels until it hears the base's heartbeat
- The laptop sends each mouth level about 50 ms before its bit of audio plays, so the mouth lines up with the sound; the exact lead gets tuned by filming it
- Failsafes: no command for 1 s and the rotor goes back to its own idle animations (blinking, looking around); no laptop for 2 s and the base tells the rotor to go idle, and walking up still wakes it because the distance sensors are on the base
- No rotor status for 0.5 s and the base holds its last motor PWM; nothing for 10 s and it spins down and tells the laptop
- The motor PWM has a hard cap so even with no feedback it can't go past about 28 rev/s
- Rotor firmware gets flashed over the hub's USB-C with the rotor stopped

### What that works out to
- Command packet: 4 header bytes + about 6 bytes of state = about 10 bytes
- Rotor status packet: 4 header bytes + 4 (spin time) + 2 (battery) + 1 (flags) = about 11 bytes
- Serial: about 30 packets a second x about 12 bytes = about 360 bytes/s, and 115200 baud carries about 11,500 bytes/s, so about 30x headroom
- Radio: about 30 packets a second down and 25 up, so about 55 packets a second
- Each ESP-NOW packet takes about 1 ms of air time at the default 1 Mbit/s, including the reply, so about 5.5 percent of the air
- Base to rotor distance is about 5 to 10 cm, so the signal is strong even while the aluminium spins past
- Latency, laptop to face: serial about 1 to 5 ms, radio about 1 to 3 ms (up to about 20 ms if it has to retry), then up to 40 ms waiting for the next spin to swap in the new frame
- That's about 25 to 45 ms normally, about 65 ms at worst
- Lip sync: people notice a mouth trailing the sound by more than about 45 ms, so sending mouth levels 50 ms early covers the worst case

### Does it work?
- Latency: 65 ms at worst against a 100 ms target. Yes.
- Bandwidth: serial and radio are both barely used. Yes.
- Lost packets: every packet carries the full state and there's a heartbeat 5 times a second, so a lost packet is fixed within 200 ms at most. Yes.
- Speed control without the radio: the rotor's inertia holds it within 0.25 percent spin to spin and the rotor measures every spin anyway, so the face stays steady; the PI loop only keeps the average at 25 rev/s. Yes.
- Overspeed: capped in the base firmware, so a dead link can't double the speed.
- Crowded 2.4 GHz at the faire: quietest channel at boot, retries, and a 5 percent air time load. It should hold up, but I'll test it next to a busy Wi-Fi network before the faire.
- Timing: the radio runs on core 0, the column timer and LED DMA on core 1, so radio traffic can't shift the columns.
- Motor noise: 100 nF caps across the motor terminals and from each terminal to the motor case keep brush noise out of the base.
- Coil: it runs at a few hundred kHz, nowhere near 2.4 GHz, so it doesn't bother the radio.
- Base enclosure: the top panel can't be metal, because the rotor's antenna talks to the base through it.
