"""Real adapters: faster-whisper (STT), Ollama (LLM, streamed), Kokoro (TTS).
Heavy imports are lazy so the repo and the mock tests run without them.

Tested in the Linux sandbox on CPU: Whisper small int8 and Kokoro (see STATUS.md).
NOT tested here: CUDA, Ollama (no Ollama in the sandbox). Those run on the laptop.
"""
import json, logging, os, re, time
from urllib.parse import urlparse
import numpy as np
from .base import STT, LLM, TTS, Speech

log = logging.getLogger("hullabaloo.adapters")

MIN_UTTERANCE_S = 0.3


def _require_local(url: str):
    host = (urlparse(url).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"refusing non-local LLM url {url!r}: everything must stay on this machine")


def add_nvidia_dll_dirs():
    """Windows: pip's nvidia-cublas-cu12 / nvidia-cudnn-cu12 put DLLs in site-packages/nvidia/*/bin,
    which ctranslate2 cannot find on its own. Register them before importing faster_whisper.
    Also covers a PyInstaller bundle (sys._MEIPASS)."""
    import sys
    if sys.platform != "win32":
        return []
    import glob, site
    try:
        roots = list(site.getsitepackages())
    except Exception:                      # frozen apps have no site-packages
        roots = []
    roots += [getattr(sys, "_MEIPASS", "")]
    appdata = os.path.join(os.environ.get("APPDATA", ""), "HolographicHullabaloo", "cuda")
    added = []
    dirs = [d for r in filter(None, roots) for d in glob.glob(os.path.join(r, "nvidia", "*", "bin"))]
    dirs += glob.glob(os.path.join(appdata, "*", "bin")) + ([appdata] if os.path.isdir(appdata) else [])
    for d in dirs:
        try:
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            added.append(d)
        except OSError:
            pass
    return added


