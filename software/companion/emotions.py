"""Emotion list, tag parsing, and emotion -> TTS style mapping."""
import json, os, re

EMOTIONS = ["neutral", "happy", "smug", "angry", "surprised", "sad",
            "confused", "sleepy", "bored", "suspicious", "laughing", "eyeroll"]

# [whisper] is an extra sentence tag, not a 13th face: the device shows the suspicious face (leaning in) and
# the audio is turned into a fake whisper by whisperize(). Kokoro cannot really whisper.
WHISPER = "whisper"
TAGS = EMOTIONS + [WHISPER]


def face_for(tag: str) -> str:
    return "suspicious" if tag == WHISPER else tag


def whisperize(pcm: bytes, sr: int, seed: int = 0) -> bytes:
    """Fake whisper: keep only the breathy top of the voice, replace the voiced part with noise that
    follows the speech envelope, and make it quieter. PCM16 mono in and out."""
    import numpy as np
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    if len(x) < 64:
        return pcm
    hp = np.concatenate([[0.0], np.diff(x)])                       # crude high pass: drops the pitch body
    win = max(1, int(sr * 0.012))
    env = np.convolve(np.abs(x), np.ones(win) / win, mode="same")  # loudness envelope of the speech
    rng = np.random.default_rng(seed)
    n = rng.standard_normal(len(x)).astype(np.float32)
    n = np.concatenate([[0.0], np.diff(n)])                        # hiss, not rumble
    y = 0.55 * hp + 1.6 * n * env
    peak = float(np.max(np.abs(y))) or 1.0
    y = y / peak * 0.32                                            # quiet
    return (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()


# Kokoro has no true emotion control: we fake it with speed, pauses and text shaping
# (see shape_text). ONE voice for every emotion on purpose: switching voices between
# sentences sounded like two different people talking in the same answer.
# speed: 1.0 = normal. The voice name is a Kokoro voice id (swap freely, but keep it the same).
VOICE = "am_michael"
TTS_STYLE = {
    "neutral":    {"speed": 1.00, "voice": VOICE},
    "happy":      {"speed": 1.22, "voice": VOICE},
    "smug":       {"speed": 0.85, "voice": VOICE},
    "angry":      {"speed": 1.30, "voice": VOICE},
    "surprised":  {"speed": 1.28, "voice": VOICE},
    "sad":        {"speed": 0.72, "voice": VOICE},
    "confused":   {"speed": 0.92, "voice": VOICE},
    "sleepy":     {"speed": 0.68, "voice": VOICE},
    "bored":      {"speed": 0.78, "voice": VOICE},
    "suspicious": {"speed": 0.82, "voice": VOICE},
    "laughing":   {"speed": 1.25, "voice": VOICE},
    "eyeroll":    {"speed": 0.82, "voice": VOICE},
}

# Pause after each sentence (ms), by emotion. Skipped after the final sentence.
PAUSE_MS = {"neutral": 180, "happy": 140, "smug": 380, "angry": 120, "surprised": 160,
            "sad": 550, "confused": 320, "sleepy": 700, "bored": 600, "suspicious": 450,
            "laughing": 100, "eyeroll": 500}

_END = re.compile(r"\.([\"')\]]*)$")
_ELLIPSIS_END = re.compile(r"\.{2,}[\"')\]]*$")


def shape_text(emotion: str, s: str) -> str:
    """Spoken text only (the transcript keeps the original). Kokoro reads punctuation as
    intonation: '!' lifts the ending, '...' drags and trails off, a comma turned into '...'
    makes a dramatic beat. No words are added or removed."""
    s = s.strip()
    if not s or _ELLIPSIS_END.search(s):
        return s
    if emotion in ("happy", "angry", "surprised", "laughing"):
        return _END.sub(r"!\1", s)
    if emotion in ("sad", "sleepy", "bored", "suspicious", "confused"):
        if emotion in ("sad", "sleepy"):
            s = s.replace(", ", "... ", 2)
        return _END.sub(r"...\1", s)
    if emotion in ("smug", "eyeroll"):
        return s.replace(", ", "... ", 1)
    return s


DEFAULT_SPEECH_MAP = {e: {"speed": TTS_STYLE[e]["speed"], "voice": TTS_STYLE[e]["voice"],
                          "pause_ms": PAUSE_MS[e], "pitch_note": ""} for e in EMOTIONS}


def validate_speech_entry(v: dict) -> dict:
    """Raise ValueError on bad values; return a clean entry."""
    out = {}
    sp = float(v["speed"])
    if not 0.6 <= sp <= 1.5:
        raise ValueError("speed must be 0.6 to 1.5")
    out["speed"] = sp
    voice = str(v["voice"])
    if not re.fullmatch(r"[a-z]{2}_[a-z]{2,20}", voice):
        raise ValueError("voice must be a Kokoro voice id like am_adam")
    out["voice"] = voice
    pm = int(v.get("pause_ms", 180))
    if not 0 <= pm <= 2000:
        raise ValueError("pause_ms must be 0 to 2000")
    out["pause_ms"] = pm
    out["pitch_note"] = str(v.get("pitch_note", ""))[:200]
    return out


class SpeechMap:
    """Emotion -> {speed, voice, pause_ms, pitch_note}, stored as editable JSON."""

    def __init__(self, path=None):
        self.path = path
        self.map = json.loads(json.dumps(DEFAULT_SPEECH_MAP))
        if path and os.path.exists(path):
            try:
                self.update(json.load(open(path, encoding="utf-8")), save=False)
            except (ValueError, KeyError, TypeError, OSError):
                pass                                  # broken file: keep defaults

    def get(self, emotion):
        return self.map.get(emotion, self.map["neutral"])

    def update(self, patch: dict, save=True):
        clean = {}
        for e, v in patch.items():
            if e not in EMOTIONS:
                raise ValueError(f"unknown emotion {e}")
            clean[e] = validate_speech_entry({**self.map[e], **v})
        self.map.update(clean)
        if save and self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.map, f, indent=2)
        return self.map


_TAG = re.compile(r"\[(\w+)\]")


def parse_tagged(text: str):
    """Split Gemma output like '[smug] Oh, really? [eyeroll] Sure.' into
    [(emotion, sentence_text), ...]. Text before any tag is 'neutral'.
    Unknown tags are dropped (the text is kept under the current emotion)."""
    out, cur, pos = [], "neutral", 0
    for m in _TAG.finditer(text):
        chunk = text[pos:m.start()].strip()
        if chunk:
            out.append((cur, chunk))
        tag = m.group(1).lower()
        if tag in TAGS:
            cur = tag
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append((cur, tail))
    return out or [("neutral", text.strip())]
