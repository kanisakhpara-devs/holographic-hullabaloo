"""Timers and reminders, the study buddy (pomodoro + quiz), voice mini games and night hours.

Everything here is plain Python with no models: the engine asks `parse_*` whether a message is a command,
keeps the state objects, and asks them each second whether something is due. The LLM only ever phrases
things; whether a timer exists is decided here, so it can never pretend to have set one.
"""
import random, re, time
from datetime import datetime, timedelta

# ------------------------------------------------------------------ numbers and durations
_UNITS = {"zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "couple": 2, "few": 3}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90}
NUM = r"(?:\d+(?:\.\d+)?|half(?: an?)?|(?:twenty|thirty|forty|fifty|sixty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|" \
      r"zero|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|" \
      r"seventeen|eighteen|nineteen|couple(?: of)?|few)"
UNIT = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|h|m|s)\b"
DUR = rf"{NUM}\s*-?\s*{UNIT}(?:\s*(?:and\s*)?(?:a\s+)?(?:{NUM}\s*-?\s*{UNIT}|half))*"


def word_num(w: str) -> float:
    w = w.strip().lower().replace("couple of", "couple")
    if re.fullmatch(r"\d+(\.\d+)?", w):
        return float(w)
    if w.startswith("half"):
        return 0.5
    if w in _UNITS:
        return _UNITS[w]
    parts = re.split(r"[- ]", w)
    if parts[0] in _TENS:
        return _TENS[parts[0]] + (_UNITS.get(parts[1], 0) if len(parts) > 1 else 0)
    raise ValueError(w)


def parse_duration(s: str):
    """'10 minutes', 'an hour and a half', '1 hour 30 mins', 'ninety seconds' -> seconds (or None)."""
    s = s.lower()
    total, found = 0.0, False
    for n, u in re.findall(rf"({NUM})\s*-?\s*({UNIT})", s):
        try:
            v = word_num(n)
        except ValueError:
            continue
        u = u[0]
        total += v * (3600 if u == "h" else 60 if u == "m" else 1)
        found = True
    if found and re.search(r"\band a half\b", s):
        last = re.findall(rf"({UNIT})", s)[-1][0]
        total += 1800 if last == "h" else 30 if last == "m" else 0
    return total if found and total > 0 else None


def fmt_duration(secs: float) -> str:
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    out = []
    if h:
        out.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        out.append(f"{m} minute" + ("s" if m != 1 else ""))
    if s and not h:
        out.append(f"{s} second" + ("s" if s != 1 else ""))
    return " and ".join(out) or "0 seconds"


def parse_clock(s: str, now: datetime):
    """'5 pm', '5:30', '17:45', 'half past six' -> the next datetime at that time (or None)."""
    s = s.lower().replace(".", "")
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a m|p m)?\b", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(" ", "")
    if h > 23 or mi > 59 or (ap and h > 12):
        return None
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if not ap and h <= 12 and t <= now:                 # "at 5" in the afternoon means 5 pm, not tomorrow 5 am
        if (t + timedelta(hours=12)) > now:
            t += timedelta(hours=12)
    if t <= now:
        t += timedelta(days=1)
    return t


def _clean_label(s: str) -> str:
    s = re.sub(r"^\s*(?:to|that|about)\s+", "", (s or "").strip(" .,!?"))
    s = re.sub(r"\b(please|thanks|thank you)\b", "", s).strip(" .,!?")
    s = re.sub(r"\bmy\b", "your", s)
    s = re.sub(r"\bI\b", "you", s)
    return s[:80]


# ------------------------------------------------------------------ timers
TIMER_RX = re.compile(rf"\b(?:set|start|put on|make)?\s*(?:a|an|the|my)?\s*(?P<d1>{DUR})\s+timer\b(?:\s+(?:for|to)\s+(?P<l1>.+))?"
                      rf"|\btimer\s+(?:for|of)\s+(?P<d2>{DUR})(?:\s+(?:for|to)\s+(?P<l2>.+))?", re.I)
REMIND_IN_RX = re.compile(rf"\bremind me\s+(?:in|after)\s+(?P<d>{DUR})\s*(?:to|that|about)?\s*(?P<l>.*)"
                          rf"|\bremind me\s+(?:to|that|about)\s+(?P<l2>.+?)\s+(?:in|after)\s+(?P<d2>{DUR})\b", re.I)
REMIND_AT_RX = re.compile(r"\bremind me\s+(?:at|by)\s+(?P<t>[\d: ]+\s*(?:am|pm|a\.?m\.?|p\.?m\.?)?)\s*(?:to|that|about)?\s*(?P<l>.*)"
                          r"|\bremind me\s+(?:to|that|about)\s+(?P<l2>.+?)\s+(?:at|by)\s+(?P<t2>[\d: ]+\s*(?:am|pm|a\.?m\.?|p\.?m\.?)?)", re.I)
