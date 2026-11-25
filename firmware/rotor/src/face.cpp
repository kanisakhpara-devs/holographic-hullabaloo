// Face renderer. See face.h for what it does and docs/PROTOCOL.md for the emotion and mouth order.
#include "face.h"
#include "config.h"
#include "packet.h"
#include "framebuffer.h"
#include "face_data.h"
#include <esp_random.h>

static_assert(FACE_ROWS == ROWS, "rebake_led.py rows must match config.h ROWS");
static_assert(FACE_EMOTIONS == EMO_COUNT, "faces.bin emotions must match packet.h Emotion");
static_assert(FACE_MOUTHS == VIS_COUNT + 1, "faces.bin needs the 6 visemes plus a blink frame");
static_assert(FACE_FIRST_COL + FACE_NCOLS <= COLUMNS_PER_REV, "face columns run past the end of the cylinder");

// Made by board_build.embed_files in platformio.ini (the path with / and . turned into _).
extern const uint8_t faces_start[] asm("_binary_data_faces_bin_start");
extern const uint8_t faces_end[]   asm("_binary_data_faces_bin_end");
extern const uint8_t back_start[]  asm("_binary_data_base_back_bin_start");
extern const uint8_t back_end[]    asm("_binary_data_base_back_bin_end");

static const uint32_t FRAME_BYTES = FACE_NCOLS * FACE_ROWS;
static const uint8_t  BLINK_FRAME = VIS_COUNT;        // 7th frame of each emotion
static const uint8_t  DEFAULT_BRIGHTNESS = 160;       // used until the base sends one

// ---- state from the radio (written on core 0, read on core 1) ----
struct RemoteState { uint8_t mode, emotion, mouth; int8_t look; uint8_t brightness; };
static portMUX_TYPE remote_lock = portMUX_INITIALIZER_UNLOCKED;
static RemoteState remote = {MODE_IDLE, EMO_NEUTRAL, VIS_CLOSED, 0, DEFAULT_BRIGHTNESS};
static volatile uint32_t remote_ms = 0;
static volatile bool have_remote = false;

// ---- local idle state machine (core 1 only) ----
static bool data_ok = false;
static uint32_t last_activity_ms = 0;
static uint8_t prev_mode = 0xFF, prev_emotion = 0xFF;
static uint32_t next_blink_ms = 0, blink_until_ms = 0;
static uint32_t next_glance_ms = 0, glance_until_ms = 0;
static int8_t glance_cols = 0;

// What is in the framebuffer right now, so we only redraw when something changes.
struct Drawn { bool dark; uint8_t frame; int16_t look; uint8_t brightness; };
static Drawn drawn = {true, 0xFF, 0, 0};
static bool drawn_valid = false;

static uint32_t rand_between(uint32_t lo, uint32_t hi) { return lo + esp_random() % (hi - lo + 1); }

bool face_data_ok() { return data_ok; }

void face_begin() {
  uint32_t faces_len = faces_end - faces_start;
  uint32_t back_len = back_end - back_start;
  uint32_t want_faces = (uint32_t)FACE_EMOTIONS * FACE_MOUTHS * FRAME_BYTES;
  uint32_t want_back = (uint32_t)COLUMNS_PER_REV * ROWS;
  data_ok = (faces_len == want_faces) && (back_len == want_back);
  if (!data_ok) {
    // Usually means faces.bin was rebaked with different sizes and face_data.h wasn't copied over with it.
    Serial.printf("face: bad data, faces.bin %u (want %u), base_back.bin %u (want %u)\n",
                  faces_len, want_faces, back_len, want_back);
  }
  uint32_t now = millis();
  last_activity_ms = now;
  next_blink_ms = now + rand_between(BLINK_MIN_MS, BLINK_MAX_MS);
  next_glance_ms = now + rand_between(GLANCE_MIN_MS, GLANCE_MAX_MS);
}

void face_set_state(uint8_t mode, uint8_t emotion, uint8_t mouth, int8_t look, uint8_t brightness) {
  if (mode > MODE_TALK) mode = MODE_IDLE;
  if (emotion >= EMO_COUNT) emotion = EMO_NEUTRAL;
  if (mouth >= VIS_COUNT) mouth = VIS_CLOSED;
  portENTER_CRITICAL(&remote_lock);
  remote = {mode, emotion, mouth, look, brightness};
  portEXIT_CRITICAL(&remote_lock);
  remote_ms = millis();
  have_remote = true;
}

