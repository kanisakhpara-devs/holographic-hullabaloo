"""Mic frames -> utterances. VAD (silero onnx, else webrtcvad, else energy), 300 ms pre-roll,
end of speech on silence, push-to-talk, mic gating, level meter, openWakeWord wake word.

Mic modes (setting mic_mode): off = no stream at all; hotkey = the stream is opened only while
push-to-talk is held; wake = stream open, but frames go only to the wake word model until it hears the
wake word, then one utterance is captured.

Mic gating: frames are DROPPED (not queued) whenever the engine is not listening, plus an
echo tail guard of ECHO_TAIL_S after speaking ends so the room echo of the last word is
not heard as the user.
"""
import asyncio, collections, logging, time
import numpy as np

log = logging.getLogger("hullabaloo.listen")

FRAME_BYTES = 480 * 2
PREROLL_FRAMES = 10            # 300 ms
MAX_UTTERANCE_S = 15
ECHO_TAIL_S = 0.3
LEVEL_HZ = 15


def rms_level(frame: bytes) -> float:
    """0..1, roughly dBFS -60..0 mapped linearly."""
    x = np.frombuffer(frame, np.int16).astype(np.float32)
    if not len(x):
        return 0.0
    r = np.sqrt(np.mean(x * x)) / 32768.0
    db = 20 * np.log10(max(r, 1e-6))
    return float(min(1.0, max(0.0, (db + 60) / 60)))


# ---------------------------------------------------------------- VAD backends
class EnergyVAD:
    name = "energy"

    def __init__(self, threshold=0.45):
        self.threshold = threshold

    def is_speech(self, frame):
        return rms_level(frame) > self.threshold


class WebRtcVAD:
    name = "webrtcvad"

    def __init__(self, aggressiveness=2):
        import webrtcvad
        self.v = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame):
        # webrtcvad flags faint noise as speech; require some energy too (about -42 dBFS)
        return rms_level(frame) > 0.3 and self.v.is_speech(frame, 16000)


class SileroVAD:
    """silero-vad wants 512 sample windows at 16 kHz; frames are 480, so we keep a carry buffer."""
    name = "silero"

    def __init__(self, threshold=0.5):
        from silero_vad import load_silero_vad
        self.model = load_silero_vad(onnx=True)
        self.threshold = threshold
        self.carry = np.zeros(0, np.float32)
        self.last = 0.0

    def is_speech(self, frame):
        import torch
        self.carry = np.concatenate([self.carry, np.frombuffer(frame, np.int16).astype(np.float32) / 32768.0])
        while len(self.carry) >= 512:
            w, self.carry = self.carry[:512], self.carry[512:]
            self.last = float(self.model(torch.from_numpy(w.copy()), 16000).item())
        return self.last > self.threshold


def make_vad():
    for cls in (SileroVAD, WebRtcVAD):
        try:
            v = cls()
            log.info("VAD: %s", v.name)
            return v
        except Exception as ex:
            log.warning("VAD %s unavailable: %s", cls.name, ex)
    return EnergyVAD()


