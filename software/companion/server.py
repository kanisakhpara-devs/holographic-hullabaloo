"""FastAPI server. The UI talks to this over one WebSocket (/ws) plus REST routes.

Security: binds to 127.0.0.1 only. When a launch token is set (Tauri always sets one),
every /api call needs header `X-Token: <token>` and the WebSocket needs `?token=<token>`.
CORS allows only the Tauri webview origins and localhost, never a wildcard.

Run (mock models, simulated device):   python -m companion.server --mock
Run (real models):                     python -m companion.server --port 8765 --token abc
"""
import argparse, asyncio, io, json, logging, os, secrets, time, zipfile
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from .engine import Engine
from .memory import Memory
from .device import SimDevice, SerialDevice
from .emotions import SpeechMap, EMOTIONS
from .persona import PersonaStore, CUSTOM
from . import diag, setup_api

VERSION = "0.1.0"

log = logging.getLogger("hullabaloo.server")

ALLOWED_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   "http://127.0.0.1", "http://localhost"]


def setup_logging(log_dir, level="info"):
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("hullabaloo")
    root.setLevel(level.upper())
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        h = RotatingFileHandler(os.path.join(log_dir, "backend.log"), maxBytes=2 * 2**20, backupCount=4,
                                encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
    return os.path.join(log_dir, "backend.log")


def create_app(stt, llm, tts, device, db="companion.db", realtime=1.0, token=None, audio=None,
               data_dir=None, on_ready=None, extract_facts=True, device_factory=None,
               ui_dir=None, dev=False) -> FastAPI:
    """on_ready(engine, app_state) is called inside the loop after the engine exists
    (the real runtime uses it to start the mic and register setting hooks)."""
    clients = set()
    state = {"log_path": None}

    def default_factory(mode, port, cap):
        return SerialDevice(port=port, brightness_cap=cap) if mode == "serial" else SimDevice()
    make_device = device_factory or default_factory

    def emit(ev):
        loop = state.get("loop")
        if loop:
            loop.call_soon_threadsafe(lambda: [asyncio.ensure_future(_send(w, ev)) for w in list(clients)])

    async def _send(ws, ev):
        try:
            await ws.send_text(json.dumps(ev))
        except Exception:
            clients.discard(ws)

    @asynccontextmanager
    async def life(app):
        state["loop"] = asyncio.get_running_loop()
        speech = SpeechMap(os.path.join(data_dir, "emotion_speech.json") if data_dir else None)
        personas = PersonaStore(os.path.join(data_dir, "personas") if data_dir else None)
        eng = Engine(stt, llm, tts, device, Memory(db), emit=emit, realtime=realtime, audio=audio,
                     speech_map=speech, personas=personas, extract_facts=extract_facts,
                     settings_export=os.path.join(data_dir, "settings.json") if data_dir else None)
        eng.attach_loop()
        state["engine"] = eng
        state["setup_done"] = bool(data_dir and os.path.exists(os.path.join(data_dir, "setup_done")))

        def device_hook(applied):
            if {"device_mode", "serial_port"} & set(applied):
                mode, port = eng.settings["device_mode"], eng.settings["serial_port"]
                if mode == "sim" and isinstance(eng.dev, SimDevice):
                    return                                 # nothing to switch
                if mode == "serial" and isinstance(eng.dev, SerialDevice) and "device_mode" not in applied:
                    eng.dev.set_port(port)                 # only the port changed: reopen, keep the object
                else:
                    try:
                        eng.swap_device(make_device(mode, port, eng.settings["device_brightness_cap"]))
                    except Exception as ex:
                        log.exception("could not switch device")
                        emit({"type": "error", "where": "device", "message": str(ex)})
        eng.setting_hooks.append(device_hook)
        if on_ready:
            on_ready(eng, state)
        task = asyncio.create_task(eng.idle_loop())
        yield
        task.cancel()
        try:
            state["engine"].dev.close()
        except Exception:
            pass
        for c in state.get("closers", []):
            try:
                c()
            except Exception:
                pass

    app = FastAPI(lifespan=life, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "PUT", "POST", "DELETE"],
                       allow_headers=["X-Token", "Content-Type"], allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+")

    @app.middleware("http")
    async def check_token(request: Request, call_next):
        if token and request.url.path.startswith("/api") and request.method != "OPTIONS":
            if not secrets.compare_digest(request.headers.get("x-token", ""), token):
                return JSONResponse({"error": "bad or missing token"}, status_code=401)
        return await call_next(request)

    def E() -> Engine:
        return state["engine"]

    # ---- status / usage / transcript
    @app.get("/api/snapshot")
    def snapshot():
        return E().snapshot()

    @app.get("/api/usage")
    def usage(days: int = 7):
        days = max(1, min(days, 90))
        cum, hours = E().mem.usage(days)
        return {"days": days, "cumulative": cum, "hours": hours, "daily": E().mem.daily(days)}

    @app.get("/api/transcript")
    def transcript():
        return [{"ts": t, "role": r, "emotion": em, "text": x} for t, r, em, x in E().mem.transcript()]

    @app.get("/api/transcript/info")
    def transcript_info():
        e = E()
        return {"privacy_mode": e.settings["privacy_mode"], "hours_left": e.mem.retention_hours_left(),
                "ttl_hours": 24, "count": len(e.mem.transcript(limit=100000))}

    @app.post("/api/transcript/wipe")
    def wipe():
        E().mem.wipe_transcripts()
        return {"ok": True}

    # ---- memory manager
    @app.get("/api/memory")
    def memory():
        m = E().mem
        return {"people": m.people_full(), "facts": m.facts_full(), "summary": m.summary()
                if E().settings["privacy_mode"] == "debug" else ""}

    @app.delete("/api/memory/person/{name}")
    def del_person(name: str):
        e = E()
        n = e.mem.delete_person(name)
        if e.speaker == name:
            e.speaker = None
        e.emit({"type": "memory", "kind": "deleted_person", "value": name})
        return {"ok": n > 0}

    @app.delete("/api/memory/fact/{fact_id}")
    def del_fact(fact_id: int):
        n = E().mem.delete_fact(fact_id)
        E().emit({"type": "memory", "kind": "deleted_fact", "value": fact_id})
        return {"ok": n > 0}

    @app.post("/api/memory/forget_all")
    async def forget_all(request: Request):
        body = await _json(request)
        if body.get("confirm") is not True:
            raise HTTPException(400, "send {\"confirm\": true}")
        E().mem.forget_all()
        E().speaker = None
        E().emit({"type": "memory", "kind": "forgot_all", "value": None})
        return {"ok": True}

    @app.get("/api/memory/export")
    def export():
        data = json.dumps(E().mem.export_memory(), indent=2)
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=hullabaloo_memory.json"})

    # ---- settings
    @app.get("/api/settings")
    def get_settings():
        e = E()
        return {"settings": dict(e.settings), "schema": e.settings.describe()}

    @app.put("/api/settings")
    async def put_settings(request: Request):
        patch = await _json(request)
        errors = E().set_settings(patch, from_ui=True)
        body = {"settings": dict(E().settings), "errors": errors}
        return JSONResponse(body, status_code=422 if errors else 200)

    # ---- personas, speech map, preview
    @app.get("/api/personas")
    def personas():
        p = E().personas
        return [{"name": n, "text": p.get(n, E().settings["custom_persona_text"]) if n != CUSTOM
                 else E().settings["custom_persona_text"]} for n in p.names()]

    @app.put("/api/personas/{name}")
    async def put_persona(name: str, request: Request):
        body = await _json(request)
        text = str(body.get("text", ""))
        if name == CUSTOM:
            errors = E().set_settings({"custom_persona_text": text}, from_ui=True)
            if errors:
                raise HTTPException(422, errors)
            return {"ok": True}
        try:
            E().personas.save(name, text)
        except ValueError as ex:
            raise HTTPException(422, str(ex))
        return {"ok": True, "names": E().personas.names()}

    @app.get("/api/emotion_map")
    def get_emotion_map():
        return {"map": E().speech.map, "overrides": E().settings["voice_overrides"],
                "state_faces": {s.value: f for s, f in E().state_face.items()}}

    @app.put("/api/emotion_map")
    async def put_emotion_map(request: Request):
        try:
            return {"map": E().speech.update(await _json(request))}
        except (ValueError, KeyError, TypeError) as ex:
            raise HTTPException(422, str(ex))

    @app.post("/api/tts/preview")
    async def tts_preview(request: Request):
        body = await _json(request)
        emo = body.get("emotion", "neutral")
        text = str(body.get("text", "") or "Well, well. Look who it is.")[:200]
        if emo not in EMOTIONS:
            raise HTTPException(422, "unknown emotion")
        ok = await E().preview(text, emo)
        return {"ok": ok}

    # ---- devices, health, logs
    @app.get("/api/devices/audio")
    def audio_devices():
        try:
            from .audio_io import list_devices
            return list_devices()
        except Exception as ex:
            return {"inputs": [], "outputs": [], "error": str(ex)}

    @app.get("/api/devices/serial")
    def serial_devices():
        try:
            from .device import list_serial_ports
            return list_serial_ports()
        except Exception as ex:
            return {"ports": [], "error": str(ex)}

    @app.get("/api/device/status")
    def device_status():
        return E().dev.status()

    @app.get("/api/device/packets")
    def device_packets(n: int = 100):
        return {"packets": E().dev.packets(n)}

    @app.post("/api/device/selftest")
    async def device_selftest():
        e = E()
        if e._selftest_running or e._busy or not e.dev.connected:
            return JSONResponse({"ok": False, "reason": "device not connected or busy"}, status_code=409)
        task = asyncio.ensure_future(e.selftest())
        state["selftest_task"] = task
        return {"ok": True, "steps": 18}

    @app.post("/api/device/selftest/stop")
    def device_selftest_stop():
        E().selftest_stop()
        return {"ok": True}

    @app.post("/api/device/test_emotion")
    async def device_test_emotion(request: Request):
        body = await _json(request)
        emo = body.get("emotion")
        if emo not in EMOTIONS:
            raise HTTPException(422, "unknown emotion")
        if not E().dev.connected:
            raise HTTPException(409, "device not connected")
        E().dev.test_emotion(emo)
        return {"ok": True}

    @app.post("/api/device/reconnect")
    def device_reconnect():
        E().dev.reconnect()
        return {"ok": True}

    # ---- prompt viewer, audio calibration, diagnostics bundle
    @app.get("/api/prompt")
    def prompt():
        return {"prompt": E().system_prompt(), "options": E().llm_options()}

    @app.post("/api/audio/calibrate")
    async def calibrate():
        return {"ok": await E().calibrate_beep()}

    @app.get("/api/diagnostics.zip")
    async def diagnostics_zip():
        """Logs + settings + health numbers. Never the database, so no transcripts, memory or facts."""
        e = E()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            lp = state.get("log_path")
            if lp:
                folder = os.path.dirname(lp)
                for f in sorted(os.listdir(folder)):
                    if f.startswith("backend.log"):
                        z.write(os.path.join(folder, f), "logs/" + f)
            z.writestr("settings.json", json.dumps({k: v for k, v in e.settings.items()
                                                    if k not in ("custom_persona_text", "blocklist")}, indent=2))
            z.writestr("health.json", json.dumps(await health(), indent=2, default=str))
            z.writestr("device.json", json.dumps({"status": e.dev.status(), "packets": e.dev.packets(100)}, indent=2))
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=hullabaloo_diagnostics.zip"})

    # ---- first-run wizard
    @app.get("/api/setup/status")
    async def setup_status():
        e = E()
        url, model = e.settings["ollama_url"], e.settings["llm_model"]
        reachable, names = await asyncio.to_thread(setup_api.ollama_models, url)
        gpu = await asyncio.to_thread(diag.gpu_info)
        mic = state.get("mic_info")
        return {
            "done": bool(state.get("setup_done")),
            "gpu": {**gpu, "cuda": await asyncio.to_thread(diag.cuda_ok),
                    "stt_device": getattr(e.stt, "device", None), "stt_note": getattr(e.stt, "fallback_reason", None)},
            "ollama": {"installed": setup_api.ollama_exe() is not None, "running": reachable, "model": model,
                       "model_present": setup_api.model_present(model, names), "download_url": setup_api.OLLAMA_DOWNLOAD_URL},
            "whisper": {"loaded": type(e.stt).__name__ == "WhisperSTT", "type": type(e.stt).__name__},
            "kokoro": {"loaded": type(e.tts).__name__ == "KokoroTTS", "type": type(e.tts).__name__},
            "mic": mic, "speaker": {"type": type(e.audio).__name__, "device": getattr(e.audio, "device_name", None)},
            "device": e.dev.status()}

    @app.post("/api/setup/ollama_start")
    async def setup_ollama_start():
        ok, msg = await asyncio.to_thread(setup_api.start_ollama)
        return {"ok": ok, "message": msg}

    @app.post("/api/setup/pull")
    async def setup_pull():
        e = E()

        async def gen():
            async for item in setup_api.pull_stream(e.settings["ollama_url"], e.settings["llm_model"]):
                yield "data: " + json.dumps(item) + "\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/setup/done")
    def setup_done():
        state["setup_done"] = True
        if data_dir:
            try:
                open(os.path.join(data_dir, "setup_done"), "w").write("1")
            except OSError:
                pass
        return {"ok": True}

    @app.post("/api/setup/reset")
    def setup_reset():
        state["setup_done"] = False
        if data_dir:
            try:
                os.remove(os.path.join(data_dir, "setup_done"))
            except OSError:
                pass
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        e = E()
        ollama = None
        if hasattr(e.llm, "is_up"):
            ollama = await asyncio.to_thread(e.llm.is_up)
        return {"stt": {"type": type(e.stt).__name__, "device": getattr(e.stt, "device", None),
                        "note": getattr(e.stt, "fallback_reason", None)},
                "llm": {"type": type(e.llm).__name__, "model": getattr(e.llm, "model", None), "reachable": ollama},
                "tts": {"type": type(e.tts).__name__, "device": getattr(e.tts, "device", None),
                        "timestamps": getattr(e.tts, "timestamps_seen", None)},
                "audio_out": {"type": type(e.audio).__name__, "device": getattr(e.audio, "device_name", None),
                              "latency_ms": round(getattr(e.audio, "output_latency_s", 0) * 1000)},
                "mic": state.get("mic_info"), "gpu": await asyncio.to_thread(diag.gpu_info),
                "device_connected": e.dev.connected, "version": VERSION, "log_path": state.get("log_path"),
                "privacy_mode": e.settings["privacy_mode"], **e.diagnostics()}

    @app.get("/api/logs")
    def logs(lines: int = 200):
        path = state.get("log_path")
        if not path or not os.path.exists(path):
            return {"lines": []}
        with open(path, encoding="utf-8", errors="replace") as f:
            return {"path": path, "lines": f.readlines()[-max(1, min(lines, 2000)):]}

    async def _json(request):
        try:
            d = await request.json()
        except Exception:
            raise HTTPException(400, "body must be JSON")
        if not isinstance(d, dict):
            raise HTTPException(400, "body must be a JSON object")
        return d

    # ---- websocket
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        # browsers don't apply CORS to WebSockets, so any open web page could reach this
        # socket; refuse every origin except our own page (localhost) and the Tauri shell
        origin = sock.headers.get("origin")
        if origin and not origin_ok(origin):
            await sock.close(code=4403)
            return
        if token and not secrets.compare_digest(sock.query_params.get("token", ""), token):
            await sock.close(code=4401)
            return
        await sock.accept()
        clients.add(sock)
        eng: Engine = state["engine"]
        await sock.send_text(json.dumps({"type": "snapshot", **eng.snapshot()}))
        try:
            while True:
                msg = await sock.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:     # raw utterance audio (PCM16 16k mono)
                    asyncio.create_task(eng.on_audio(msg["bytes"]))
                    continue
                try:
                    d = json.loads(msg.get("text") or "{}")
                except ValueError:
                    continue
                t = d.get("type")
                if t == "text":
                    asyncio.create_task(eng.on_text(str(d.get("text", ""))[:1000]))
                elif t == "button":
                    eng.button()
                elif t == "wake":
                    eng.wake("ui")
                elif t == "sleep":
                    eng.sleep()
                elif t == "reconnect":
                    eng.dev.reconnect()
                elif t == "mic_test":
                    eng.mic_test = bool(d.get("on"))
                    if state.get("mic") and state["mic"].on_ptt_change:
                        state["mic"].on_ptt_change()      # open the mic for the test, close after
                elif t == "settings":
                    errors = eng.set_settings(d.get("patch", {}), from_ui=True)
                    if errors:
                        await sock.send_text(json.dumps({"type": "error", "where": "settings", "errors": errors}))
                elif t in ("ptt_down", "ptt_up") and state.get("mic"):
                    getattr(state["mic"], t)()
                elif t == "sim" and isinstance(eng.dev, SimDevice):
                    dev = eng.dev
                    {"near": lambda: dev.sim_proximity(True), "far": lambda: dev.sim_proximity(False),
                     "press": dev.sim_button, "unplug": lambda: dev.sim_disconnect(True),
                     "plug": lambda: dev.sim_disconnect(False)}.get(d.get("what"), lambda: None)()
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(sock)

    # ---- Shut down button: unload the model from the GPU, kill the old app, stop the dev runner and this backend
    @app.post("/api/shutdown")
    async def shutdown(request: Request):
        if request.headers.get("origin") and not origin_ok(request.headers["origin"]):
            raise HTTPException(403, "bad origin")
        d = await request.json()
        if not d.get("confirm"):
            raise HTTPException(400, "send {\"confirm\": true}")
        from . import power
        eng = state["engine"]
        try:
            eng.button()                                   # stop talking right now
        except Exception:
            pass
        for c in state.get("closers", []):                 # mic off
            try:
                c()
            except Exception:
                pass
        res = await asyncio.to_thread(power.shutdown_everything, eng.settings["ollama_url"], not d.get("dry_run"))
        if not d.get("dry_run"):
            power.stop_self_and_runner()
        return {"ok": True, **res}

    # ---- push-to-talk from the dev runner's global hotkey (the browser only sees keys when focused)
    @app.post("/api/ptt")
    async def ptt(request: Request):
        if request.headers.get("origin") and not origin_ok(request.headers["origin"]):
            raise HTTPException(403, "bad origin")
        d = await request.json()
        mic = state.get("mic")
        if mic:
            (mic.ptt_down if d.get("down") else mic.ptt_up)()
        return {"ok": bool(mic)}

    if dev and ui_dir:
        @app.get("/api/dev/stamp")
        async def dev_stamp():
            """newest mtime of any UI file: the page polls this and reloads itself on change"""
            newest = 0.0
            for root, _, files in os.walk(ui_dir):
                for f in files:
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                    except OSError:
                        pass
            return {"stamp": newest}

    if ui_dir and os.path.isdir(ui_dir):
        from fastapi.staticfiles import StaticFiles

        class NoCache(StaticFiles):
            async def get_response(self, path, scope):
                r = await super().get_response(path, scope)
                r.headers["Cache-Control"] = "no-store"     # edits show up on a plain reload
                return r
        app.mount("/", NoCache(directory=ui_dir, html=True), name="ui")

    app.state.hh = state
    return app


