"""Phoneme -> 6 mouth shapes, and a 30 fps timeline builder.

Shapes: closed, ah, oh, ee, oo, fv (device index order).
Symbols are misaki (Kokoro's G2P) output. misaki American English uses IPA plus
capital letters for diphthongs: A = eI, I = aI, W = aU, Y = oI, O = oU (Q = British oU).
Stress marks and length marks carry no time. Consonants that do not shape the lips
(t d s z n l r k g ng h j flap) return None: the mouth keeps the neighbouring vowel
shape, which reads much better on a 6-shape cartoon than flapping to a fixed shape.
"""
FPS = 30
MIN_HOLD_FRAMES = 2

_MAP = {}


def _set(chars, v):
    for c in chars:
        _MAP[c] = v


_set("pbm", "closed")
_set("fv", "fv")
_set("iɪeɛAᵻjE", "ee")             # see, sit, bed, say (A = eI), y-glide
_set("uʊwW", "oo")                 # food, put, we
_set("ʃʒʧʤ", "oo")                 # sh, zh, ch, j: lips push forward
_set("oɔɒOQY", "oh")               # law, go (O), boy (Y)
_set("aɑʌɐəæɜɚᵊIh", "ah")          # father, cup, cat, bird, schwa, my (I = aI), h
_set("θð", "ee")                   # th: tongue between teeth, mouth slightly open
_set("tdsznlɹrkgɡŋɾʔT", None)      # no lip shape (T = misaki flap): keep the previous one
# uppercase letters from the mock TTS / plain text fallback
_set("PBM", "closed")
_set("FV", "fv")

IGNORE = set("ˈˌːˑ.,!?;:'\"-()[]\u2026\u2014\u2013")


def phoneme_to_viseme(ph: str):
    """None means 'no lip shape' (hold the previous). Unknown letters: 'ah'."""
    if ph in _MAP:
        return _MAP[ph]
    if ph in IGNORE or not ph.strip():
        return None
    return "ah"


def build_timeline(phonemes, duration_s: float, fps: int = FPS, times=None):
    """phonemes: list of symbols (one per char, " " marks a word gap).
    times: optional start time (s) per symbol from the TTS; else spread evenly
    over the symbols that take time (marks and punctuation take none).

    Output: [(t_seconds, viseme)], t on the 1/fps grid, starts at 0.0 with 'closed',
    repeats merged, each shape held at least 2 frames (a word-gap 'closed' may be 1),
    and ends on 'closed' at the end of the audio. So never more than fps updates/s."""
    if duration_s <= 0 or not phonemes:
        return [(0.0, "closed")]
    if times is not None and len(times) == len(phonemes):
        pairs = list(zip(phonemes, times))
    else:
        timed = [p for p in phonemes if p == " " or p not in IGNORE]
        step = duration_s / max(1, len(timed))
        pairs, i = [], 0
        for p in phonemes:
            if p == " " or p not in IGNORE:
                pairs.append((p, i * step))
                i += 1
    end_frame = max(1, round(duration_s * fps))

    events = []                                   # (frame, viseme, is_gap)
    for p, t in pairs:
        f = min(end_frame - 1, max(0, round(t * fps)))
        if p == " ":
            events.append((f, "closed", True))
            continue
        v = phoneme_to_viseme(p)
        if v is not None:
            events.append((f, v, False))

    out = [(0, "closed", True)]
    for f, v, gap in events:
        lf, lv, lgap = out[-1]
        if v == lv:
            continue
        min_f = lf + (1 if lgap else MIN_HOLD_FRAMES)
        if f < min_f:
            if f == lf and not lgap and not gap:
                out[-1] = (lf, v, False)          # same frame: the later shape wins
                continue
            if gap:
                continue                          # no room for a gap blink: skip it
            f = min_f                             # nudge to keep the 2 frame hold
            if f >= end_frame:
                continue
        out.append((f, v, gap))
    if out[-1][1] != "closed":
        f = max(end_frame, out[-1][0] + MIN_HOLD_FRAMES)
        out.append((f, "closed", True))
    return [(f / fps, v) for f, v, _ in out]


def text_to_fake_phonemes(text: str):
    """Mock-TTS fallback: letters as pseudo phonemes, spaces as word gaps."""
    return [c if c.isalpha() else " " for c in text.lower() if c.isalpha() or c == " "]