// Copy one frame into the back buffer, turned by `look` columns, with palette lookup and brightness.
static void render(uint8_t frame, int16_t look, uint8_t brightness) {
  fb_frame_t& fb = fb_back();
  const uint8_t* face = faces_start + (uint32_t)frame * FRAME_BYTES;
  for (int c = 0; c < COLUMNS_PER_REV; c++) {
    int dst = ((c + look) % COLUMNS_PER_REV + COLUMNS_PER_REV) % COLUMNS_PER_REV;
    int fc = c - FACE_FIRST_COL;
    const uint8_t* src = (fc >= 0 && fc < FACE_NCOLS) ? face + fc * FACE_ROWS : back_start + c * ROWS;
    for (int r = 0; r < ROWS; r++) {
      const uint8_t* p = face_palette[src[r]];
      for (int k = 0; k < 3; k++) fb[dst][r][k] = (uint8_t)((p[k] * brightness + 127) / 255);
    }
  }
}

void face_update(uint32_t now) {
  // 1. Pick the state: the base's, or local idle if the radio has gone quiet.
  RemoteState s;
  bool radio_fresh = have_remote && (now - remote_ms) <= HEARTBEAT_TIMEOUT_MS;
  if (radio_fresh) {
    portENTER_CRITICAL(&remote_lock);
    s = remote;
    portEXIT_CRITICAL(&remote_lock);
  } else {
    uint8_t b = have_remote ? remote.brightness : DEFAULT_BRIGHTNESS;   // keep the last brightness cap
    s = {MODE_IDLE, EMO_NEUTRAL, VIS_CLOSED, 0, b};
  }

  // 2. Inactivity: talking, or any change of mode or face, counts as activity.
  if (s.mode == MODE_TALK || s.mode != prev_mode || s.emotion != prev_emotion) last_activity_ms = now;
  prev_mode = s.mode;
  prev_emotion = s.emotion;
  uint32_t idle_for = now - last_activity_ms;

  bool dark = !data_ok || s.mode == MODE_OFF || idle_for >= DARK_AFTER_MS || s.brightness == 0;
  uint8_t emotion = s.emotion, mouth = s.mouth;
  if (s.mode == MODE_SLEEP || (s.mode == MODE_IDLE && idle_for >= SLEEP_AFTER_MS)) {
    emotion = EMO_SLEEPY;
    mouth = VIS_CLOSED;
  }

  // 3. Blink: only drawn while the mouth is closed, because the blink frame has a closed mouth.
  if ((int32_t)(now - next_blink_ms) >= 0) {
    blink_until_ms = now + BLINK_LEN_MS;
    next_blink_ms = now + rand_between(BLINK_MIN_MS, BLINK_MAX_MS);
  }
  bool blinking = (int32_t)(blink_until_ms - now) > 0 && mouth == VIS_CLOSED;

  // 4. Glance: small random head turn, idle mode only (not while talking or sleeping).
  if (s.mode == MODE_IDLE && emotion != EMO_SLEEPY) {
    if ((int32_t)(now - next_glance_ms) >= 0) {
      int8_t d = (int8_t)rand_between(1, GLANCE_MAX_COLS);
      glance_cols = (esp_random() & 1) ? d : -d;
      glance_until_ms = now + rand_between(GLANCE_HOLD_MIN_MS, GLANCE_HOLD_MAX_MS);
      next_glance_ms = now + rand_between(GLANCE_MIN_MS, GLANCE_MAX_MS);
    }
    if ((int32_t)(glance_until_ms - now) <= 0) glance_cols = 0;
  } else {
    glance_cols = 0;
  }

  // 5. Redraw only when something visible changed, and only when the last frame has been swapped in.
  Drawn want = {dark, (uint8_t)(emotion * FACE_MOUTHS + (blinking ? BLINK_FRAME : mouth)),
                (int16_t)(s.look + glance_cols), s.brightness};
  bool same = drawn_valid && want.dark == drawn.dark &&
              (want.dark || (want.frame == drawn.frame && want.look == drawn.look &&
                             want.brightness == drawn.brightness));
  if (same || fb_swap_pending()) return;

  if (want.dark) memset(&fb_back(), 0, sizeof(fb_frame_t));
  else render(want.frame, want.look, want.brightness);
  fb_commit();
  drawn = want;
  drawn_valid = true;
}
