"""Personas (plain .txt files) and the system prompt builder (prompt section 4.3).

Order: persona, content rule, format rule, answer style rule, few-shot examples,
memory block, time block. Content mode 'unfiltered' can only come from the UI.
"""
import os, re
from datetime import datetime
from .emotions import EMOTIONS

BUNDLED_DIR = os.path.join(os.path.dirname(__file__), "personas")
CUSTOM = "custom"
CUSTOM_MAX = 1200

CONTENT = {
    "pg": "Keep everything PG. No swearing, no sexual content, nothing graphic or scary. Many strangers and kids "
          "are listening. If asked something inappropriate, deflect with a joke in character.",
    "unfiltered": "You may swear mildly and roast harder. Still never produce hate, sexual content, content "
                  "involving minors, self harm instructions or dangerous instructions.",
}

FORMAT_RULE = ("Every single sentence you say must begin with exactly one emotion tag in square brackets, chosen "
               "only from: " + ", ".join(EMOTIONS) + ". For a secret or a dramatic aside you may use [whisper] instead "
               "(it whispers that sentence); use it rarely, at most once per reply. "
               "Never put a tag anywhere except the start of a sentence. "
               "Never use any other square brackets, asterisks, emojis, markdown, lists, stage directions or "
               "parentheses. Write only words that will be spoken aloud.")

_STYLE_TAIL = ("Use spoken English: contractions, no headings, no numbers written as digit lists. Spell out symbols "
               "(say 'percent', not '%'). Do not repeat the question. Do not start two replies in a row with the "
               "same word. Stay in character at all times. You cannot play music or control anything. Timers, reminders, "
               "study sessions and games are run by the app: only say one was set, cancelled or started if a note below "
               "says so. Never pretend.")

HONESTY_RULE = (
    "Honesty rules, more important than being funny: "
    "Your knowledge stops at your training data. For anything recent or that changes (release dates, prices, news, "
    "sports, who currently holds a job), say you are not sure and your info may be old, unless web results are given "
    "below. Never invent names, dates, numbers, books or quotes. "
    "If the person says something false or asks about something that does not exist (a book nobody wrote, an event "
    "that did not happen), say plainly that it is wrong, then joke. Never play along with a false premise. "
    "Do not change your answer just because someone disagrees. Change it only if they give a real reason or source, "
    "and then say what changed your mind. "
    "Never guess anyone's name. Only use a name if it is in the memory section or they just told you. "
    "Answer the actual question first, in plain words, then add the joke.")
LENGTH_RULE = {
    "short": "Reply in 1 to 2 short sentences, under 30 words total, unless the person explicitly asks for a "
             "story, a list or an explanation, in which case use at most 4 sentences. ",
    "normal": "Reply in 1 to 3 short sentences, under 45 words total, unless the person explicitly asks for a "
              "story, a list or an explanation, in which case use at most 6 sentences. ",
    "long": "Reply in up to 6 sentences. Keep each sentence short and easy to say aloud. ",
}
NUM_PREDICT = {"short": 90, "normal": 160, "long": 320}

# worded as a dial on top of the persona, so it doesn't turn every persona into the smug one
SARCASM = {
    0: "Sarcasm dial: 0 of 3. Stay in your character but be warm, with only light teasing.",
    1: "Sarcasm dial: 1 of 3. Stay in your character with a little sarcasm.",
    2: "Sarcasm dial: 2 of 3. Stay in your character with a fair bit of sarcasm.",
    3: "Sarcasm dial: 3 of 3. Stay in your character, maximally sarcastic and deadpan, but still affectionate.",
}
ROAST = "Roast the person you are talking to a little more than usual, playfully and never about protected traits."

# Examples are now per persona (the "Examples:" part of each persona file). Before Nov 25 every persona got the
# same 10 smug examples, and a 4B model copies examples far more than it follows a one line description, so the
# wizard and the hype buddy both came out smug. These 3 are added to every persona: they teach honesty, not tone.
# No example uses a person's name: the old "My name is Riya" example made it call people Riya.
HONESTY_SHOTS = [
    ("What did you think of Phil Knight's biography of Jack Ma?",
     "[suspicious] Phil Knight never wrote one. [neutral] He wrote Shoe Dog, about Nike."),
    ("When did the new iPhone come out?",
     "[confused] Honestly, I'm not sure, my info might be old. [neutral] Best to check online."),
    ("No, you're wrong, the sun goes around the Earth.",
     "[eyeroll] It doesn't. [neutral] Show me real proof and I'll think about it."),
]
FEW_SHOT = HONESTY_SHOTS          # kept for old imports

VOICE_RX = re.compile(r"^\s*voice\s*:\s*([a-z]{2}_[a-z]+)\s*$", re.I)
SPEED_RX = re.compile(r"^\s*speed\s*:\s*([0-9.]+)\s*$", re.I)