import re as _re
_ORIGIN_RE = _re.compile(r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|tauri://localhost|https?://tauri\.localhost)$")


def origin_ok(origin):
    return bool(_ORIGIN_RE.match(origin or ""))


# ---------------------------------------------------------------- real runtime
def real_runtime(data_dir, mock=False):
    """Build adapters from saved settings and return (stt, llm, tts, audio, on_ready)."""
    from .memory import Memory as _M
    from .settings import Settings
    s = Settings(_M(os.path.join(data_dir, "companion.db")))
    if mock:
        from .adapters.mock import MockSTT, MockLLM, MockTTS
        stt, llm, tts = MockSTT(), MockLLM(), MockTTS()
    else:
        from .adapters.real import WhisperSTT, OllamaLLM, KokoroTTS
        from .adapters.mock import MockSTT, MockTTS
        models = os.path.join(data_dir, "models")
        try:
            stt = WhisperSTT(s["stt_model"], device=s["stt_device"], download_root=os.path.join(models, "whisper"))
        except Exception:
            log.exception("Whisper failed to load; typed input only")
            stt = MockSTT()
        llm = OllamaLLM(s["llm_model"], s["ollama_url"])
        try:
            tts = KokoroTTS(device=s["tts_device"])
        except Exception:
            log.exception("Kokoro failed to load; silent placeholder voice")
            tts = MockTTS()
    audio = None
    try:
        from .audio_io import SoundDeviceOut
        audio = SoundDeviceOut(s["speaker_device"], s["volume"], s["mute"])
    except Exception as ex:
        log.warning("no speaker output: %s", ex)

    def on_ready(eng, state):
        from .listen import MicPipeline, WakeWord, find_custom, phrase_of
        pipe = MicPipeline(eng, noise_gate=eng.settings["noise_gate"])
        pipe.attach_loop()
        state["mic"] = pipe

        def wake_status(msg, ok=False):
            eng.wake_status = {"ok": ok, "message": msg, "phrase": pipe.wake.phrase if pipe.wake else phrase_of(find_custom())}
            eng.emit({"type": "wake_status", **eng.wake_status})

        def ensure_wake():
            """Build the wake word model when wake mode is on. The first time this downloads a few MB,
            so it runs in a thread and reports progress through wake_status."""
            if eng.settings["mic_mode"] != "wake":
                return
            if pipe.wake:
                return wake_status("ready", True)
            if state.get("wake_loading"):
                return
            state["wake_loading"] = True
            wake_status("loading the wake word model (first time: downloading a few MB)...")
            loop = asyncio.get_running_loop()

            def build():
                try:
                    w = WakeWord(sensitivity=eng.settings["wake_word_sensitivity"])
                    def done():
                        pipe.wake = w
                        state["wake_loading"] = False
                        wake_status("ready", True)
                        log.info("wake word ready: %s", w.phrase)
                    loop.call_soon_threadsafe(done)
                except Exception as ex:
                    log.warning("wake word unavailable: %s", ex)
                    def fail():
                        state["wake_loading"] = False
                        wake_status("error: " + str(ex)[:200] + " (needs internet the first time)")
                    loop.call_soon_threadsafe(fail)
            import threading
            threading.Thread(target=build, daemon=True).start()

        def close_mic():
            old = state.pop("mic_stream", None)
            if old:
                try:
                    old.close()
                except Exception:
                    pass
            state["mic_info"] = {"open": False, "vad": pipe.det.vad.name}
            eng.emit({"type": "mic_stream", "open": False})

        def open_mic():
            close_mic()
            try:
                from .audio_io import MicIn
                t_open = time.monotonic()
                m = MicIn(pipe.on_frame_threadsafe, eng.settings["mic_device"], eng.settings["mic_gain"])
                state["mic_stream"], state["mic_info"] = m, {"open": True, "device": m.device_name, "vad": pipe.det.vad.name}
                log.info("mic opened in %d ms (%s)", (time.monotonic() - t_open) * 1000, m.device_name)
                eng.emit({"type": "mic_stream", "open": True})
            except Exception as ex:
                state["mic_info"] = {"error": str(ex)}
                eng.emit({"type": "error", "where": "mic", "message": str(ex)})

        def sync_mic(ptt_held=None):
            """The OS mic is open only in wake mode, or while push-to-talk is held."""
            held = pipe._ptt if ptt_held is None else ptt_held
            want = (eng.settings["mic_mode"] == "wake" or (held and eng.settings["mic_mode"] != "off")
                    or getattr(eng, "mic_test", False))
            if want and not state.get("mic_stream"):
                open_mic()
            elif not want and state.get("mic_stream"):
                close_mic()
        pipe.on_ptt_change = sync_mic
        eng.wake_status = {"ok": False, "message": "off", "phrase": phrase_of(find_custom())}
        ensure_wake()
        sync_mic(False)

        def hook(applied):
            if eng.audio is not None and hasattr(eng.audio, "volume"):
                if "volume" in applied:
                    eng.audio.volume = applied["volume"]
                if "mute" in applied:
                    eng.audio.mute = applied["mute"]
                if "speaker_device" in applied:
                    eng.audio.open(applied["speaker_device"])
            if {"mic_device", "mic_gain"} & set(applied) and state.get("mic_stream"):
                open_mic()
            if "noise_gate" in applied:
                pipe.noise_gate = applied["noise_gate"]
            if "vad_silence_ms" in applied:
                pipe.det.silence_frames = max(1, applied["vad_silence_ms"] // 30)
            if "wake_word_sensitivity" in applied and pipe.wake:
                pipe.wake.sensitivity = applied["wake_word_sensitivity"]
            if "mic_mode" in applied:
                pipe.armed = False
                if eng.settings["mic_mode"] != "wake":
                    eng.wake_status = {**eng.wake_status, "ok": False, "message": "off"}
                    eng.emit({"type": "wake_status", **eng.wake_status})
                ensure_wake()
                sync_mic()
            if {"llm_model", "ollama_url"} & set(applied) and hasattr(eng.llm, "keep_alive"):
                from .adapters.real import OllamaLLM
                eng.llm = OllamaLLM(eng.settings["llm_model"], eng.settings["ollama_url"])
        eng.setting_hooks.append(hook)
        state.setdefault("closers", []).append(lambda: state.get("mic_stream") and state["mic_stream"].close())
        if hasattr(eng.llm, "warm"):
            asyncio.ensure_future(eng._safe_warm())     # first token fast: load the model now

    return stt, llm, tts, audio, on_ready


def main(argv=None):
    import uvicorn
    from . import paths
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="fake models (no GPU needed)")
    ap.add_argument("--port", type=int, default=8765, help="TCP port on 127.0.0.1 (0 = pick a free one)")
    ap.add_argument("--token", default=os.environ.get("HH_TOKEN"), help="launch token required on every call")
    ap.add_argument("--serial", default=None, help="force the serial device on this port, e.g. COM3 (else the saved device_mode setting decides)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--ui", default=None, help="serve the UI folder at / (browser mode)")
    ap.add_argument("--dev", action="store_true", help="browser dev mode: UI auto-reload, extra log file")
    ap.add_argument("--dev-log", default=None, help="also write the log here (dev mode)")
    a = ap.parse_args(argv)
    if a.data_dir:
        os.environ["HH_DATA_DIR"] = a.data_dir
    dd = paths.data_dir()
    log_path = setup_logging(os.path.join(dd, "logs"))
    if a.dev_log:
        h = logging.FileHandler(a.dev_log, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("hullabaloo").addHandler(h)
    if a.dev and not a.mock:
        from .memory import Memory as _M0
        from .settings import Settings as _S0
        s0 = _S0(_M0(os.path.join(dd, "companion.db")), os.path.join(dd, "settings.json"))
        if s0["device_mode"] == "sim":                 # he chose: dev server defaults to the real device
            s0.update_from({"device_mode": "serial"})
            log.info("dev mode: switched saved device_mode sim -> serial")
    stt, llm, tts, audio, on_ready = real_runtime(dd, mock=a.mock)
    from .memory import Memory as _M
    from .settings import Settings as _S
    saved = _S(_M(os.path.join(dd, "companion.db")))
    if a.serial:
        dev = SerialDevice(a.serial, brightness_cap=saved["device_brightness_cap"])
    elif a.mock:
        dev = SimDevice()                  # --mock is the no-hardware developer mode
    elif saved["device_mode"] == "serial":
        dev = SerialDevice(saved["serial_port"], brightness_cap=saved["device_brightness_cap"])
    else:
        dev = SimDevice()
    app = create_app(stt, llm, tts, dev, os.path.join(dd, "companion.db"), token=a.token, audio=audio,
                     data_dir=dd, on_ready=on_ready, ui_dir=a.ui, dev=a.dev)
    app.state.hh["log_path"] = log_path
    log.info("backend %s listening on http://localhost:%s (dev=%s)", VERSION, a.port, a.dev)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
