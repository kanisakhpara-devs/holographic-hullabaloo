# Laptop <-> base ESP32-S3 serial protocol

Source of truth for the byte format. `software/companion/device.py` implements it and
`software/tests/test_device.py` checks every example below. If you change one, change all three.
The base firmware (`firmware/shared/packet.h` in the Fallen repo) must match this file.

## Link

- USB serial (CDC) on the ESP32-S3 native USB, VID:PID `303A:1001`, 921600 baud, 8N1, no flow control.
- Open the port with DTR and RTS held low. Toggling them resets the S3 or drops it into the bootloader.
- Binary, fixed 5 byte packets, no length field, no escaping.
- Laptop to device packets start with `0xA5`. Device to laptop packets start with `0x5A`.
- Layout: `[header, cmd, a, b, checksum]` with `checksum = (cmd + a + b) & 0xFF`. The header is not summed.
- Unused `a` or `b` are sent as `0x00`.

## Resync

A receiver keeps a byte buffer. Loop: drop bytes until the header byte is first in the buffer, wait for 5 bytes,
check the checksum. If it matches, consume 5 bytes and handle the packet. If it does not, count one checksum error,
drop exactly one byte (the header) and hunt for the next header byte. A header value inside `a` or `b` is fine,
because a real packet always passes its checksum and a false one almost never does. One corrupted byte costs at most
the packets that overlap it. The firmware should do the same for laptop packets.

## Laptop to device (header 0xA5)

| cmd | name | a | b | meaning |
|---|---|---|---|---|
| 1 | FACE | emotion index 0..11 | 0 | show this face |
| 2 | MOUTH | viseme index 0..5 | 0 | show this mouth shape |
| 3 | POWER | 0 sleep, 1 awake | 0 | sleeping: LEDs off, motor may stop. awake: spin and show |
| 4 | PING | 0 | 0 | heartbeat, device answers PONG |
| 5 | BRIGHTNESS | cap 0..255 | 0 | LED brightness cap, device answers BRIGHTNESS_ACK |
| 6 | SLEEP_ANIM | 0 | 0 | reserved, device ignores it for now |
| 7 | SHOW_EMOTION_TEST | emotion index 0..11 | 0 | hold this face for 3 s (diagnostics), then go back |

Emotion index order: `neutral happy smug angry surprised sad confused sleepy bored suspicious laughing eyeroll`
(0 to 11). Viseme index order: `closed ah oh ee oo fv` (0 to 5).

Examples (hex):

| what | bytes | check |
|---|---|---|
| FACE smug (index 2) | `a5 01 02 00 03` | 1 + 2 + 0 = 3 |
| MOUTH ee (index 3) | `a5 02 03 00 05` | 2 + 3 + 0 = 5 |
| POWER awake | `a5 03 01 00 04` | 3 + 1 + 0 = 4 |
| PING | `a5 04 00 00 04` | 4 |
| BRIGHTNESS 128 | `a5 05 80 00 85` | 5 + 128 = 133 = 0x85 |
| SLEEP_ANIM | `a5 06 00 00 06` | 6 |
| SHOW_EMOTION_TEST eyeroll (index 11) | `a5 07 0b 00 12` | 7 + 11 = 18 = 0x12 |

## Device to laptop (header 0x5A)

| cmd | name | a | b | meaning |
|---|---|---|---|---|
| 1 | PROXIMITY | 1 near, 0 far | 0 | proximity sensor changed (send on change only) |
| 2 | BUTTON | 0 | 0 | talk button pressed (one packet per press) |
| 3 | PONG | 0 | 0 | answer to PING (any packet also counts as a heartbeat) |
| 4 | ROTOR_STATUS | 1 ok, 0 fault | 0 | rotor radio link and motor state, send on change and every 5 s |
| 5 | BRIGHTNESS_ACK | cap now in force | 0 | answer to BRIGHTNESS |

Examples (hex):

| what | bytes | check |
|---|---|---|
| PROXIMITY near | `5a 01 01 00 02` | 1 + 1 = 2 |
| BUTTON | `5a 02 00 00 02` | 2 |
| PONG | `5a 03 00 00 03` | 3 |
| ROTOR_STATUS ok | `5a 04 01 00 05` | 4 + 1 = 5 |
| BRIGHTNESS_ACK 200 | `5a 05 c8 00 cd` | 5 + 200 = 205 = 0xCD |

## Link state machine (laptop side)

1. Port closed. Every second the laptop looks for a COM port. With no port set in Settings it auto-picks only a port
   with VID:PID `303A:1001`. With a port set it opens only that name, and only when it exists.
2. Port open. The laptop sends PING at once, then every 2 s. The link is still DOWN.
3. Link UP when the first valid packet arrives (a PONG is enough). The laptop then sends BRIGHTNESS, the app goes
   from `disconnected` to `sleeping`, and content mode is forced back to PG.
4. Link DOWN when no valid packet arrives for 6 s, or when the port errors (cable pulled). The app goes to
   `disconnected`, speech is cut and the mic is closed. With a timeout the port stays open and PINGs continue,
   so the link comes back by itself. With a port error the laptop retries opening the port every second.

While the link is DOWN the laptop drops FACE, MOUTH and POWER packets instead of queueing them, because an old
face would be wrong by the time the device is back. The app resends the current face and power state on link UP.

## Rates

- MOUTH at most 30 per second (the lip sync timeline is 30 fps).
- FACE only when a face changes.
- The firmware must answer PING within 100 ms. Keep the PONG path out of anything that blocks on the radio.

## Not covered here

Audio is not on this port. The base ESP32-S3 is also a USB sound card, and the laptop plays speech and records the
mic through the normal Windows audio devices.