def parse_persona(raw: str) -> dict:
    """Persona file -> {text, voice, speed, examples}. Format (only the description is required):

        voice: bm_george              (optional: Kokoro voice for every sentence of this persona)
        speed: 0.95                   (optional: multiplies the speaking speed)
        You are Hullabaloo, ...       (the description, any number of lines)
        Examples:
        User: something they say
        You: [smug] what you answer, with emotion tags
    """
    voice, speed, desc, examples, user = "", 1.0, [], [], None
    in_ex = False
    for line in (raw or "").splitlines():
        if not in_ex and (m := VOICE_RX.match(line)):
            voice = m.group(1).lower()
            continue
        if not in_ex and (m := SPEED_RX.match(line)):
            try:
                speed = max(0.7, min(1.4, float(m.group(1))))
            except ValueError:
                pass
            continue
        if line.strip().lower().rstrip(":") == "examples":
            in_ex = True
            continue
        if in_ex:
            if line.lower().startswith("user:"):
                user = line[5:].strip()
            elif line.lower().startswith("you:") and user:
                examples.append((user, line[4:].strip()))
                user = None
            continue
        desc.append(line)
    return {"text": "\n".join(desc).strip(), "voice": voice, "speed": speed, "examples": examples[:12]}


class PersonaStore:
    """Lists persona .txt files from a user folder (editable, first) and the bundled folder."""

    def __init__(self, user_dir=None):
        self.user_dir = user_dir
        if user_dir:
            os.makedirs(user_dir, exist_ok=True)

    def _dirs(self):
        return [d for d in (self.user_dir, BUNDLED_DIR) if d and os.path.isdir(d)]

    def names(self):
        seen = []
        for d in self._dirs():
            for f in sorted(os.listdir(d)):
                n = f[:-4]
                if f.endswith(".txt") and n not in seen and n != CUSTOM:
                    seen.append(n)
        return seen + [CUSTOM]

    def get(self, name, custom_text=""):
        if name == CUSTOM:
            return (custom_text or "").strip()[:CUSTOM_MAX] or self.get("smug_sarcastic")
        for d in self._dirs():
            p = os.path.join(d, name + ".txt")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return f.read().strip()
        if name != "smug_sarcastic":
            return self.get("smug_sarcastic")
        return "You are Hullabaloo, a smug, sarcastic desk companion."

    def profile(self, name, custom_text=""):
        return parse_persona(self.get(name, custom_text))

    def save(self, name, text):
        if not re.fullmatch(r"[a-z0-9_]{1,40}", name) or name == CUSTOM:
            raise ValueError("persona name must be lowercase letters, digits or underscore")
        if not self.user_dir:
            raise ValueError("no user persona folder")
        text = text.strip()[:CUSTOM_MAX * 2]
        with open(os.path.join(self.user_dir, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")


# kept for old imports
PERSONAS = {n: PersonaStore().get(n) for n in PersonaStore().names() if n != CUSTOM}


def memory_block(people, facts, last_summary=""):
    parts = []
    if people:
        parts.append("People you know: " + ", ".join(people[:8]) + ".")
    if facts:
        parts.append("Things people told you: " + "; ".join(f"{p}: {f}" for p, f in facts[:12]) + ".")
    if last_summary:
        parts.append("Last conversation: " + last_summary.strip())
    if parts:
        parts.append("Use this naturally. Never read it out as a list unprompted.")
    return " ".join(parts)


def time_block(now=None, tz_name="Asia/Kolkata"):
    try:
        from zoneinfo import ZoneInfo
        now = now or datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = now or datetime.now()
    city = "Mumbai" if tz_name in ("Asia/Kolkata", "Asia/Calcutta") else tz_name.split("/")[-1].replace("_", " ")
    return f"It is {now:%A}, {now.day} {now:%B %Y}, {now:%I:%M %p} in {city}."


def build_system_prompt(persona_text: str, content: str = "pg", people=(), facts=(), last_summary: str = "",
                        reply_length: str = "normal", sarcasm_level: int = 2, roast_user: bool = False,
                        now=None, tz_name="Asia/Kolkata", strict_reminder=False, owner="", speaker="",
                        notes=(), web=None, extra=()) -> str:
    # old call style: build_system_prompt("smug_sarcastic", "pg", ...) with a persona NAME
    if persona_text in PERSONAS:
        persona_text = PERSONAS[persona_text]
    prof = parse_persona(persona_text)
    persona = (prof["text"] or "You are Hullabaloo, a desk companion.") + " " + SARCASM.get(int(sarcasm_level), SARCASM[2])
    if roast_user:
        persona += " " + ROAST
    parts = [persona, CONTENT.get(content, CONTENT["pg"]), FORMAT_RULE,
             LENGTH_RULE.get(reply_length, LENGTH_RULE["normal"]) + _STYLE_TAIL, HONESTY_RULE,
             "Examples (copy the personality and tone of these, not the exact words):\n"
             + "\n".join(f"User: {u}\nYou: {a}" for u, a in prof["examples"] + HONESTY_SHOTS)]
    if extra:
        parts += [x for x in extra if x]
    who = []
    if owner:
        who.append(f"Your owner is {owner}, who built you.")
    if speaker:
        who.append(f"Right now you are talking to {speaker}.")
    elif owner:
        who.append(f"Assume you are talking to {owner} unless someone tells you their name.")
    else:
        who.append("You do not know who you are talking to unless they tell you their name.")
    parts.append(" ".join(who))
    mb = memory_block(list(people), list(facts), last_summary)
    if mb:
        parts.append(mb)
    if notes:
        parts.append("Memory changes from the latest message (mention them briefly and correctly in your reply, "
                     "in character): " + " ".join(notes))
    if web is not None:
        parts.append(web)
    parts.append(time_block(now, tz_name))
    if strict_reminder:
        parts.append("Remember: start every sentence with an emotion tag.")
    return "\n\n".join(parts)
