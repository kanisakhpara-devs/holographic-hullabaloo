"""Music reactions: listen to what this computer is PLAYING (speaker loopback, not the microphone), find the
beats, and make the face bob along while it is idle.

Loopback capture uses the `soundcard` package (WASAPI loopback on Windows). If it is missing or the speaker
can't be opened, the feature just reports why and stays off; nothing else is affected.

Only the beat timing and loudness are used. No audio is saved, sent anywhere or transcribed.
"""
import logging, math, threading, time
import numpy as np

log = logging.getLogger("hullabaloo.music")

SR = 48000
BLOCK = 1024                     # about 21 ms per block


class BeatDetector:
    """Energy-flux beat finder. feed(block of float32 mono samples) -> list of events:
    ('start',) when music has been playing for START_S, ('stop',) after STOP_S of quiet, ('beat', strength 0..1)."""
    START_S, STOP_S, MIN_GAP_S = 2.0, 2.5, 0.28

    def __init__(self, sensitivity=0.5, block_s=BLOCK / SR, clock=None):
        self.block_s = block_s
        self.set_sensitivity(sensitivity)
        self.avg = 1e-6                     # slow energy average (about 1 s)
        self.t = 0.0                        # stream time in seconds (independent of the wall clock)
        self.loud_since = None
        self.quiet_since = None
        self.playing = False
        self.last_beat = -1.0
        self.level = 0.0

    def set_sensitivity(self, s):
        s = max(0.0, min(1.0, float(s)))
        self.floor_db = -30.0 - 20.0 * s            # 0 -> needs -30 dBFS, 1 -> reacts from -50 dBFS
        self.ratio = 1.7 - 0.5 * s                  # how far above the average a block must be to count as a beat

    def feed(self, x):
        out = []
        x = np.asarray(x, np.float32)
        e = float(np.mean(x * x)) if len(x) else 0.0
        db = 10 * math.log10(max(e, 1e-12))
        self.level = max(0.0, min(1.0, (db + 60) / 60))
        a = min(1.0, self.block_s / 1.0)
        loud = db > self.floor_db
        self.t += self.block_s
        if loud:
            self.quiet_since = None
            if self.loud_since is None:
                self.loud_since = self.t
            if not self.playing and self.t - self.loud_since >= self.START_S:
                self.playing = True
                out.append(("start",))
        else:
            self.loud_since = None
            if self.quiet_since is None:
                self.quiet_since = self.t
            if self.playing and self.t - self.quiet_since >= self.STOP_S:
                self.playing = False
                out.append(("stop",))
        if self.playing and loud and e > self.avg * self.ratio and self.t - self.last_beat >= self.MIN_GAP_S:
            self.last_beat = self.t
            out.append(("beat", max(0.0, min(1.0, (e / max(self.avg, 1e-12) - self.ratio) / 3))))
        self.avg += (e - self.avg) * a
        return out


class MusicListener:
    """Background thread: speaker loopback -> BeatDetector -> engine.music_event(...) on the engine's loop."""

    def __init__(self, engine, recorder_factory=None):
        self.eng = engine
        self.det = BeatDetector(engine.settings["music_sensitivity"])
        self._factory = recorder_factory or _loopback_recorder
        self._stop = threading.Event()
        self._thread = None
        self.status = {"ok": False, "message": "off"}

    def _report(self, ok, message):
        self.status = {"ok": ok, "message": message}
        self.eng.emit({"type": "music_status", **self.status})

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="music", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        if self.det.playing:
            self.det.playing = False
            self._post(("stop",))
        self._report(False, "off")

    def _post(self, ev):
        loop = self.eng._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self.eng.music_event, ev, self.det.level)

    def _run(self):
        try:
            rec = self._factory()
        except Exception as ex:
            log.warning("music reactions unavailable: %s", ex)
            self._report(False, f"can't listen to the speaker output: {ex}")
            return
        self._report(True, "listening for music")
        try:
            with rec as r:
                while not self._stop.is_set():
                    data = r.record(numframes=BLOCK)
                    x = np.asarray(data, np.float32)
                    if x.ndim > 1:
                        x = x.mean(axis=1)
                    for ev in self.det.feed(x):
                        self._post(ev)
        except Exception as ex:
            log.warning("music loopback stopped: %s", ex)
            self._report(False, f"speaker capture stopped: {ex}")


def _loopback_recorder():
    """The default speaker, opened as a loopback 'microphone' (needs `pip install soundcard`)."""
    import soundcard as sc
    spk = sc.default_speaker()
    mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    return mic.recorder(samplerate=SR, channels=2, blocksize=BLOCK)