CANCEL_RX = re.compile(r"\b(?:cancel|stop|delete|remove|clear|kill)\b.*\b(?P<what>timers?|reminders?|alarms?)\b", re.I)
LIST_RX = re.compile(r"\b(?:what|which|any|how many|list|show)\b.*\b(?:timers?|reminders?)\b"
                     r"|\bhow (?:long|much time)\b.*\b(?:left|remaining)\b", re.I)


def parse_timer_command(text: str, now: datetime):
    """-> ('add', kind, seconds_from_now, label) | ('cancel', all_or_label) | ('list',) | None"""
    t = text.strip()
    m = CANCEL_RX.search(t)
    if m:
        rest = re.sub(r"\b(cancel|stop|delete|remove|clear|kill|the|my|all|timers?|reminders?|alarms?|please|for)\b", " ", t.lower())
        rest = rest.strip(" .,!?")
        return ("cancel", "all" if re.search(r"\ball\b|\bevery", t.lower()) or not rest else rest)
    m = REMIND_IN_RX.search(t)
    if m:
        d = parse_duration(m.group("d") or m.group("d2") or "")
        if d:
            return ("add", "reminder", d, _clean_label(m.group("l") if m.group("d") else m.group("l2")))
    m = REMIND_AT_RX.search(t)
    if m:
        when = parse_clock(m.group("t") or m.group("t2") or "", now)
        if when:
            return ("add", "reminder", (when - now).total_seconds(), _clean_label(m.group("l") if m.group("t") else m.group("l2")))
    m = TIMER_RX.search(t)
    if m:
        d = parse_duration(m.group("d1") or m.group("d2") or "")
        if d:
            return ("add", "timer", d, _clean_label(m.group("l1") or m.group("l2") or ""))
    if LIST_RX.search(t):
        return ("list",)
    return None


class Timers:
    """Timers and reminders, saved in the memory database so they survive a restart."""
    MAX = 20

    def __init__(self, mem, clock=time.time):
        self.mem, self.clock = mem, clock
        with mem.lock:
            mem.db.execute("CREATE TABLE IF NOT EXISTS timers(id INTEGER PRIMARY KEY, kind TEXT, label TEXT,"
                           " created REAL, due REAL, done INTEGER DEFAULT 0)")
            mem.db.commit()

    def add(self, kind, secs, label=""):
        if len(self.active()) >= self.MAX:
            raise ValueError(f"already {self.MAX} timers running")
        secs = max(1.0, min(float(secs), 7 * 86400))
        now = self.clock()
        with self.mem.lock:
            cur = self.mem.db.execute("INSERT INTO timers(kind,label,created,due) VALUES(?,?,?,?)",
                                      (kind, label or "", now, now + secs))
            self.mem.db.commit()
            return self.get(cur.lastrowid, locked=True)

    def get(self, tid, locked=False):
        q = "SELECT id,kind,label,created,due,done FROM timers WHERE id=?"
        if locked:
            r = self.mem.db.execute(q, (tid,)).fetchone()
        else:
            with self.mem.lock:
                r = self.mem.db.execute(q, (tid,)).fetchone()
        return self._row(r) if r else None

    @staticmethod
    def _row(r):
        return {"id": r[0], "kind": r[1], "label": r[2], "created": r[3], "due": r[4], "done": bool(r[5])}

    def active(self):
        with self.mem.lock:
            rows = self.mem.db.execute("SELECT id,kind,label,created,due,done FROM timers WHERE done=0 ORDER BY due").fetchall()
        return [self._row(r) for r in rows]

    def cancel(self, what="all"):
        """what = 'all', an id, or words to match in the label ('pasta'). Returns the cancelled timers."""
        act = self.active()
        if what == "all":
            gone = act
        elif isinstance(what, int):
            gone = [t for t in act if t["id"] == what]
        else:
            words = [w for w in re.findall(r"[a-z]+", str(what).lower()) if len(w) > 2]
            gone = [t for t in act if words and any(w in t["label"].lower() for w in words)]
            if not gone and len(act) == 1:
                gone = act                                   # "cancel the timer" with only one running
        with self.mem.lock:
            for t in gone:
                self.mem.db.execute("UPDATE timers SET done=2 WHERE id=?", (t["id"],))
            self.mem.db.commit()
        return gone

    def due(self):
        """Timers whose time has come; they are marked done so each fires once."""
        now = self.clock()
        with self.mem.lock:
            rows = self.mem.db.execute("SELECT id,kind,label,created,due,done FROM timers WHERE done=0 AND due<=? ORDER BY due",
                                       (now,)).fetchall()
            for r in rows:
                self.mem.db.execute("UPDATE timers SET done=1 WHERE id=?", (r[0],))
            self.mem.db.execute("DELETE FROM timers WHERE done!=0 AND due<?", (now - 86400,))
            self.mem.db.commit()
        return [self._row(r) for r in rows]

    def describe(self, t, now=None):
        now = now or self.clock()
        left = fmt_duration(max(0, t["due"] - now))
        name = f"{t['kind']} for {t['label']}" if t["label"] else f"{fmt_duration(t['due'] - t['created'])} {t['kind']}"
        return f"{name}, {left} left"


