"""Learning names and facts, explicit only (his choice, Nov 22).

A fact is saved only when someone
  - says "remember (that) ...", or
  - states a clear fact about themselves ("my favourite book is ...", "I'm from Pune", "I love chess"),
  - or about someone it already knows ("Ria likes to talk").
There is no background LLM guessing any more: that is what filled memory with junk.

Every fact has a SLOT (person + topic). A newer fact in the same slot replaces the old one, so
"my favourite book is X" followed later by "my favourite book is Y" keeps only Y, and
"I hate pizza" replaces "I love pizza".

Names: the owner's name comes from Settings. Anyone else's name is saved only after they say
"my name is X" (or "call me X") AND confirm it on the next turn ("yes"). "I'm X" / "this is X"
are ignored: they misfire on "I'm tired", and Whisper capitalises random words.

Never stored: health, addresses, phone numbers, passwords, ID numbers, finances, schools.
"""
import re

NAME_RX = re.compile(r"\b(?:my name(?: is|'s)|call me)\s+([A-Za-z][A-Za-z'-]{1,19})", re.I)
YES_RX = re.compile(r"^\W*(yes|yeah|yep|yup|ya|correct|right|that's right|that is right|exactly|sure|uh huh)\b", re.I)
NO_RX = re.compile(r"^\W*(no|nope|nah|wrong|not quite|that's not)\b", re.I)
REMEMBER_RX = re.compile(r"\b(?:please )?remember(?: that)?[,:]?\s+(.{3,120})", re.I)
FORGET_RX = re.compile(r"\bforget(?: that| about)?[,:]?\s+(.{2,80})", re.I)

NOT_NAMES = {"Not", "Just", "So", "Very", "Really", "Fine", "Good", "Okay", "Ok", "Here", "Back", "Sorry", "Tired",
             "Bored", "Sad", "Happy", "Hungry", "Done", "Going", "The", "A", "An", "In", "At", "From", "Hullabaloo",
             "Me", "You", "Him", "Her", "That", "This", "It", "Nothing", "Anything", "Whatever"}

SENSITIVE = re.compile(
    r"\b(diabet\w*|cancer|depress\w*|anxiety|adhd|autis\w*|asthma\w*|allerg\w*|epilep\w*|disease|illness|sick|medic\w*|pills?|therap\w*|inhaler|insulin|injur\w*|disab\w*|condition|syndrome|"
    r"pregnan\w*|hiv|disorder|surgery|hospital|doctor|diagnos\w*|"
    r"address|street|road|lane|apartment|flat no|house no|building|pin ?code|zip|"
    r"phone|mobile number|whatsapp|email|e-mail|@|"
    r"password|passcode|pin\b|otp|login|"
    r"aadhaa?r|passport|pan card|ssn|social security|licen[cs]e number|id number|"
    r"salary|income|bank|account|loan|debt|credit card|debit card|upi|money|rupees|lakh|crore|"
    r"school|class \d+|grade \d+|\d+(st|nd|rd|th) grade|teacher|principal)\b", re.I)
DIGITS = re.compile(r"\d{4,}")
MOOD = re.compile(r"\b(feel\w*|mood|bad day|good day|upset|annoyed|tired|stress\w*)\b", re.I)

# (pattern on first-person text, slot builder, fact builder)
_FAV = re.compile(r"\bmy (?:favou?rite|fav) ([a-z][a-z ]{1,24}?)\s+(?:is|was|would be|are|has to be)\s+(.{2,60})", re.I)
_FROM = re.compile(r"\bi(?: am|'m) from\s+(.{2,40})", re.I)
_LIVE = re.compile(r"\bi live in\s+(.{2,40})", re.I)
_JOB = re.compile(r"\bi work as\s+(?:an? )?(.{2,40})", re.I)
_FEEL = re.compile(r"\bi (?:really |absolutely )?(like|love|enjoy|hate|dislike|can't stand)\s+(.{2,50})", re.I)
_DO = re.compile(r"\bi (play|study|collect|build|make|support|speak)\s+(.{2,50})", re.I)
THIRD = {"like": "likes", "love": "loves", "enjoy": "enjoys", "hate": "hates", "dislike": "dislikes",
         "can't stand": "can't stand", "play": "plays", "study": "studies", "collect": "collects",
         "build": "builds", "make": "makes", "support": "supports", "speak": "speaks"}
