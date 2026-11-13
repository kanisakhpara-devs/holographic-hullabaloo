// Shared packet format: laptop <-> base (USB serial) and base <-> rotor (ESP-NOW).
// Every message is a full state, not a delta, so a lost packet never leaves the face stuck.
#pragma once
#include <stdint.h>

#define PKT_MAGIC   0xFA   // first byte of every packet ("Fallen")
#define PKT_VERSION 1

enum PacketType : uint8_t {
  PKT_STATE     = 1,  // base -> rotor: what the face should show
  PKT_HEARTBEAT = 2,  // base -> rotor: 5 Hz "I'm alive"
  PKT_STATUS    = 3,  // rotor -> base: battery, charging, spin rate
};

enum Mode : uint8_t { MODE_OFF = 0, MODE_SLEEP = 1, MODE_IDLE = 2, MODE_TALK = 3 };

enum Emotion : uint8_t {
  EMO_NEUTRAL = 0, EMO_HAPPY, EMO_SMIRK, EMO_ANNOYED, EMO_SURPRISED, EMO_THINKING, EMO_SLEEPING
};

#pragma pack(push, 1)
struct PacketHeader {
  uint8_t magic;     // PKT_MAGIC
  uint8_t version;   // PKT_VERSION
  uint8_t type;      // PacketType
  uint8_t seq;       // increments every packet, wraps at 255
};

struct StatePacket {   // PKT_STATE
  PacketHeader hdr;
  uint8_t mode;        // Mode
  uint8_t emotion;     // Emotion
  uint8_t mouth;       // 0 (closed) to 4 (wide open), from TTS loudness
  int8_t  look;        // head turn in columns, negative = left
  uint8_t brightness;  // 0 to 255, firmware still enforces the LED current cap
  uint8_t crc;         // CRC-8 of everything before this byte
};

struct StatusPacket {  // PKT_STATUS
  PacketHeader hdr;
  uint16_t battery_mv;
  uint8_t  flags;      // bit0 = power good, bit1 = charging
  uint16_t rev_us;     // last measured spin time in microseconds (40000 = 25 rev/s)
  uint8_t  crc;
};
#pragma pack(pop)

// CRC-8 (polynomial 0x07). Same function on all three devices.
static inline uint8_t crc8(const uint8_t* data, uint32_t len) {
  uint8_t crc = 0;
  for (uint32_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}
