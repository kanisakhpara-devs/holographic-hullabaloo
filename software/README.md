# Hullabaloo companion app (browser version)

The laptop side of Holographic Hullabaloo: listens to you, thinks with Gemma 3 4B running locally,
talks back with Kokoro, and tells the device which face and mouth shape to show. The UI runs in Chrome.

## Run it (Windows)
1. Install Python 3.11 and Ollama, then `ollama pull gemma3:4b`.
2. Double click `software\SETUP.cmd` once. It makes `software\.venv` and installs everything.
3. Double click `software\DEV.cmd`. Chrome opens http://localhost:5000. Keep the black window open.
   `software\DEV_MOCK.cmd` does the same with fake models (no GPU, no Ollama), handy for UI work.
4. Hold Ctrl+Space anywhere to talk, or use the Hold to talk button. The Shut down button in More stops everything.

Whisper, Kokoro and wake word models download on first use into %APPDATA%\HolographicHullabaloo.
Settings, memory and logs live there too, not in the repo.

## Folders
- `companion/` Python backend (FastAPI + WebSocket). `server.py` is the entry point.
- `ui/` the browser UI (plain HTML, CSS, JS). `ui/assets/face/face_sheet.png` is the pixel face.
- `tools/face/make_face.py` rebuilds the face sheet from the turnaround art.
- `tests/` pytest suite, mostly mock models and a fake serial port: `software\.venv\Scripts\python.exe -m pytest software\tests`
- `dev.py` the browser dev runner that DEV.cmd starts.
- Device wire protocol: `docs/PROTOCOL.md`. Wake word notes: `docs/WAKE_WORD.md`.

Built with heavy AI help (Claude); see the AI usage section of the main README.

## Backend reference

    pip install -r requirements.txt
    python -m companion.server --mock        # fake models + simulated device, no GPU needed
    python -m companion.server --port COM3   # real models (Whisper/Gemma/Kokoro) + base ESP32
    python -m pytest tests                   # 102 tests (mock models, fake serial, Playwright UI)

Server: http://127.0.0.1:8765  (UI connects to ws://127.0.0.1:8765/ws)

## States (design one mockup per state)
sleeping, waking, listening, thinking, speaking, interrupted, disconnected
Flow: sleeping -> waking -> listening -> thinking -> speaking -> listening ... -> sleeping (30 s idle).
Mic is ignored in thinking/speaking. Button in thinking/speaking = interrupt.

## Emotions (12)  face preview shows one of these
neutral happy smug angry surprised sad confused sleepy bored suspicious laughing eyeroll
Mouth shapes (6): closed ah oh ee oo fv

## Screens and the data each needs
1 Live status: state, face emotion, mouth, device_connected, last say text.
2 Transcript: transcript events + GET /api/transcript, button to wipe (POST /api/transcript/wipe).
3 Persona + settings: persona, content (pg/unfiltered, UI only), privacy_mode (debug/faire),
  proximity_wake, wake_word, idle_timeout_s, tts_speed_scale. Also lists people + facts remembered.
4 Diagnostics: link status, simulate buttons (near, far, press, unplug, plug), last 50 device packets.

## WebSocket: server -> UI (JSON)
snapshot {state, face, settings, people, facts, emotions, device_connected}   (sent on connect)
state {state, prev}   face {emotion}   mouth {viseme}
say {emotion, text, duration}   transcript {role, text}   interrupted {said_so_far}
wake {source}   mic_dropped {state, count}   memory {kind: person|fact, value}   settings {settings}
transcript also carries emotions [..] for role assistant.
NEW (phase 2): latency {ts, source, stt_ms, llm_first_sentence_ms, tts_first_chunk_ms, total_ms}
               llm_token {text}  (raw model tokens, for an optional live "thinking" view; may contain tags)
               device_link {connected}
snapshot also has personas [..] and diagnostics {latencies[20], counters{..}, last_interrupt_ms}.

## WebSocket: UI -> server
JSON: {type:"text", text} | {type:"button"} | {type:"wake"} | {type:"sleep"}
      {type:"settings", patch:{...}} | {type:"sim", what:"near|far|press|unplug|plug"}
Binary frame: one finished utterance, PCM16 16 kHz mono (push-to-talk release).

## Privacy
debug: transcripts saved, auto-deleted after 24 h. faire: switching wipes transcripts + summary,
keeps only names + facts. Device boots PG every time; unfiltered only from the UI.

## Wire packet to the device (the faces live on the rotor, laptop sends ids only)
[0xA5, cmd, a, b, (cmd+a+b)&0xFF]  cmd 1 FACE(emotion idx) 2 MOUTH(viseme idx) 3 POWER 4 PING

## Phase 5 and 6 additions
REST (all need the X-Token header):
  GET  /api/device/status        POST /api/device/reconnect       POST /api/device/test_emotion {emotion}
  GET  /api/device/packets?n=    POST /api/device/selftest (409 if busy or not connected)   POST /api/device/selftest/stop
  GET  /api/prompt               POST /api/audio/calibrate        GET /api/diagnostics.zip
  GET  /api/setup/status         POST /api/setup/ollama_start     POST /api/setup/pull (SSE, data: {json})
  POST /api/setup/done           POST /api/setup/reset            GET /api/health (adds version, log_path, privacy_mode)
WS server to UI: device_link {connected, device}  device_rotor {ok}  device_brightness_ack  selftest {step,total,what,name,finished,completed}  mic_test {text, stt_ms}
WS UI to server: {type:"reconnect"}  {type:"mic_test", on}
Wire protocol: ../docs/PROTOCOL.md. UI tests: `python -m pytest tests/test_ui_smoke.py` (needs playwright and Chrome, skips without them).