# ---------------------------------------------------------------- STT
class WhisperSTT(STT):
    """faster-whisper. Tries CUDA float16, falls back to CPU int8 if CUDA or its DLLs fail."""

    def __init__(self, model="small", device="cuda", compute_type="float16", download_root=None):
        add_nvidia_dll_dirs()
        from faster_whisper import WhisperModel
        self.fallback_reason = None
        try:
            if device != "cuda":
                raise RuntimeError("cpu requested")
            self.m = WhisperModel(model, device="cuda", compute_type=compute_type, download_root=download_root)
            # cuBLAS/cuDNN problems often only show on first use: run a tiny decode now
            list(self.m.transcribe(np.zeros(16000, np.float32), language="en", beam_size=1)[0])
            self.device = "cuda"
        except Exception as ex:
            if device == "cuda":
                self.fallback_reason = f"CUDA failed ({type(ex).__name__}: {ex}); using CPU int8"
                log.warning(self.fallback_reason)
            self.m = WhisperModel(model, device="cpu", compute_type="int8", download_root=download_root)
            self.device = "cpu"

    def transcribe(self, audio: bytes) -> str:
        """audio: PCM16 mono 16 kHz. Returns '' for too-short or no-speech audio."""
        if len(audio) < MIN_UTTERANCE_S * 16000 * 2:
            return ""
        x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768.0
        segs, _ = self.m.transcribe(x, language="en", vad_filter=True, beam_size=1,
                                    condition_on_previous_text=False)
        keep = [s.text.strip() for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return " ".join(keep).strip()


# ---------------------------------------------------------------- LLM
class OllamaLLM(LLM):
    """Ollama /api/chat with stream=true. Cancelling the consuming task closes the HTTP
    stream, which makes Ollama stop generating."""

    def __init__(self, model="gemma3:4b", url="http://127.0.0.1:11434", keep_alive="30m"):
        _require_local(url)
        self.model, self.url, self.keep_alive = model, url.rstrip("/"), keep_alive
        self.last_done_reason = None

    def _body(self, system, history, user, options, stream):
        msgs = [{"role": "system", "content": system}] + list(history) + [{"role": "user", "content": user}]
        opts = {"temperature": 0.9, "top_p": 0.95, "repeat_penalty": 1.1, "num_predict": 160, "num_ctx": 4096}
        opts.update(options or {})
        return {"model": self.model, "messages": msgs, "stream": stream, "options": opts,
                "keep_alive": self.keep_alive}

    def chat(self, system, history, user, options=None):
        import httpx
        r = httpx.post(f"{self.url}/api/chat", json=self._body(system, history, user, options, False), timeout=120)
        r.raise_for_status()
        d = r.json()
        self.last_done_reason = d.get("done_reason")
        return d["message"]["content"]

    async def stream(self, system, history, user, options=None):
        import httpx
        self.last_done_reason = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as c:
            async with c.stream("POST", f"{self.url}/api/chat",
                                json=self._body(system, history, user, options, True)) as r:
                r.raise_for_status()
                r.encoding = "utf-8"      # Ollama sends no charset; a guessed one garbled curly quotes on Windows
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    tok = (d.get("message") or {}).get("content", "")
                    if tok:
                        yield tok
                    if d.get("done"):
                        self.last_done_reason = d.get("done_reason", "stop")
                        return

    async def warm(self):
        """1 token request so the model is in VRAM before the first real turn.
        Must use the SAME num_ctx as real calls: a different context size makes Ollama
        reload the model (measured on the laptop: 18 s first sentence when it did)."""
        import httpx
        async with httpx.AsyncClient(timeout=180) as c:
            await c.post(f"{self.url}/api/chat", json=self._body("hi", [], "hi", {"num_predict": 1}, False))

    # --- setup helpers (used by the first-run endpoints)
    def is_up(self) -> bool:
        import httpx
        try:
            return httpx.get(f"{self.url}/api/version", timeout=2).status_code == 200
        except Exception:
            return False

    def has_model(self) -> bool:
        import httpx
        try:
            tags = httpx.get(f"{self.url}/api/tags", timeout=5).json().get("models", [])
        except Exception:
            return False
        want = self.model if ":" in self.model else self.model + ":latest"
        return any(m.get("name") == want or m.get("model") == want for m in tags)

    def pull(self):
        """Generator of {status, completed, total} dicts from Ollama's pull API."""
        import httpx
        with httpx.stream("POST", f"{self.url}/api/pull", json={"model": self.model, "stream": True},
                          timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.strip():
                    yield json.loads(line)


# ---------------------------------------------------------------- TTS
class KokoroTTS(TTS):
    """Kokoro 82M via the `kokoro` package (KPipeline, misaki G2P, needs espeak-ng only
    for out of vocabulary words). Returns phonemes with per-symbol times when the
    installed kokoro version gives token timestamps (start_ts/end_ts), else even spread."""

    SR = 24000

    def __init__(self, lang="a", device="cpu", repo_id="hexgrad/Kokoro-82M"):
        from kokoro import KPipeline
        self.device = device
        self.p = KPipeline(lang_code=lang, repo_id=repo_id, device=device)
        self.lang, self.repo_id = lang, repo_id
        self.pipes = {lang: self.p}        # British voices (bf_ / bm_) get a British pipeline, sharing the model
        self.timestamps_seen = None        # True/False after the first call

    def _pipe(self, voice):
        want = "b" if voice[:1] == "b" else "a"
        if want not in self.pipes:
            from kokoro import KPipeline
            try:
                self.pipes[want] = KPipeline(lang_code=want, repo_id=self.repo_id, model=self.p.model)
            except Exception as ex:                  # missing British G2P data: American pronunciation, same voice
                log.warning("kokoro %s pipeline failed (%s), using %s", want, ex, self.lang)
                self.pipes[want] = self.p
        return self.pipes[want]

    def speak(self, text, voice, speed):
        chunks, phs, times, wts = [], [], [], []
        offset = 0.0
        have_ts = True
        for res in self._pipe(voice)(text, voice=voice, speed=speed):
            a = res.audio
            a = a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a)
            a = a.astype(np.float32).reshape(-1)
            dur = len(a) / self.SR
            toks = getattr(res, "tokens", None) or []
            got = [t for t in toks if getattr(t, "start_ts", None) is not None and getattr(t, "phonemes", None)]
            if got:
                for t in got:
                    seq = list(t.phonemes)
                    st, en = offset + float(t.start_ts), offset + float(t.end_ts or t.start_ts)
                    if any(ch.isalnum() for ch in str(getattr(t, "text", ""))):
                        wts.append(round(st, 3))
                    step = (en - st) / max(1, len(seq))
                    phs.extend(seq)
                    times.extend(st + i * step for i in range(len(seq)))
                    phs.append(" ")
                    times.append(en)
            else:
                have_ts = False
                phs.extend(list(res.phonemes or ""))
                phs.append(" ")
                times.extend([None] * (len(res.phonemes or "") + 1))
            chunks.append(a)
            offset += dur
        if self.timestamps_seen is None:
            self.timestamps_seen = have_ts
            log.info("kokoro token timestamps available: %s", have_ts)
        a = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
        return Speech(audio=pcm, sample_rate=self.SR, duration_s=len(a) / self.SR, phonemes=phs,
                      times=times if have_ts else None, word_times=wts if have_ts and wts else None)
