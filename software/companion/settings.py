"""All settings keys: type, default, validation, and whether a change takes effect live.

Stored in SQLite (JSON values) and mirrored to <app data>/settings.json.
`content` is never persisted: it is always 'pg' at start and on device reconnect,
and only a UI call (from_ui=True) can set it to 'unfiltered'.
"""
import json, logging, os, re
from .emotions import EMOTIONS, validate_speech_entry
from .states import State

log = logging.getLogger("hullabaloo.settings")

STATES = [s.value for s in State]


class Bad(ValueError):
    pass


def _choice(*opts):
    def f(v):
        if v not in opts:
            raise Bad(f"must be one of {', '.join(opts)}")
        return v
    return f


def _num(lo, hi, cast=float):
    def f(v):
        if isinstance(v, bool):
            raise Bad("must be a number")
        try:
            x = cast(v)
        except (TypeError, ValueError):
            raise Bad("must be a number")
        if cast is int and float(v) != int(float(v)):
            raise Bad("must be a whole number")
        if not lo <= x <= hi:
            raise Bad(f"must be {lo} to {hi}")
        return x
    return f


def _bool(v):
    if not isinstance(v, bool):
        raise Bad("must be true or false")
    return v


def _text(maxlen, pattern=None):
    def f(v):
        if not isinstance(v, str):
            raise Bad("must be text")
        if len(v) > maxlen:
            raise Bad(f"max {maxlen} characters")
        if pattern and v and not re.fullmatch(pattern, v):
            raise Bad("invalid format")
        return v
    return f


def _hotkey(v):
    v = _text(40)(v)
    parts = v.split("+")
    mods = {"Ctrl", "Alt", "Shift", "Super", "CommandOrControl"}
    if not parts or not parts[-1] or any(p not in mods for p in parts[:-1]) or parts[-1] in mods:
        raise Bad("hotkey like Ctrl+Space or Ctrl+Shift+H")
    return v


def _local_url(v):
    v = _text(100, r"https?://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?/?")(v)
    if not v:
        raise Bad("required")
    return v


def _timezone(v):
    v = _text(64)(v)
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(v)
    except Exception:
        raise Bad("unknown time zone (example: Asia/Kolkata)")
    return v


def _voice_overrides(v):
    if not isinstance(v, dict):
        raise Bad("must be an object of emotion -> {speed, voice, pause_ms}")
    out = {}
    for e, o in v.items():
        if e not in EMOTIONS or not isinstance(o, dict):
            raise Bad(f"bad emotion {e!r}")
        base = {"speed": 1.0, "voice": "am_michael", "pause_ms": 180}
        try:
            clean = validate_speech_entry({**base, **o})
        except (ValueError, KeyError, TypeError) as ex:
            raise Bad(f"{e}: {ex}")
        out[e] = {k: clean[k] for k in o if k in clean}
    return out


def _emotion_map(v):
    if not isinstance(v, dict):
        raise Bad("must be an object of state -> emotion")
    for s, e in v.items():
        if s not in STATES or e not in EMOTIONS:
            raise Bad(f"bad entry {s!r}: {e!r}")
    return dict(v)


def _persona(v):
    v = _text(40, r"[a-z0-9_]+")(v)
    if not v:
        raise Bad("required")
    return v


