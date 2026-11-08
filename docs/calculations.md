# Calculations

## 1. Display
Status: Frozen, Nov 8 2026

Inputs
- Blades: 1 plus counterweight (cheapest, fewest parts)
- LED: APA102-2020 (clocked SPI, fast refresh, no PWM smear)
- Rows: 72 (enough detail for expressions, divisible by 8)
- Pitch: 2 mm (smallest hand-solderable APA102)
- Radius: 50 mm (face width close to head proportions)
- Columns: 200 per rev (horizontal detail costs no hardware)
- Speed: 25 rev/s (minimum for low flicker with 1 blade)

Derived
- Image height = rows x pitch = 144 mm
- Diameter = 2 x radius = 100 mm
- Column width = 2 x pi x radius / columns = 1.57 mm
- Column period = 1 / (columns x speed) = 200 us
- Bytes per column = rows x 4 + overhead = about 300 bytes
- SPI rate needed = bits per column / column period = about 12 Mbit/s
- Frame buffer = rows x columns x 3 = about 43 KB
- Centripetal accel = (2 x pi x speed)^2 x radius / 9.81 = about 125 g

Checks
- SPI rate: needs 12, APA102 reliable to about 20 Mbit/s. Pass.
- RAM: 2 buffers need 86 KB, ESP32-S3 has 512 KB. Pass.

## 2. Position sensing
## 3. Mechanics
## 4. Power
## 5. Wireless