# ------------------------------------------------------------------ study buddy (pomodoro)
STUDY_START_RX = re.compile(r"\b(?:start|begin|let'?s do|let'?s start|time for)\b.*\b(?:study(?:ing)?|pomodoro|focus)\b"
                            r"|\blet'?s study\b|\bstudy session\b|\bhelp me (?:study|focus)\b|\bi(?:'m| am)? (?:going to |gonna )?study\b", re.I)
STUDY_STOP_RX = re.compile(r"\b(?:stop|end|finish|quit|cancel)\b.*\b(?:study(?:ing)?|pomodoro|session|focus)\b"
                           r"|\bi'?m done studying\b", re.I)
SUBJECT_RX = re.compile(r"\b(?:study(?:ing)?|session|pomodoro|focus(?:ing)?|revise|revising)(?:\s+session)?\s+(?:for\s+(?:my\s+)?|on\s+|about\s+)?"
                        r"(?P<s>(?!for\b|\d)[a-z][a-z \-]{1,40}?)(?:\s+(?:for|now|please|today|with)\b|[.!?]|$)", re.I)
STUDY_FILLER = {"session", "a", "the", "now", "please", "today", "time", "a bit", "it", "with me"}


def parse_study_command(text: str):
    """-> ('start', subject, focus_min or None) | ('stop',) | None"""
    if STUDY_STOP_RX.search(text):
        return ("stop",)
    if not STUDY_START_RX.search(text):
        return None
    subj = ""
    m = SUBJECT_RX.search(text)
    if m:
        subj = m.group("s").strip().lower()
        subj = re.sub(r"^(?:my|some|a|the)\s+", "", subj)
        if subj in STUDY_FILLER or subj.startswith("session"):
            subj = ""
    mins = None
    d = re.search(rf"\bfor\s+({DUR})", text, re.I)
    if d:
        sec = parse_duration(d.group(1))
        if sec:
            mins = max(1, min(120, round(sec / 60)))
    return ("start", subj, mins)