# key: (default, validator, live, helper text). live=False means: saved now, used after
# the named component reloads (noted in `needs`).
SCHEMA = {
    "persona":               ("smug_sarcastic", _persona, True, "Personality file from the personas folder."),
    "custom_persona_text":   ("", _text(1200), True, "Your own persona text, used when persona is 'custom'."),
    "content":               ("pg", _choice("pg", "unfiltered"), True, "PG always at start. Unfiltered only from this UI."),
    "privacy_mode":          ("debug", _choice("debug", "faire"), True, "debug keeps transcripts 24 h; faire keeps only names and facts."),
    "reply_length":          ("normal", _choice("short", "normal", "long"), True, "How long replies are."),
    "sarcasm_level":         (2, _num(0, 3, int), True, "0 warm to 3 maximum sass."),
    "temperature":           (0.9, _num(0.5, 1.2), True, "Creativity of the model."),
    "roast_user":            (False, _bool, True, "Tease the person more (still PG in PG mode)."),
    "blocklist":             ("", _text(2000), True, "Comma or line separated words/topics that always get deflected."),
    "owner_name":            ("", _text(20, r"^[A-Za-z][A-Za-z' -]{0,19}$"), True,
                              "Your name. It assumes it's talking to you unless someone says their name."),
    "web_search":            (False, _bool, True, "Look up recent facts online (DuckDuckGo) for time-sensitive questions. Needs internet, adds about 1 s."),
    "proximity_wake":        (True, _bool, True, "Wake when someone comes near the device."),
    "mic_mode":              ("hotkey", _choice("off", "hotkey", "wake"), True,
                              "off = mic closed; hotkey = mic opens only while push-to-talk is held; wake = listens only for the wake word."),
    "wake_word_sensitivity": (0.5, _num(0.0, 1.0), True, "Higher wakes more easily (and falsely)."),
    "ptt_hotkey":            ("Ctrl+Space", _hotkey, True, "Hold to talk (handled by the desktop shell)."),
    "vad_silence_ms":        (700, _num(200, 3000, int), True, "Silence that ends your sentence."),
    "idle_timeout_s":        (30.0, _num(5, 600), True, "Go to sleep after this much silence."),
    "mic_device":            ("", _text(200), True, "Microphone (empty = system default)."),
    "mic_gain":              (1.0, _num(0.1, 8.0), True, "Input gain."),
    "noise_gate":            (0.0, _num(0.0, 1.0), True, "Treat input below this level as silence (0 = off)."),
    "speaker_device":        ("", _text(200), True, "Speaker (empty = Hullabaloo device if present, else default)."),
    "volume":                (80, _num(0, 100, int), True, "Speaker volume."),
    "mute":                  (False, _bool, True, "Mute the speaker."),
    "tts_speed_scale":       (1.0, _num(0.7, 1.3), True, "Multiplies every emotion's speed."),
    "lipsync_offset_ms":     (0, _num(-200, 200, int), True, "Shift the mouth later (+) or earlier (-) than the audio."),
    "voice_overrides":       ({}, _voice_overrides, True, "Per emotion speed/voice/pause overrides."),
    "emotion_map":           ({}, _emotion_map, True, "Face shown in each state (overrides the defaults)."),
    "device_mode":           ("serial", _choice("sim", "serial"), True, "The real device over USB, or the on screen simulator."),
    "serial_port":           ("", _text(64), True, "COM port (empty = auto-detect)."),
    "device_brightness_cap": (255, _num(0, 255, int), True, "Maximum LED brightness sent to the device."),
    "llm_model":             ("gemma3:4b", _text(80, r"[A-Za-z0-9._:/-]+"), True, "Ollama model name."),
    "ollama_url":            ("http://127.0.0.1:11434", _local_url, True, "Must be this computer."),
    "stt_model":             ("small", _choice("tiny", "base", "small", "medium"), False, "Whisper model size."),
    "stt_device":            ("cuda", _choice("cuda", "cpu"), False, "Where Whisper runs."),
    "tts_device":            ("cpu", _choice("cpu", "cuda"), False, "Where Kokoro runs."),
    "timezone":              ("Asia/Kolkata", _timezone, True, "Used for the time in the prompt."),
    "autostart":             (False, _bool, True, "Start with Windows (desktop shell)."),
    "start_minimized":       (False, _bool, True, "Start in the tray (desktop shell)."),
    "tray_icon":             (True, _bool, True, "Closing the window minimizes to the tray."),
    "log_level":             ("info", _choice("debug", "info", "warning", "error"), True, "Log detail."),
    "ui_theme":              ("classic", _choice("classic", "glass"), True, "Classic sage cards, or liquid glass."),
    "ui_animations":         (True, _bool, True, "Background waves and other animations (ignores the Windows animation setting)."),
    "ui_scale":              (1.0, _num(0.8, 1.5), True, "Text and bubble size; the layout reflows."),
}
DEFAULTS = {k: v[0] for k, v in SCHEMA.items()}
NEEDS_RELOAD = {"stt_model": "speech recognizer", "stt_device": "speech recognizer", "tts_device": "voice"}


def validate(key, value):
    if key not in SCHEMA:
        raise Bad("unknown setting")
    return SCHEMA[key][1](value)


class Settings(dict):
    """dict of current values + persistence. Use update_from() for changes."""

    def __init__(self, mem, export_path=None):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.mem, self.export_path = mem, export_path
        for k in SCHEMA:
            if k == "content":
                continue
            raw = mem.get(k)
            if raw is None:
                continue
            try:
                v = json.loads(raw)
            except ValueError:
                v = raw                                # older plain-string rows
                if isinstance(DEFAULTS[k], bool):
                    v = raw == "True"
                elif isinstance(DEFAULTS[k], (int, float)):
                    try:
                        v = type(DEFAULTS[k])(float(raw))
                    except ValueError:
                        continue
            try:
                self[k] = validate(k, v)
            except Bad as ex:
                log.warning("stored setting %s=%r invalid (%s), using default", k, v, ex)
        self["content"] = "pg"

    def update_from(self, patch: dict, from_ui=False):
        """Validate everything first, then apply. Returns (applied, errors)."""
        applied, errors = {}, {}
        if not isinstance(patch, dict):
            return {}, {"_": "patch must be an object"}
        for k, v in patch.items():
            if k == "content" and not from_ui:
                errors[k] = "content can only be changed from the laptop UI"
                continue
            try:
                applied[k] = validate(k, v)
            except Bad as ex:
                errors[k] = str(ex)
        for k, v in applied.items():
            self[k] = v
            if k != "content":
                self.mem.put(k, json.dumps(v))
        if applied:
            self.export()
        return applied, errors

    def export(self):
        if not self.export_path:
            return
        try:
            data = {k: v for k, v in self.items() if k != "content"}
            tmp = self.export_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.export_path)
        except OSError as ex:
            log.warning("settings export failed: %s", ex)

    def describe(self):
        return {k: {"default": d, "live": live, "help": h, **({"needs": NEEDS_RELOAD[k]} if k in NEEDS_RELOAD else {})}
                for k, (d, _, live, h) in SCHEMA.items()}