# ---------------------------------------------------------------- utterance detector
class UtteranceDetector:
    """feed(frame) -> bytes of a finished utterance, or None."""

    def __init__(self, vad, silence_ms=700, min_speech_ms=240):
        self.vad = vad
        self.silence_frames = max(1, silence_ms // 30)
        self.min_speech_frames = max(1, min_speech_ms // 30)
        self.pre = collections.deque(maxlen=PREROLL_FRAMES)
        self.reset()

    def reset(self):
        self.buf, self.in_speech, self.speech_frames, self.quiet = [], False, 0, 0
        self.ptt = False
        self.pre.clear()

    def ptt_down(self):
        self.reset()
        self.ptt = True
        self.in_speech = True

    def ptt_up(self):
        if not self.ptt:
            return None
        out = b"".join(self.buf)
        self.reset()
        return out or None

    def feed(self, frame: bytes):
        if self.ptt:                               # push-to-talk: no VAD end of speech
            self.buf.append(frame)
            if len(self.buf) * 0.03 > MAX_UTTERANCE_S:
                return self.ptt_up()
            return None
        sp = self.vad.is_speech(frame)
        if not self.in_speech:
            self.pre.append(frame)
            if sp:
                self.speech_frames += 1
                if self.speech_frames >= 3:        # 90 ms of speech starts an utterance
                    self.in_speech = True
                    self.buf = list(self.pre)
                    self.pre.clear()
            else:
                self.speech_frames = 0
            return None
        self.buf.append(frame)
        if sp:
            self.quiet = 0
            self.speech_frames += 1
        else:
            self.quiet += 1
        too_long = len(self.buf) * 0.03 > MAX_UTTERANCE_S
        if self.quiet >= self.silence_frames or too_long:
            enough = self.speech_frames >= self.min_speech_frames
            out = b"".join(self.buf)
            self.reset()
            return out if enough else None
        return None

    @property
    def active(self):
        return self.in_speech


# ---------------------------------------------------------------- wake word
# openWakeWord, fully local, no account. Its models are NOT shipped inside the pip package: the old build crashed
# with "hey_jarvis_v0.1.onnx ... File doesn't exist". They are now downloaded once (a few MB, from the
# openWakeWord GitHub releases) into <data dir>/wakeword/oww/ and loaded from there.
OWW_STOCK = "hey_jarvis_v0.1"


def oww_dir():
    from .paths import p as data_path
    return data_path("wakeword", "oww")


def find_custom():
    """A custom model you trained, e.g. <data dir>/wakeword/hey_hullabaloo.onnx (see docs/WAKE_WORD.md)."""
    import glob, os
    from .paths import p as data_path
    os.makedirs(data_path("wakeword"), exist_ok=True)
    found = sorted(glob.glob(data_path("wakeword", "*.onnx")))
    return found[0] if found else None


def phrase_of(path):
    import os
    if not path:
        return "hey jarvis"
    return os.path.splitext(os.path.basename(path))[0].split("_v")[0].replace("_", " ").replace("-", " ")


def ensure_oww_models(target=None):
    """Download the feature models + hey_jarvis once. Returns the folder. Raises on no internet."""
    import os
    target = target or oww_dir()
    need = [os.path.join(target, f) for f in ("melspectrogram.onnx", "embedding_model.onnx", OWW_STOCK + ".onnx")]
    if not all(os.path.exists(f) for f in need):
        from openwakeword.utils import download_models
        download_models([OWW_STOCK], target_directory=target)
    missing = [f for f in need if not os.path.exists(f)]
    if missing:
        raise RuntimeError("wake word model download incomplete: " + ", ".join(os.path.basename(m) for m in missing))
    return target


class WakeWord:
    """openWakeWord on 80 ms chunks. Uses a custom .onnx in the wakeword folder if there is one, else 'hey jarvis'."""

    def __init__(self, sensitivity=0.5, model_path=None, model_factory=None, models_dir=None):
        import os
        self.sensitivity = float(sensitivity)
        self.carry = b""
        if model_factory:                          # tests
            self.m, self.phrase = model_factory(), "test"
            return
        d = models_dir or ensure_oww_models()
        path = model_path if model_path is not None else (find_custom() or os.path.join(d, OWW_STOCK + ".onnx"))
        self.phrase = phrase_of(None if path.endswith(OWW_STOCK + ".onnx") else path)
        from openwakeword.model import Model
        self.m = Model(wakeword_models=[path], inference_framework="onnx",
                       melspec_model_path=os.path.join(d, "melspectrogram.onnx"),
                       embedding_model_path=os.path.join(d, "embedding_model.onnx"))

    def heard(self, frame: bytes) -> bool:
        self.carry += frame
        hit = False
        while len(self.carry) >= 2560:             # openWakeWord wants 80 ms chunks
            chunk, self.carry = self.carry[:2560], self.carry[2560:]
            scores = self.m.predict(np.frombuffer(chunk, np.int16))
            thr = 1.0 - self.sensitivity * 0.9     # sensitivity 0..1 -> threshold 1.0..0.1
            hit = hit or any(v >= thr for v in scores.values())
        if hit:
            self.m.reset()
            self.carry = b""
        return hit

    def close(self):
        pass


# ---------------------------------------------------------------- pipeline
class MicPipeline:
    """Glue between mic frames (any thread) and the engine (asyncio loop)."""

    def __init__(self, engine, vad=None, wake=None, noise_gate=0.0, emit=None):
        self.eng = engine
        self.det = UtteranceDetector(vad or make_vad(), int(engine.settings.get("vad_silence_ms", 700)))
        self.wake = wake
        self.noise_gate = noise_gate               # 0..1 level below which frames count as silence
        self.emit = emit or engine.emit
        self.loop = None
        self._last_level = 0.0
        self._last_drop_emit = 0.0
        self._dropped = 0
        self._was_closed_at = 0.0
        self._ptt = False
        self._drop_episode = False
        self.armed = False                         # wake mode: wake word heard, capturing one utterance
        self._armed_at = 0.0
        self.on_ptt_change = None                  # server hook: opens/closes the mic stream
        self._partial_busy = False                 # live captions: one rough transcription at a time
        self._partial_at = 0.0
        self._capture_id = 0                       # bumps per utterance, so late partials are ignored
        self.utterances = 0

    def mode(self):
        return self.eng.settings.get("mic_mode", "hotkey")

    def attach_loop(self, loop=None):
        self.loop = loop or asyncio.get_running_loop()

    def on_frame_threadsafe(self, frame: bytes):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.on_frame, frame)

    def _gate_open(self):
        now = time.monotonic()
        if not self.eng.mic_open():
            self._was_closed_at = now
            return False
        return now - self._was_closed_at >= ECHO_TAIL_S * (self.eng.realtime or 1)

    def on_frame(self, frame: bytes):
        """Nothing is captured unless push-to-talk is held, or (wake mode) right after the wake word.
        Before the wake word, frames only go to the wake word model and are thrown away."""
        mode, now = self.mode(), time.monotonic()
        st = self.eng.sm.state.value
        testing = getattr(self.eng, "mic_test", False)   # wizard / settings mic test: user started it
        if mode == "off" and not testing:
            return
        if not self._ptt and not testing:
            if mode != "wake":
                return                              # hotkey mode: stray frame after release
            if not self.armed:
                if self.wake and st in ("sleeping", "listening"):
                    try:
                        if self.wake.heard(frame):
                            self.armed, self._armed_at = True, now
                            self.det.reset()
                            self.eng.wake_word_heard()
                            self.emit({"type": "wake_heard"})
                    except Exception as ex:
                        log.warning("wake word error: %s", ex)
                return
            if not self.det.active and now - self._armed_at > 8:
                self.armed = False                  # said the wake word, then nothing
                self.emit({"type": "wake_timeout"})
                return
        lvl = rms_level(frame)
        if now - self._last_level >= 1 / LEVEL_HZ:
            self._last_level = now
            self.emit({"type": "level", "level": round(lvl, 3)})
        if not self._gate_open():
            if self.det.active:
                self.det.reset()
            # count once per stretch of you talking while it was busy, not once per 30 ms frame
            if lvl > 0.45 and not self._drop_episode:
                self._drop_episode = True
                self._dropped += 1
                self.eng.counters["mic_dropped"] = self.eng.counters.get("mic_dropped", 0) + 1
                self.emit({"type": "mic_dropped", "state": st, "count": self.eng.counters["mic_dropped"]})
            return
        self._drop_episode = False
        if self.noise_gate and lvl < self.noise_gate and not self._ptt:
            frame = bytes(len(frame))
        was_active = self.det.active
        utt = self.det.feed(frame)
        if self.det.active:
            if not was_active:
                self._capture_id += 1
                self._partial_at = now
            self.eng._touch()                       # user is talking: no idle sleep
            self._maybe_partial(now)
        if utt:
            self.armed = False
            self._submit(utt)

    PARTIAL_EVERY_S = 0.6

    def _maybe_partial(self, now):
        """Rough text of what you've said so far, about every 0.6 s, so Home shows your words live."""
        if self._partial_busy or now - self._partial_at < self.PARTIAL_EVERY_S or not self.loop:
            return
        if getattr(self.eng, "mic_test", False) or not getattr(self.eng.settings, "get", None):
            return
        if not self.eng.settings.get("live_captions", True):
            return
        audio = b"".join(self.det.buf)
        if len(audio) < 16000 * 2 * 0.5:            # under half a second: nothing useful yet
            return
        self._partial_at, self._partial_busy, cid = now, True, self._capture_id

        async def run():
            try:
                text = await asyncio.to_thread(self.eng.stt.transcribe, audio[-16000 * 2 * 12:])
                if text and cid == self._capture_id and self.det.active:
                    self.emit({"type": "partial", "text": text})
            except Exception as ex:
                log.debug("partial transcription failed: %s", ex)
            finally:
                self._partial_busy = False
        asyncio.ensure_future(run())

    def _submit(self, utt):
        self.utterances += 1
        asyncio.ensure_future(self.eng.on_audio(utt))

    def ptt_down(self):
        if self.mode() == "off":
            self.emit({"type": "toast", "message": "Mic is off. Switch it on, on Home."})
            return
        if self._ptt:
            return
        if self.on_ptt_change:
            self.on_ptt_change(True)                # open the mic stream now
        if self.eng.sm.state.value == "sleeping":
            self.eng.wake("ptt")
        if self.eng.sm.state.value in ("thinking", "speaking"):
            self.eng.button()                       # holding PTT while it talks = interrupt
        self._ptt = True
        self.det.ptt_down()
        self._capture_id += 1
        self._partial_at = time.monotonic()

    def ptt_up(self):
        if not self._ptt:
            return
        self._ptt = False
        utt = self.det.ptt_up()
        if self.on_ptt_change:
            self.on_ptt_change(False)               # close it again (hotkey mode)
        if utt:
            self._submit(utt)