# third person, about someone already known: "<Name> likes X", "<Name>'s favourite X is Y"
_P_FAV = re.compile(r"\b([A-Z][a-z]{1,19})'s (?:favou?rite|fav) ([a-z][a-z ]{1,24}?)\s+(?:is|was|are)\s+(.{2,60})")
_P_DO = re.compile(r"\b([A-Z][a-z]{1,19}) (likes|loves|enjoys|hates|plays|studies|collects|builds|is from|lives in)\s+(.{2,50})")


def sensitive(text: str) -> bool:
    return bool(SENSITIVE.search(text) or DIGITS.search(text))


def _tidy(v):
    v = re.split(r"\b(?:and then|but|because|so)\b|[.!?;]", v)[0]
    v = re.sub(r"^(?:a|an|the)\s+", "", v.strip(), flags=re.I)
    return re.sub(r"\s+", " ", v).strip(" ,\"'")


def _key(v):
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()[:40]


def clean_name(n):
    if not isinstance(n, str) or not n.strip():
        return None
    n = n.strip().split()[0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,19}", n):
        return None
    n = n[0].upper() + n[1:].lower()
    return None if n in NOT_NAMES else n


def first_person_facts(text):
    """-> [(slot, fact)] stated by the speaker about themselves."""
    out = []
    for m in _FAV.finditer(text):
        what, val = _key(m.group(1)), _tidy(m.group(2))
        if val:
            out.append(("favorite " + what, f"favorite {what} is {val}"))
    for rx, slot, verb in ((_FROM, "from", "is from"), (_LIVE, "lives in", "lives in"), (_JOB, "job", "works as")):
        m = rx.search(text)
        if m and _tidy(m.group(1)):
            out.append((slot, f"{verb} {_tidy(m.group(1))}"))
    for verb, what in _FEEL.findall(text):
        w = _tidy(what)
        if w:                                     # like/love/hate the same thing share a slot: newest wins
            out.append(("feels about " + _key(w), f"{THIRD[verb.lower()]} {w}"))
    for verb, what in _DO.findall(text):
        w = _tidy(what)
        if w:
            out.append((verb.lower() + " " + _key(w), f"{THIRD[verb.lower()]} {w}"))
    return [(s, f) for s, f in out if ok_fact(f)][:3]


def third_person_facts(text, known):
    """-> [(person, slot, fact)] only for names it already knows."""
    known = {k.lower(): k for k in known}
    out = []
    for name, what, val in _P_FAV.findall(text):
        if name.lower() in known and _tidy(val):
            w = _key(what)
            out.append((known[name.lower()], "favorite " + w, f"favorite {w} is {_tidy(val)}"))
    for name, verb, what in _P_DO.findall(text):
        if name.lower() in known and _tidy(what):
            w = _tidy(what)
            slot = "feels about " + _key(w) if verb in ("likes", "loves", "enjoys", "hates") else verb + " " + _key(w)
            out.append((known[name.lower()], slot, f"{verb} {w}"))
    return [(p, s, f) for p, s, f in out if ok_fact(f)][:3]


def to_third_person(s):
    s = _tidy(s)
    rep = [(r"\bi am\b", "is"), (r"\bi'm\b", "is"), (r"\bmy\b", "their"), (r"\bme\b", "them"), (r"\bmine\b", "theirs"),
           (r"\bi\b", "they")]
    for a, b in rep:
        s = re.sub(a, b, s, flags=re.I)
    return s


def remember_request(text):
    """'remember that ...' -> [(slot, fact)]. Uses the fact patterns if they match, else keeps it as a note."""
    m = REMEMBER_RX.search(text)
    if not m:
        return None
    body = m.group(1)
    facts = first_person_facts(body)
    if facts:
        return facts
    note = to_third_person(body)
    if not ok_fact(note, note_ok=True):
        return []
    return [("note " + _key(note)[:24], note)]


def forget_request(text):
    m = FORGET_RX.search(text)
    if not m:
        return None
    return _tidy(m.group(1))


def ok_fact(f, note_ok=False):
    if not f or len(f) > 90 or sensitive(f) or MOOD.search(f):
        return False
    return True


def words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower())) - {"the", "a", "an", "is", "my", "their", "that", "about", "to"}


def matches(query, fact):
    """forget: does this stored fact match what they asked to forget?"""
    q, f = words(query), words(fact)
    return bool(q) and len(q & f) / len(q) >= 0.6


def is_duplicate(fact, existing):
    a = re.sub(r"\W+", " ", fact.lower()).strip()
    return any(a == re.sub(r"\W+", " ", e.lower()).strip() for e in existing)


# kept for old callers: the regex pass now means first-person facts, no name guessing
def regex_pass(text):
    m = NAME_RX.search(text)
    return (clean_name(m.group(1)) if m else None), [f for _, f in first_person_facts(text)]
