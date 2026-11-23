"""Streaming emotion-tag parser, sentence splitter and TTS text normalizer.

TagStream consumes LLM tokens as they arrive and yields (emotion, sentence)
pairs as soon as each sentence is complete, so TTS can start on sentence 1
while the model is still writing sentence 2.
"""
import re
from .emotions import EMOTIONS, TAGS

# Off-list tags the model likes to invent, mapped to the closest of the 12.
SYNONYMS = {
    "amused": "smug", "smirk": "smug", "smirking": "smug", "sarcastic": "smug", "sarcasm": "smug",
    "excited": "happy", "joyful": "happy", "cheerful": "happy", "glad": "happy",
    "annoyed": "angry", "irritated": "angry", "mad": "angry", "furious": "angry", "grumpy": "angry",
    "tired": "sleepy", "yawn": "sleepy", "yawning": "sleepy",
    "curious": "confused", "puzzled": "confused", "thinking": "confused", "thoughtful": "confused",
    "shocked": "surprised", "startled": "surprised", "amazed": "surprised", "gasp": "surprised",
    "unimpressed": "bored", "flat": "bored", "sigh": "bored", "sighs": "bored", "deadpan": "bored",
    "chuckle": "laughing", "chuckles": "laughing", "laugh": "laughing", "laughs": "laughing", "giggle": "laughing",
    "doubtful": "suspicious", "skeptical": "suspicious", "sceptical": "suspicious",
    "upset": "sad", "disappointed": "sad",
    "rolls eyes": "eyeroll", "eye roll": "eyeroll", "eye-roll": "eyeroll",
    "calm": "neutral",
}

MAX_TAG_LEN = 30          # longer bracket content is never a tag, just removed
MIN_SENTENCE = 12         # shorter sentences merge with the next one
MAX_SENTENCE = 220        # hard split at a comma beyond this

ABBREV = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "jr", "sr", "prof", "e.g", "i.e", "eg", "ie", "approx"}

FALLBACK = ("confused", "I had something clever to say and then I didn't.")


def normalize_tag(tag: str):
    """'[ Smug ]' -> 'smug'. Returns None for tags we cannot place."""
    t = re.sub(r"\s+", " ", tag.strip().lower())
    if t in TAGS:
        return t
    if t in ("whispers", "whispering", "whispered", "quietly", "softly"):
        return "whisper"
    if t in SYNONYMS:
        return SYNONYMS[t]
    t2 = t.replace(" ", "")
    if t2 in EMOTIONS:
        return t2
    return SYNONYMS.get(t2)


# ---------------------------------------------------------------- normalizer
_ROLE = re.compile(r"^\s*(hullabaloo|assistant|ai|bot|model|user|human)\s*:\s*", re.I)
_PAREN = re.compile(r"\([^()]*\)")
_STAR = re.compile(r"\*{1,2}([^*]{1,40})\*{1,2}")
_ACTIONS = re.compile(r"\b(sigh|laugh|chuckl|giggl|roll|smirk|yawn|grin|shrug|cough|gasp|wink|nod|paus|snort|groan|scoff|clear|stretch|blink|squint|twirl|stroke|adjust)", re.I)


def _star(m):
    """*sighs* is a stage direction (removed); *really* is emphasis (word kept)."""
    inner = m.group(1).strip()
    if len(inner.split()) <= 4 and _ACTIONS.search(inner):
        return " "
    return " " + inner + " "
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️←-⇿⬀-⯿]")
_ABBR_EXP = [
    (re.compile(r"\bMrs\.", re.I), "Missus"), (re.compile(r"\bMr\.", re.I), "Mister"),
    (re.compile(r"\bMs\.", re.I), "Miz"), (re.compile(r"\bDr\.", re.I), "Doctor"),
    (re.compile(r"\bProf\.", re.I), "Professor"), (re.compile(r"\be\.g\.", re.I), "for example"),
    (re.compile(r"\bi\.e\.", re.I), "that is"), (re.compile(r"\betc\.", re.I), "et cetera"),
    (re.compile(r"\bvs\.?(?=\s)", re.I), "versus"), (re.compile(r"\bapprox\.", re.I), "approximately"),
]
_UNITS = {"km": "kilometers", "kg": "kilograms", "cm": "centimeters", "mm": "millimeters", "m": "meters",
          "g": "grams", "ml": "milliliters", "l": "liters", "kmh": "kilometers per hour", "km/h": "kilometers per hour",
          "mph": "miles per hour", "h": "hours", "hr": "hours", "hrs": "hours", "min": "minutes", "s": "seconds",
          "ms": "milliseconds", "gb": "gigabytes", "mb": "megabytes", "tb": "terabytes", "ghz": "gigahertz",
          "mhz": "megahertz", "v": "volts", "w": "watts", "a": "amps", "mah": "milliamp hours", "fps": "frames per second"}
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(km/h|kmh|mph|km|kg|cm|mm|ml|mah|ghz|mhz|gb|mb|tb|hrs|hr|min|ms|fps)\b", re.I)
_SYM = [("%", " percent"), ("&", " and "), ("+", " plus "), ("=", " equals "), ("@", " at "), ("#", " number ")]


