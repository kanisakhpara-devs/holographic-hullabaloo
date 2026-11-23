"""Speaker output and microphone input with sounddevice (PortAudio).

Devices are stored by name plus index; if the saved one is gone (Windows renames and
renumbers devices) we fall back to the system default. The default speaker is any
output whose name contains "Hullabaloo" (the base ESP32 as a USB sound card).
"""
import logging, threading
import numpy as np
from .adapters.base import AudioOut

log = logging.getLogger("hullabaloo.audio")

MIC_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = MIC_RATE * FRAME_MS // 1000      # 480


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Linear resample of float32 mono. Plenty for speech; no scipy needed."""
    if sr_in == sr_out or len(x) == 0:
        return x
    n = int(round(len(x) * sr_out / sr_in))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _sd():
    import sounddevice as sd
    return sd


def list_devices():
    """{'inputs': [...], 'outputs': [...]} with name, index, default flag, sample rate."""
    sd = _sd()
    devs = sd.query_devices()
    di, do = sd.default.device if isinstance(sd.default.device, (list, tuple)) else (None, None)
    out = {"inputs": [], "outputs": []}
    for i, d in enumerate(devs):
        e = {"index": i, "name": d["name"], "sample_rate": int(d["default_samplerate"]),
             "hostapi": sd.query_hostapis(d["hostapi"])["name"]}
        if d["max_input_channels"] > 0:
            out["inputs"].append({**e, "default": i == di})
        if d["max_output_channels"] > 0:
            out["outputs"].append({**e, "default": i == do})
    return out


def resolve_device(saved, kind="output"):
    """saved: '' (default), 'name' or 'name|index'. Returns a PortAudio index or None (default)."""
    try:
        devs = list_devices()[kind + "s"]
    except Exception:
        return None
    if not saved:
        if kind == "output":
            for d in devs:
                if "hullabaloo" in d["name"].lower():
                    return d["index"]
        return None
    name, _, idx = str(saved).partition("|")
    if idx.isdigit():
        for d in devs:
            if d["index"] == int(idx) and d["name"] == name:
                return d["index"]
    for d in devs:
        if d["name"] == name:
            return d["index"]
    log.warning("%s device %r not found, using default", kind, saved)
    return None


class SoundDeviceOut(AudioOut):
    """Callback stream with a sample buffer. play() appends, stop() empties the buffer at once."""

    def __init__(self, device="", volume=100, mute=False):
        self.volume, self.mute = volume, mute
        self._lock = threading.Lock()
        self._buf = np.zeros(0, np.float32)
        self.stream = None
        self.open(device)

    def open(self, device=""):
        sd = _sd()
        if self.stream:
            self.stream.close()
        idx = resolve_device(device, "output")
        info = sd.query_devices(idx, "output") if idx is not None else sd.query_devices(kind="output")
        self.rate = int(info["default_samplerate"])
        self.stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="float32", device=idx,
                                      blocksize=0, latency="low", callback=self._cb)
        self.stream.start()
        self.output_latency_s = float(self.stream.latency or 0.0)
        self.device_name = info["name"]
        log.info("speaker %s at %d Hz, latency %.0f ms", self.device_name, self.rate, self.output_latency_s * 1000)

    def _cb(self, outdata, frames, t, status):
        with self._lock:
            n = min(frames, len(self._buf))
            outdata[:n, 0] = self._buf[:n]
            outdata[n:, 0] = 0
            self._buf = self._buf[n:]
        g = 0.0 if self.mute else self.volume / 100.0
        if g != 1.0:
            outdata *= g

    def play(self, pcm: bytes, sample_rate: int):
        x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        x = resample(x, sample_rate, self.rate)
        with self._lock:
            self._buf = np.concatenate([self._buf, x])

    def stop(self):
        with self._lock:
            self._buf = np.zeros(0, np.float32)

    @property
    def busy(self):
        return len(self._buf) > 0

    def test_tone(self, freq=660, secs=0.4):
        t = np.arange(int(self.rate * secs)) / self.rate
        x = (0.3 * np.sin(2 * np.pi * freq * t) * np.minimum(1, (secs - t) * 20)).astype(np.float32)
        self.play((x * 32767).astype(np.int16).tobytes(), self.rate)

    def close(self):
        if self.stream:
            self.stream.close()


class MicIn:
    """16 kHz mono int16, 30 ms frames, delivered to on_frame(bytes) on the PortAudio thread."""

    def __init__(self, on_frame, device="", gain=1.0):
        self.on_frame, self.gain = on_frame, gain
        sd = _sd()
        idx = resolve_device(device, "input")
        self.stream = sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="int16", device=idx,
                                     blocksize=FRAME_SAMPLES, callback=self._cb)
        self.device_name = (sd.query_devices(idx, "input") if idx is not None else sd.query_devices(kind="input"))["name"]
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        x = indata[:, 0]
        if self.gain != 1.0:
            x = np.clip(x.astype(np.float32) * self.gain, -32768, 32767).astype(np.int16)
        self.on_frame(x.tobytes())

    def close(self):
        self.stream.close()
