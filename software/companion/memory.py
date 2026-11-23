"""SQLite memory: people's names, facts told to it, last-conversation summary,
plus optional debug transcripts with auto-delete.

Modes (settings.privacy_mode):
  "faire"  -> keep only names + facts. No transcripts, no summary.
  "debug"  -> also keep transcripts, auto-deleted after TRANSCRIPT_TTL_H hours.
"""
import sqlite3, time, threading

TRANSCRIPT_TTL_H = 24


class Memory:
    def __init__(self, path="companion.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS people(name TEXT PRIMARY KEY, first_seen REAL, last_seen REAL);
            CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, person TEXT, fact TEXT, ts REAL);
            CREATE TABLE IF NOT EXISTS summary(id INTEGER PRIMARY KEY CHECK(id=1), text TEXT, ts REAL);
            CREATE TABLE IF NOT EXISTS transcript(id INTEGER PRIMARY KEY, ts REAL, role TEXT, emotion TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS usage(ts REAL);
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
            """)
            cols = [r[1] for r in self.db.execute("PRAGMA table_info(facts)")]
            if "slot" not in cols:                  # upgrade older databases in place
                self.db.execute("ALTER TABLE facts ADD COLUMN slot TEXT")
            if "secs" not in [r[1] for r in self.db.execute("PRAGMA table_info(usage)")]:
                self.db.execute("ALTER TABLE usage ADD COLUMN secs REAL DEFAULT 0")
            self.db.commit()

    # --- people / facts
    def seen(self, name):
        now = time.time()
        with self.lock:
            self.db.execute("INSERT INTO people VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET last_seen=?",
                            (name, now, now, now))
            self.db.commit()

    def add_fact(self, person, fact, slot=None):
        """Same person + same slot: the newer fact REPLACES the older one. Returns the replaced fact text
        (or None). Without a slot, exact duplicates are skipped."""
        replaced = None
        with self.lock:
            if slot:
                old = self.db.execute("SELECT fact FROM facts WHERE person=? AND slot=?", (person, slot)).fetchall()
                replaced = next((o[0] for o in old if o[0] != fact), None)
                self.db.execute("DELETE FROM facts WHERE person=? AND slot=?", (person, slot))
            elif self.db.execute("SELECT 1 FROM facts WHERE person=? AND fact=?", (person, fact)).fetchone():
                return None
            self.db.execute("DELETE FROM facts WHERE person=? AND fact=?", (person, fact))
            self.db.execute("INSERT INTO facts(person,fact,ts,slot) VALUES(?,?,?,?)", (person, fact, time.time(), slot))
            self.db.commit()
        return replaced

    def forget_matching(self, match, person=None):
        """Delete every fact for which match(fact_text) is true. Returns the deleted facts."""
        with self.lock:
            q, a = "SELECT id,person,fact FROM facts", ()
            if person:
                q, a = q + " WHERE person=?", (person,)
            rows = [r for r in self.db.execute(q, a).fetchall() if match(r[2])]
            for i, _, _ in rows:
                self.db.execute("DELETE FROM facts WHERE id=?", (i,))
            self.db.commit()
        return [(p, f) for _, p, f in rows]

    def rename_person(self, old, new):
        with self.lock:
            self.db.execute("UPDATE facts SET person=? WHERE person=?", (new, old))
            self.db.execute("DELETE FROM people WHERE name=?", (old,))
            self.db.commit()

    def facts(self, person=None, limit=30):
        q, a = "SELECT person,fact FROM facts", ()
        if person:
            q, a = q + " WHERE person=?", (person,)
        with self.lock:
            return self.db.execute(q + " ORDER BY ts DESC LIMIT ?", a + (limit,)).fetchall()

    def people(self):
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT name FROM people ORDER BY last_seen DESC")]

    def people_full(self):
        with self.lock:
            return [{"name": n, "first_seen": a, "last_seen": b} for n, a, b in
                    self.db.execute("SELECT name,first_seen,last_seen FROM people ORDER BY last_seen DESC")]

    def facts_full(self, limit=500):
        with self.lock:
            return [{"id": i, "person": p, "fact": f, "ts": t} for i, p, f, t in
                    self.db.execute("SELECT id,person,fact,ts FROM facts ORDER BY ts DESC LIMIT ?", (limit,))]

    def delete_person(self, name):
        """Removes the person and every fact attributed to them."""
        with self.lock:
            n = self.db.execute("DELETE FROM people WHERE name=?", (name,)).rowcount
            n += self.db.execute("DELETE FROM facts WHERE person=?", (name,)).rowcount
            self.db.commit()
        return n

    def delete_fact(self, fact_id):
        with self.lock:
            n = self.db.execute("DELETE FROM facts WHERE id=?", (int(fact_id),)).rowcount
            self.db.commit()
        return n

    def forget_all(self):
        with self.lock:
            for t in ("people", "facts", "summary"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.commit()

    def export_memory(self):
        return {"people": self.people_full(), "facts": self.facts_full(), "summary": self.summary()}

    # --- summary
    def set_summary(self, text):
        with self.lock:
            self.db.execute("INSERT INTO summary VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET text=?,ts=?",
                            (text, time.time(), text, time.time()))
            self.db.commit()

    def summary(self):
        with self.lock:
            r = self.db.execute("SELECT text FROM summary WHERE id=1").fetchone()
        return r[0] if r else ""

    # --- transcript (debug only)
    def log(self, role, text, emotion="", mode="debug"):
        if mode != "debug":
            return
        with self.lock:
            self.db.execute("INSERT INTO transcript(ts,role,emotion,text) VALUES(?,?,?,?)",
                            (time.time(), role, emotion, text))
            self.db.commit()

    def transcript(self, limit=200):
        with self.lock:
            return self.db.execute("SELECT ts,role,emotion,text FROM transcript ORDER BY ts DESC LIMIT ?",
                                   (limit,)).fetchall()[::-1]

    def retention_hours_left(self, now=None):
        """Hours until the oldest saved transcript line is deleted (None if no transcript)."""
        with self.lock:
            r = self.db.execute("SELECT MIN(ts) FROM transcript").fetchone()
        if not r or r[0] is None:
            return None
        return max(0.0, TRANSCRIPT_TTL_H - ((now or time.time()) - r[0]) / 3600)

    def purge_old(self, now=None):
        cutoff = (now or time.time()) - TRANSCRIPT_TTL_H * 3600
        with self.lock:
            n = self.db.execute("DELETE FROM transcript WHERE ts<?", (cutoff,)).rowcount
            self.db.commit()
        return n

    def wipe_transcripts(self):
        with self.lock:
            self.db.execute("DELETE FROM transcript")
            self.db.commit()

    def enter_faire_mode(self):
        """Switching to Faire mode: drop transcripts + summary immediately."""
        self.wipe_transcripts()
        with self.lock:
            self.db.execute("DELETE FROM summary")
            self.db.commit()

    # --- usage (timestamps only, kept in every privacy mode; no content)
    def log_usage(self, secs=0.0):
        """One row per turn. Returns the row id so the turn's length can be filled in when it ends."""
        with self.lock:
            cur = self.db.execute("INSERT INTO usage(ts,secs) VALUES(?,?)", (time.time(), float(secs)))
            self.db.commit()
            return cur.lastrowid

    def set_usage_secs(self, row_id, secs):
        with self.lock:
            self.db.execute("UPDATE usage SET secs=? WHERE rowid=?", (float(secs), row_id))
            self.db.commit()

    def daily(self, days=7, now=None):
        """Last `days` local calendar days, oldest first: [{date, weekday, minutes, turns}].
        minutes = your speech + its speech, from the stored per-turn lengths."""
        import datetime as _dt
        now = now or time.time()
        today = _dt.date.fromtimestamp(now)
        first = today - _dt.timedelta(days=days - 1)
        start = time.mktime(first.timetuple())
        out = {first + _dt.timedelta(days=i): [0.0, 0] for i in range(days)}
        with self.lock:
            rows = self.db.execute("SELECT ts, COALESCE(secs,0) FROM usage WHERE ts>=?", (start,)).fetchall()
        for ts, secs in rows:
            d = _dt.date.fromtimestamp(ts)
            if d in out:
                out[d][0] += secs
                out[d][1] += 1
        return [{"date": d.isoformat(), "weekday": d.strftime("%a"), "minutes": round(v[0] / 60, 1), "turns": v[1]}
                for d, v in sorted(out.items())]

    def usage(self, days=7, now=None):
        """Returns (cumulative [(day_index, total)], hours[24]) for the last `days` days."""
        now = now or time.time()
        start = now - days * 86400
        with self.lock:
            rows = [r[0] for r in self.db.execute("SELECT ts FROM usage WHERE ts>=? ORDER BY ts", (start,))]
        per_day = [0] * days
        hours = [0] * 24
        for t in rows:
            per_day[min(days - 1, int((t - start) // 86400))] += 1
            hours[time.localtime(t).tm_hour] += 1
        cum, tot = [], 0
        for c in per_day:
            tot += c
            cum.append(tot)
        return cum, hours

    # --- settings
    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def put(self, k, v):
        with self.lock:
            self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=?", (k, str(v), str(v)))
            self.db.commit()
