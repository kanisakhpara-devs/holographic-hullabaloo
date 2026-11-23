"""PG post-filter and user blocklist. Runs IN ADDITION to the prompt rules.

PG filter: only in content mode 'pg'. Blocklist: in every mode, applied to the
user's text (pre-filter, skip the LLM) and to every model sentence (post-filter).
Tripped sentences are replaced by an in-character deflection.
"""
import itertools, os, re

DATA = os.path.join(os.path.dirname(__file__), "data")


def _load_lines(name):
    path = os.path.join(DATA, name)
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def _word_rx(words):
    parts = []
    for w in words:
        w = w.strip().lower()
        if not w:
            continue
        if w.endswith("*"):
            parts.append(re.escape(w[:-1]) + r"\w*")
        else:
            parts.append(re.escape(w))
    if not parts:
        return None
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I)


# common disguises: f*ck, sh!t, a$$
_LEET = str.maketrans({"!": "i", "1": "i", "$": "s", "@": "a", "0": "o", "3": "e", "*": "u"})


class ContentFilter:
    def __init__(self, blocklist=()):
        self.pg_rx = _word_rx(_load_lines("pg_words.txt"))
        self.deflections = _load_lines("deflections.txt")
        self._cycle = itertools.cycle(self.deflections)
        self.set_blocklist(blocklist)
        self.counts = {"pg_post": 0, "block_pre": 0, "block_post": 0}

    def set_blocklist(self, items):
        if isinstance(items, str):
            items = re.split(r"[,\n]", items)
        self.block_rx = _word_rx([i for i in items if i.strip()])

    def deflection(self):
        return next(self._cycle)

    @staticmethod
    def _variants(text):
        t = text.lower()
        return (t, t.translate(_LEET))

    def is_pg_violation(self, text):
        return bool(self.pg_rx) and any(self.pg_rx.search(v) for v in self._variants(text))

    def is_blocked(self, text):
        return bool(self.block_rx) and any(self.block_rx.search(v) for v in self._variants(text))

    def check_user(self, text):
        """True if the user's text hits the blocklist (then skip the LLM and deflect)."""
        if self.is_blocked(text):
            self.counts["block_pre"] += 1
            return True
        return False

    def check_sentence(self, text, content="pg"):
        """Return None if fine, or a reason string if the sentence must be replaced."""
        if self.is_blocked(text):
            self.counts["block_post"] += 1
            return "blocklist"
        if content == "pg" and self.is_pg_violation(text):
            self.counts["pg_post"] += 1
            return "pg"
        return None