_TYPOGRAPHY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "..."})


def clean_for_tts(s: str) -> str:
    """Make one sentence safe to speak: no tags, markup, emojis, stage directions or symbols."""
    s = s.translate(_TYPOGRAPHY)
    s = re.sub(r"\[[^\]]*\]?", " ", s)                     # any leftover bracket
    s = _ROLE.sub("", s)
    s = _PAREN.sub(" ", s)
    s = re.sub(r"[()]", " ", s)
    s = _STAR.sub(_star, s)
    s = re.sub(r"[*_`~>|]+", " ", s)
    s = re.sub(r"^\s*#+\s*", "", s)                         # markdown heading
    s = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", s)       # list bullet / "1." at line start
    s = _EMOJI.sub(" ", s)
    s = s.replace("\u2014", ", ").replace("\u2013", ", ")    # dashes become pauses
    s = re.sub(r"\s+-\s+", ", ", s)
    for rx, rep in _ABBR_EXP:
        s = rx.sub(rep, s)
    s = re.sub(r"(\d)\s?°\s?C\b", r"\1 degrees Celsius", s)
    s = re.sub(r"(\d)\s?°\s?F\b", r"\1 degrees Fahrenheit", s)
    s = re.sub(r"°", " degrees", s)
    s = re.sub(r"\$\s?(\d[\d,.]*)", r"\1 dollars", s)
    s = re.sub(r"(?:₹|\bRs\.?)\s?(\d[\d,.]*)", r"\1 rupees", s)
    s = _UNIT_RE.sub(lambda m: f"{m.group(1)} {_UNITS[m.group(2).lower()]}", s)
    for a, b in _SYM:
        s = s.replace(a, b)
    s = re.sub(r"\s+([,.!?])", r"\1", s)
    s = re.sub(r"([,])\1+", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;:")
    if not re.search(r"[A-Za-z0-9]", s):
        return ""
    return s


# ---------------------------------------------------------------- splitter
def _is_boundary(text: str, i: int) -> bool:
    """text[i] is . ! or ?, and the character after it (and any closing quotes) is whitespace.
    Not a boundary for ellipses or known abbreviations."""
    c = text[i]
    if c == ".":
        if i > 0 and text[i - 1] == ".":
            return False
        if i + 1 < len(text) and text[i + 1] == ".":
            return False
        m = re.search(r"([A-Za-z.]+)$", text[:i])
        if m and m.group(1).lower().strip(".") in ABBREV:
            return False
    return True


def split_sentences(text: str):
    """Non-streaming helper (used for tests and summaries)."""
    ts = TagStream()
    out = ts.feed(text) + ts.flush()
    return [s for _, s in out]


def _hard_split(s: str):
    """Split a run-on longer than MAX_SENTENCE at the last comma (or space) before the limit."""
    parts = []
    while len(s) > MAX_SENTENCE:
        cut = s.rfind(",", 0, MAX_SENTENCE)
        if cut < MIN_SENTENCE:
            cut = s.rfind(" ", 0, MAX_SENTENCE)
        if cut < MIN_SENTENCE:
            cut = MAX_SENTENCE
        parts.append(s[:cut + 1].strip())
        s = s[cut + 1:].strip()
    if s:
        parts.append(s)
    return parts


# ---------------------------------------------------------------- the stream
class TagStream:
    """feed(token) -> list of ready (emotion, sentence); flush(truncated) -> the rest.

    Sentences are cleaned for TTS. A sentence's emotion is the last valid tag before it,
    else the previous sentence's emotion, else neutral.
    """

    def __init__(self):
        self.buf = ""            # raw text not yet consumed
        self.cur = ""            # current sentence text (raw, uncleaned)
        self.emotion = "neutral" # emotion that applies to self.cur
        self.cur_emotion = None  # emotion fixed when self.cur got its first char
        self.saw_tag = False
        self.held = None         # short sentence waiting to merge: (emotion, text)
        self.emitted = 0

    # -- internals
    def _close(self, out):
        raw = self.cur
        self.cur = ""
        emo = self.cur_emotion or self.emotion
        self.cur_emotion = None
        for piece in _hard_split(raw.strip()):
            text = clean_for_tts(piece)
            if text:
                self._push(out, emo, text)

    def _push(self, out, emo, text):
        if self.held:
            emo0, t0 = self.held
            self.held = None
            text, emo = f"{t0} {text}", emo0
        if len(text) < MIN_SENTENCE:
            self.held = (emo, text)
            return
        out.append((emo, text))
        self.emitted += 1

    def _add_text(self, s):
        if not s:
            return
        if self.cur_emotion is None and s.strip():
            self.cur_emotion = self.emotion
        self.cur += s

    def feed(self, token: str, final: bool = False):
        out = []
        self.buf += token
        while self.buf:
            b = self.buf
            lb = b.find("[")
            stop = lb if lb >= 0 else len(b)
            # scan plain text up to the next "[" for sentence boundaries
            i = 0
            consumed = False
            while i < stop:
                c = b[i]
                if c == "\n":
                    self._add_text(b[:i])
                    self.buf = b[i + 1:]
                    if self.cur.strip():
                        self._close(out)
                    consumed = True
                    break
                if c in ".!?":
                    j = i
                    while j + 1 < len(b) and b[j + 1] in ".!?\"')”’":
                        j += 1
                    if j + 1 >= len(b) and not final:
                        # punctuation at the very end: wait for the next token to decide
                        self._add_text(b[:i])
                        self.buf = b[i:]
                        return out
                    nxt = b[j + 1] if j + 1 < len(b) else " "
                    if (nxt.isspace() or nxt == "[") and _is_boundary(self.cur + b[:j + 1], len(self.cur) + i):
                        self._add_text(b[:j + 1])
                        self.buf = b[j + 1:]
                        self._close(out)
                        consumed = True
                        break
                    i = j + 1
                    continue
                i += 1
            if consumed:
                continue
            if lb < 0:
                self._add_text(b)
                self.buf = ""
                if len(self.cur) > MAX_SENTENCE + 40:
                    self._close(out)
                break
            # there is a "[" at lb
            self._add_text(b[:lb])
            rest = b[lb:]
            rb = rest.find("]")
            if rb < 0:
                if len(rest) > MAX_TAG_LEN + 2 or final:
                    self.buf = rest[1:]           # not a tag: drop the bracket and keep going
                    continue
                self.buf = rest                   # tag split across tokens: wait
                return out
            inner = rest[1:rb]
            self.buf = rest[rb + 1:]
            if len(inner) > MAX_TAG_LEN:
                continue                          # long bracket text: removed, never spoken
            emo = normalize_tag(inner)
            if self.cur.strip():
                self._close(out)                  # a tag always starts a new sentence
            if emo:
                self.saw_tag = True
                self.emotion = emo
            # unknown tag: keep the current emotion (inherit)
        return out

    def flush(self, truncated: bool = False):
        out = self.feed("", final=True)
        if self.cur.strip():
            tail = self.cur.strip()
            complete = bool(re.search(r"[.!?][\"')”’]*$", tail))
            if truncated and not complete and (self.emitted or self.held):
                self.cur, self.cur_emotion = "", None     # num_predict cut it mid sentence: drop the fragment
            else:
                self._close(out)
        if self.held:
            out.append(self.held)
            self.held = None
            self.emitted += 1
        return out