class Study:
    """Focus -> break -> focus ... One object per app; `tick()` returns what just happened, if anything."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.active = False
        self.phase, self.subject, self.ends, self.cycle = None, "", 0.0, 0
        self.focus_min, self.break_min = 25, 5
        self.quiz_question_pending = False

    def start(self, subject, focus_min, break_min):
        self.active, self.phase, self.subject = True, "focus", subject or ""
        self.focus_min, self.break_min = focus_min, break_min
        self.ends, self.cycle = self.clock() + focus_min * 60, 1
        self.quiz_question_pending = False

    def stop(self):
        was = self.active
        self.active, self.phase = False, None
        self.quiz_question_pending = False
        return was

    def tick(self):
        if not self.active or self.clock() < self.ends:
            return None
        if self.phase == "focus":
            self.phase, self.ends = "break", self.clock() + self.break_min * 60
            return "break"
        self.phase, self.ends, self.cycle = "focus", self.clock() + self.focus_min * 60, self.cycle + 1
        self.quiz_question_pending = False
        return "focus"

    def left_s(self):
        return max(0.0, self.ends - self.clock()) if self.active else 0.0

    def status(self):
        if not self.active:
            return None
        return {"phase": self.phase, "subject": self.subject, "ends": self.ends, "cycle": self.cycle,
                "focus_min": self.focus_min, "break_min": self.break_min}

    def prompt_block(self):
        if not self.active:
            return ""
        subj = f" {self.subject}" if self.subject else ""
        left = fmt_duration(self.left_s())
        if self.phase == "focus":
            return (f"Study session: they are meant to be studying{subj} right now, focus block {self.cycle}, {left} left. "
                    "Answer study questions properly and helpfully. For anything off topic, answer in one short sentence, "
                    "then tell them to get back to work, in character.")
        b = (f"Study break: {left} left of the break after focus block {self.cycle}"
             + (f" on {self.subject}" if self.subject else "") + ". Be relaxed.")
        if self.quiz_question_pending:
            b += (" You just asked them a quiz question (it is in the conversation). Judge their answer honestly: say "
                  "plainly if it is right or wrong, give the correct answer if it is wrong, then you may ask one more.")
        return b


# ------------------------------------------------------------------ voice mini games
TWENTY_Q_THINGS = ["a banana", "a toothbrush", "a penguin", "the Eiffel Tower", "a guitar", "a volcano", "a pizza",
                   "a smartphone", "a giraffe", "a bicycle", "the Moon", "an umbrella", "a robot", "a cactus",
                   "a pair of sunglasses", "a cricket bat", "an octopus", "a rubber duck", "a lighthouse", "a cupcake",
                   "a skateboard", "a camel", "a rainbow", "a dragon", "a teapot", "a submarine", "a snowman", "a kite"]
GAMES = {
    "trivia": "Trivia", "twenty_questions": "20 questions", "would_you_rather": "Would you rather",
}
GAME_START_RX = re.compile(r"\b(?:let'?s|can we|wanna|want to|start|play)\b.*?\b(?P<g>trivia|quiz|twenty questions|20 questions|"
                           r"would you rather|a game|game)\b", re.I)
GAME_STOP_RX = re.compile(r"\b(?:stop|end|quit|exit|finish|cancel)\b.*\b(?:game|playing|trivia|quiz|questions|would you rather)\b"
                          r"|\bi quit\b|\bno more (?:games|trivia)\b", re.I)
GIVE_UP_RX = re.compile(r"\bi give up\b|\btell me (?:what it is|the answer)\b", re.I)


def parse_game_command(text: str):
    """-> ('start', game or None, topic) | ('stop',) | None"""
    if GAME_STOP_RX.search(text):
        return ("stop",)
    m = GAME_START_RX.search(text)
    if not m:
        return None
    g = m.group("g").lower()
    game = ("twenty_questions" if "question" in g else "would_you_rather" if "rather" in g
            else "trivia" if g in ("trivia", "quiz") else None)
    topic = ""
    t = re.search(r"\b(?:trivia|quiz)\s+(?:about|on)\s+(?P<t>[a-z0-9 \-]{2,40}?)(?:[.!?]|$)", text, re.I)
    if t:
        topic = t.group("t").strip().lower()
    return ("start", game, topic)


class Game:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.name = None
        self.topic, self.secret, self.turns = "", "", 0

    @property
    def active(self):
        return self.name is not None

    def start(self, name, topic=""):
        self.name, self.topic, self.turns = name, topic or "", 0
        self.secret = self.rng.choice(TWENTY_Q_THINGS) if name == "twenty_questions" else ""

    def stop(self):
        was = self.name
        self.name, self.secret, self.turns = None, "", 0
        return was

    def user_turn(self, text):
        """Count the turn. For 20 questions returns 'won' / 'gave_up' / 'out' when the game ends, else None."""
        if not self.active:
            return None
        self.turns += 1
        if self.name != "twenty_questions":
            return None
        core = re.sub(r"^(?:a|an|the)\s+", "", self.secret.lower())
        if re.search(r"\b" + re.escape(core) + r"s?\b", text.lower()):
            return "won"
        if GIVE_UP_RX.search(text):
            return "gave_up"
        if self.turns >= 20:
            return "out"
        return None

    def status(self):
        if not self.active:
            return None
        return {"name": self.name, "title": GAMES[self.name], "topic": self.topic, "turns": self.turns}

    def prompt_block(self):
        if self.name == "trivia":
            about = f" about {self.topic}" if self.topic else " on mixed topics (science, geography, history, sport, films)"
            return ("Game: you are hosting voice trivia" + about + ". Ask ONE question at a time, with one clear short "
                    "answer, suitable for a teenager. No multiple choice lists. When they answer, say plainly if it is right "
                    "or wrong (never accept a wrong answer to be nice), give the right answer if wrong, keep score out loud "
                    "like 'that's 3 out of 4', then ask the next question. Only ask questions you are sure of.")
        if self.name == "twenty_questions":
            return (f"Game: 20 questions. You have secretly picked: {self.secret}. NEVER say it unless they guess it or "
                    f"give up. They ask yes or no questions; this is question {self.turns} of 20. Answer each with yes, no, "
                    "sometimes or not really, plus a short in-character jab, and say how many questions are left. "
                    "Answer truthfully about the thing.")
        if self.name == "would_you_rather":
            return ("Game: would you rather. Give one funny, PG would-you-rather with two options. When they pick, react "
                    "to their choice in character in one sentence, then give a new one.")
        return ""


# ------------------------------------------------------------------ night hours
def parse_hhmm(s):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def in_window(now: datetime, start: str, end: str) -> bool:
    """True if now is inside start..end (HH:MM), wrapping past midnight (23:00 -> 07:00)."""
    a, b = parse_hhmm(start), parse_hhmm(end)
    if not a or not b or a == b:
        return False
    n = now.hour * 60 + now.minute
    a, b = a[0] * 60 + a[1], b[0] * 60 + b[1]
    return a <= n < b if a < b else (n >= a or n < b)
