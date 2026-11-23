"""Voice-loop engine. Orchestrates: wake -> listen -> STT -> LLM -> TTS -> device.

Pipeline for one turn (all stages run at the same time):
    LLM token stream -> TagStream -> sentence queue -> TTS -> audio queue -> playback + visemes
so sentence 1 is spoken while the model is still writing sentence 2.

Rules baked in:
 - Mic audio is DROPPED while THINKING/SPEAKING (no self-hearing).
 - Button press while THINKING/SPEAKING cuts the reply off (INTERRUPTED 400 ms -> LISTENING).
 - Content mode always boots PG; 'unfiltered' only via set_settings(from_ui=True).
 - privacy_mode 'faire' keeps only names + facts; 'debug' also keeps transcripts (24 h TTL).
"""
import asyncio, collections, logging, math, re, threading, time
from .states import State, StateMachine, STATE_FACE
from .emotions import parse_tagged, EMOTIONS, SpeechMap, shape_text, face_for, whisperize, WHISPER
from .textproc import TagStream, FALLBACK
from .visemes import build_timeline
from .memory import Memory
from .persona import build_system_prompt, PersonaStore, NUM_PREDICT
from .safety import ContentFilter
from .adapters.base import NullAudioOut

log = logging.getLogger("hullabaloo.engine")

from .settings import Settings, DEFAULTS
from . import learn, websearch

# STT outputs Whisper invents on silence/noise
HALLUCINATIONS = {"thanks for watching", "thank you for watching", "you", "thank you", "bye", "subtitles by",
                  "please subscribe", "thanks for watching!"}

INTERRUPT_HOLD_S = 0.4
FACE_RETURN_S = 0.6
HISTORY_KEEP = 8

_STOP = object()     # sentinel: interrupted while waiting


def stt_reject(text: str) -> bool:
    t = (text or "").strip().lower().strip(" .!?,")
    return not t or t in HALLUCINATIONS or not re.search(r"[a-z0-9]", t)


class Engine:
    def __init__(self, stt, llm, tts, device, memory: Memory, emit=None, realtime=1.0,
                 audio=None, speech_map=None, personas=None, content_filter=None, settings_export=None,
                 extract_facts=True):
        self.stt, self.llm, self.tts, self.dev, self.mem = stt, llm, tts, device, memory
        self.audio = audio or NullAudioOut()
        self.speech = speech_map or SpeechMap()
        self.personas = personas or PersonaStore()
        self.emit = emit or (lambda e: None)
        self.realtime = realtime          # 1.0 real time; 0 = instant (tests)
        self.state_face = {s: f for s, f in STATE_FACE.items()}
        self.sm = StateMachine(self._on_state, State.DISCONNECTED if not device.connected else State.SLEEPING)
        self.settings = Settings(memory, settings_export)   # content is always 'pg' here
        self.extract_facts = extract_facts
        self._extract_task = None
        self.setting_hooks = []           # callables(applied: dict) registered by the server
        self.filter = content_filter or ContentFilter(self.settings["blocklist"])
        self.history = []
        self.speaker = None               # person who confirmed their name this conversation (else the owner)
        self.pending_name = None          # heard "my name is X", waiting for "yes"
        self.turn_notes = []              # what memory did with the latest message (told to the model)
        self.turn_web = None              # web results block for the latest message
        self._interrupt = asyncio.Event()
        self._busy = False
        self._t_button = None
        self._face_timer = None
        self._loop = None
        self._loop_thread = None
        self.last_activity = time.time()
        self.latencies = collections.deque(maxlen=20)
        self.counters = {"untagged_replies": 0, "tag_retries": 0, "fallbacks": 0, "mic_dropped": 0,
                         "stt_rejected": 0, "interrupts": 0}
        self.last_interrupt_ms = None
        self._selftest_stop = False
        self._selftest_running = False
        self.mic_test = False           # wizard: transcribe utterances and report them, no reply
        self._apply_live(dict(self.settings))
        device.on_event = self._on_device_event_ts
        self.dev.set_power(self.sm.state not in (State.SLEEPING, State.DISCONNECTED))

    # ---------- plumbing
    def attach_loop(self, loop=None):
        self._loop = loop or asyncio.get_running_loop()
        self._loop_thread = threading.get_ident()

    def _on_state(self, old, new):
        self.emit({"type": "state", "state": new.value, "prev": old.value})
        if old == State.SPEAKING and new == State.LISTENING:
            self._schedule_face_return()      # face holds the last emotion, then neutral
        elif new != State.SPEAKING:
            self._face(self.state_face[new])
        self.dev.set_power(new not in (State.SLEEPING, State.DISCONNECTED))

    def _schedule_face_return(self):
        self._cancel_face_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._face(self.state_face[State.LISTENING])
            return

        def back():
            self._face_timer = None
            if self.sm.state == State.LISTENING:
                self._face(self.state_face[State.LISTENING])
        self._face_timer = loop.call_later(FACE_RETURN_S * self.realtime, back)

    def _cancel_face_timer(self):
        if self._face_timer:
            self._face_timer.cancel()
            self._face_timer = None

    def _face(self, emo):
        emo = face_for(emo)                       # [whisper] shows the suspicious face
        self._cancel_face_timer()
        self.dev.set_face(emo)
        self.emit({"type": "face", "emotion": emo})

    def _mouth(self, v):
        self.dev.set_mouth(v)
        self.emit({"type": "mouth", "viseme": v})

    def _touch(self):
        self.last_activity = time.time()

    # ---------- device events (may arrive on the serial read thread)
    def _on_device_event_ts(self, e):
        if self._loop and self._loop.is_running() and threading.get_ident() != self._loop_thread:
            self._loop.call_soon_threadsafe(self._on_device_event, e)
        else:
            self._on_device_event(e)

    def _on_device_event(self, e):
        t = e.get("type")
        if t == "link":
            self.emit({"type": "device_link", "connected": e["connected"], "device": self.dev.status()})
            if not e["connected"]:
                self._selftest_stop = True
                self._cut_audio()
                self._interrupt.set()
                self.sm.to(State.DISCONNECTED, force=True)
            else:
                self.settings["content"] = "pg"       # every (re)connect forces PG
                if self.sm.state == State.DISCONNECTED:
                    self.sm.to(State.SLEEPING, force=True)
                self.dev.set_power(self.sm.state not in (State.SLEEPING, State.DISCONNECTED))
                self.dev.set_brightness(self.settings["device_brightness_cap"])
                self._face(self.state_face[self.sm.state])
                self.emit({"type": "settings", "settings": dict(self.settings)})
        elif t == "proximity" and e.get("near") and self.settings["proximity_wake"]:
            self.wake("proximity")
        elif t == "button":
            self.button()
        elif t in ("rotor", "brightness_ack"):
            self.emit({**e, "type": "device_" + t})

    # ---------- inputs
    def wake(self, source="button"):
        if self.sm.state == State.INTERRUPTED:
            self.sm.to(State.LISTENING)
            self._touch()
            return True
        if self.sm.state != State.SLEEPING:
            return False
        self.sm.to(State.WAKING)
        self.emit({"type": "wake", "source": source})
        self.sm.to(State.LISTENING)
        self._touch()
        if hasattr(self.llm, "warm") and self._loop:
            asyncio.ensure_future(self._safe_warm())
        return True

    async def _safe_warm(self):
        try:
            await self.llm.warm()
        except Exception as ex:                 # warming is best effort
            log.debug("warm failed: %s", ex)

    def wake_word_heard(self):
        if self.settings.get("mic_mode") == "wake" and self.sm.state in (State.SLEEPING, State.LISTENING):
            self.wake("wake_word")

    def _cut_audio(self):
        """Instant stop: audio off and mouth closed right now, the turn task cleans up after."""
        try:
            self.audio.stop()
        except Exception as ex:
            log.warning("audio stop failed: %s", ex)
        self._mouth("closed")

    def button(self):
        """One button, three meanings depending on state."""
        s = self.sm.state
        if s in (State.THINKING, State.SPEAKING):
            self._t_button = time.monotonic()
            self._cut_audio()
            self._interrupt.set()
            self.last_interrupt_ms = (time.monotonic() - self._t_button) * 1000
            self.counters["interrupts"] += 1
            return "interrupted"
        if s == State.SLEEPING:
            self.wake("button")
            return "woke"
        if s == State.INTERRUPTED:
            self.sm.to(State.LISTENING)
            return "listening"
        return "noop"

    def sleep(self):
        if self.sm.state in (State.LISTENING, State.INTERRUPTED, State.WAKING):
            self._finish_conversation()
            self.sm.to(State.SLEEPING)

    def mic_open(self) -> bool:
        return self.sm.state == State.LISTENING and not self._busy

    def drop_mic(self):
        self.counters["mic_dropped"] += 1
        self.emit({"type": "mic_dropped", "state": self.sm.state.value, "count": self.counters["mic_dropped"]})

    async def on_audio(self, audio: bytes):
        """One finished utterance (from push-to-talk release or VAD end)."""
        t0 = time.monotonic()
        if not self.mic_open():
            self.drop_mic()
            return None
        self._busy = True
        try:
            self._last_utt_s = len(audio) / 32000.0       # PCM16 16 kHz mono: for minutes-talked usage
            text = await asyncio.to_thread(self.stt.transcribe, audio)
            stt_ms = (time.monotonic() - t0) * 1000
            if stt_reject(text):
                self.counters["stt_rejected"] += 1
                return None
            if self.mic_test:
                self.emit({"type": "mic_test", "text": text, "stt_ms": round(stt_ms)})
                self._touch()
                return None
            return await self._turn(text, t0=t0, stt_ms=stt_ms, source="voice")
        finally:
            self._busy = False

    async def on_text(self, text: str):
        """Typed input from the UI (also used by tests)."""
        if self.sm.state in (State.SLEEPING, State.INTERRUPTED):
            self.wake("text")
        if not self.mic_open() or not text.strip():
            return None
        self._busy = True
        try:
            return await self._turn(text.strip(), source="text")
        finally:
            self._busy = False

    def speech_for(self, emo):
        if emo == WHISPER:                        # slower, a beat before, based on the suspicious style
            return {**self.speech_for("suspicious"), "speed": 0.9, "pause_ms": 300, "whisper": True}
        return {**self.speech.get(emo), **self.settings["voice_overrides"].get(emo, {})}

    async def preview(self, text, emotion):
        """Settings 'Preview' button: speak one line in an emotion and show the face."""
        if self._busy or self.sm.state in (State.THINKING, State.SPEAKING):
            return False
        self._busy = True
        try:
            self._interrupt.clear()
            st = self.speech_for(emotion)
            sp = await asyncio.to_thread(self.tts.speak, text, st["voice"],
                                         st["speed"] * float(self.settings["tts_speed_scale"]))
            self._face(emotion)
            self.emit({"type": "say", "emotion": emotion, "text": text, "duration": sp.duration_s, "preview": True})
            self.audio.play(sp.audio, sp.sample_rate)
            await self._play_timeline(build_timeline(sp.phonemes, sp.duration_s, times=sp.times), sp.duration_s)
            self._mouth("closed")
            self._face(self.state_face[self.sm.state])
            return True
        finally:
            self._busy = False

    # ---------- prompt / options
    def system_prompt(self, strict=False):
        s = self.settings
        mode = s["privacy_mode"]
        return build_system_prompt(
            self.personas.get(s["persona"], s["custom_persona_text"]), s["content"],
            self.mem.people()[:8], self.mem.facts(limit=12), self.mem.summary() if mode == "debug" else "",
            reply_length=s["reply_length"], sarcasm_level=s["sarcasm_level"], roast_user=s["roast_user"],
            tz_name=s["timezone"], strict_reminder=strict, owner=s.get("owner_name", ""),
            speaker=self.speaker or "", notes=self.turn_notes, web=self.turn_web)

    def llm_options(self):
        return {"temperature": float(self.settings["temperature"]), "top_p": 0.95, "repeat_penalty": 1.1,
                "num_predict": NUM_PREDICT.get(self.settings["reply_length"], 160), "num_ctx": 4096}

    # ---------- the turn
    async def _wait(self, aw):
        """Await aw unless an interrupt comes first (then _STOP)."""
        if self._interrupt.is_set():
            if asyncio.iscoroutine(aw):
                aw.close()
            return _STOP
        task = asyncio.ensure_future(aw)
        stop = asyncio.ensure_future(self._interrupt.wait())
        done, _ = await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            stop.cancel()
            return task.result()
        task.cancel()
        return _STOP

    async def _produce(self, user_text, sent_q, lat, t_llm):
        """Never hangs the turn: any LLM error becomes an in-character line + end marker."""
        try:
            await self._produce_inner(user_text, sent_q, lat, t_llm)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log.error("LLM failed: %s", ex)
            self.counters["llm_errors"] = self.counters.get("llm_errors", 0) + 1
            self.emit({"type": "error", "where": "llm", "message": str(ex)})
            await sent_q.put(("confused", "My brain is not answering. Is Ollama running?"))
            await sent_q.put(None)

    async def _produce_inner(self, user_text, sent_q, lat, t_llm):
        """LLM stream -> TagStream -> filters -> sentence queue. Retries once if untagged."""
        content = self.settings["content"]
        hist = self.history[-HISTORY_KEEP:]
        put_any = False

        async def put(emo, s):
            nonlocal put_any
            if not put_any:
                lat["llm_first_sentence_ms"] = round((time.monotonic() - t_llm) * 1000)
            put_any = True
            await sent_q.put((emo, s))

        async def put_deflection():
            ts = TagStream()
            for e, s in ts.feed(self.filter.deflection()) + ts.flush():
                await put(e, s)

        if self.filter.check_user(user_text):
            await put_deflection()
            await sent_q.put(None)
            return

        for attempt in (0, 1):
            ts = TagStream()
            retry = False
            raw = []
            agen = self.llm.stream(self.system_prompt(strict=attempt == 1), hist, user_text, self.llm_options())
            try:
                async for tok in agen:
                    raw.append(tok)
                    self.emit({"type": "llm_token", "text": tok})
                    ready = ts.feed(tok)
                    if ready and not put_any and not ts.saw_tag and attempt == 0:
                        retry = True
                        break
                    if await self._emit_sentences(ready, put, put_deflection, content):
                        return await sent_q.put(None)
                if not retry:
                    ready = ts.flush(truncated=getattr(self.llm, "last_done_reason", None) == "length")
                    if ready and not put_any and not ts.saw_tag and attempt == 0:
                        retry = True
            finally:
                await agen.aclose()
            if self.settings["privacy_mode"] == "debug":
                log.debug("raw model output (attempt %d): %s", attempt, "".join(raw))
            if retry:
                self.counters["tag_retries"] += 1
                log.info("reply had no emotion tags, retrying with a stricter reminder")
                continue
            if (put_any or ready) and not ts.saw_tag:
                self.counters["untagged_replies"] += 1
                log.warning("reply still untagged after retry, spoken as neutral")
            if await self._emit_sentences(ready, put, put_deflection, content):
                return await sent_q.put(None)
            break
        if not put_any:
            self.counters["fallbacks"] += 1
            await put(*FALLBACK)
        await sent_q.put(None)

    async def _emit_sentences(self, ready, put, put_deflection, content):
        """Put sentences, or a deflection if a filter trips. True = stop the reply here."""
        for emo, s in ready:
            if self.filter.check_sentence(s, content):
                await put_deflection()
                return True
            await put(emo, s)
        return False

    async def _synth(self, sent_q, audio_q, lat):
        first = True
        while True:
            item = await sent_q.get()
            if item is None:
                await audio_q.put(None)
                return
            emo, s = item
            st = self.speech_for(emo)
            t = time.monotonic()
            try:
                sp = await asyncio.to_thread(self.tts.speak, shape_text(emo, s), st["voice"],
                                             min(1.6, max(0.55, st["speed"] * float(self.settings["tts_speed_scale"]))))
                if st.get("whisper") and getattr(sp, "audio", None):
                    sp.audio = whisperize(sp.audio, sp.sample_rate)
            except Exception as ex:
                log.error("TTS failed: %s", ex)
                self.emit({"type": "error", "where": "tts", "message": str(ex)})
                continue
            if first:
                lat["tts_first_chunk_ms"] = round((time.monotonic() - t) * 1000)
                first = False
            await audio_q.put((emo, s, sp))

    async def _turn(self, user_text: str, t0=None, stt_ms=0.0, source="text"):
        t0 = t0 or time.monotonic()
        self._touch()
        self._interrupt.clear()
        if self._extract_task and not self._extract_task.done():
            self._extract_task.cancel()          # the GPU is needed for the reply now
        mode = self.settings["privacy_mode"]
        self.mem.log("user", user_text, mode=mode)
        self.emit({"type": "transcript", "role": "user", "text": user_text})
        self._learn(user_text)
        await self._maybe_search(user_text)
        usage_row = self.mem.log_usage()
        heard_s = getattr(self, "_last_utt_s", 0.0) if source != "text" else 0.0
        self._last_utt_s = 0.0
        self.sm.to(State.THINKING)

        lat = {"source": source, "stt_ms": round(stt_ms), "llm_first_sentence_ms": None,
               "tts_first_chunk_ms": None, "total_ms": None}
        sent_q, audio_q = asyncio.Queue(), asyncio.Queue(maxsize=2)
        producer = asyncio.ensure_future(self._produce(user_text, sent_q, lat, time.monotonic()))
        synth = asyncio.ensure_future(self._synth(sent_q, audio_q, lat))
        spoken, prev_emo, interrupted = [], None, False
        talk_s = 0.0
        try:
            while True:
                item = await self._wait(audio_q.get())
                if item is _STOP:
                    interrupted = True
                    break
                if item is None:
                    break
                emo, s, sp = item
                if prev_emo is not None:          # pause after the previous sentence (not after the last)
                    if await self._sleep(self.speech_for(prev_emo)["pause_ms"] / 1000):
                        interrupted = True
                        break
                if self.sm.state == State.THINKING:
                    self.sm.to(State.SPEAKING)
                self._face(emo)
                self.emit({"type": "say", "emotion": emo, "text": s, "duration": sp.duration_s,
                           "word_times": getattr(sp, "word_times", None),
                           "offset_ms": self.settings.get("lipsync_offset_ms", 0)})
                self.audio.play(sp.audio, sp.sample_rate)
                if lat["total_ms"] is None:
                    lat["total_ms"] = round((time.monotonic() - t0) * 1000)
                    self._record_latency(lat)
                tl = build_timeline(sp.phonemes, sp.duration_s, times=sp.times)
                t_play = time.monotonic()
                ok = await self._play_timeline(tl, sp.duration_s)
                self._mouth("closed")
                if not ok:
                    interrupted = True
                    # keep the words that were actually heard (by elapsed share of the audio)
                    frac = (time.monotonic() - t_play) / max(1e-3, sp.duration_s * (self.realtime or 1))
                    words = s.split()
                    heard = " ".join(words[:math.ceil(len(words) * min(1.0, frac))]) if frac > 0.1 else ""
                    if heard:
                        spoken.append((emo, heard.rstrip(".,!?;: ") + "..."))
                    talk_s += min(1.0, frac) * sp.duration_s
                    break
                spoken.append((emo, s))
                talk_s += sp.duration_s
                prev_emo = emo
        finally:
            for t in (producer, synth):
                t.cancel()
            await asyncio.gather(producer, synth, return_exceptions=True)
        if interrupted or self._interrupt.is_set():
            self.mem.set_usage_secs(usage_row, heard_s + talk_s)
            return await self._interrupted(user_text, spoken)
        said = " ".join(s for _, s in spoken)
        self._remember_turn(user_text, spoken)
        self.mem.log("assistant", said, emotion=spoken[0][0] if spoken else "", mode=mode)
        self.emit({"type": "transcript", "role": "assistant", "text": said,
                   "emotions": [e for e, _ in spoken]})
        self.sm.to(State.LISTENING)          # mic reopens only now
        self._touch()
        self._schedule_extract(user_text)
        self.mem.set_usage_secs(usage_row, heard_s + talk_s)
        return said

    def _record_latency(self, lat):
        rec = {"ts": time.time(), **lat}
        self.latencies.append(rec)
        log.info("latency %s", rec)
        self.emit({"type": "latency", **rec})

    def _remember_turn(self, user_text, spoken, marker=None):
        reply = " ".join(f"[{e}] {s}" for e, s in spoken)
        if marker:
            reply = (reply + "\n" + marker).strip()
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-2 * HISTORY_KEEP:]

    async def _sleep_real(self, secs):
        """Interruptible sleep in real seconds. True if interrupted."""
        if secs <= 0:
            return self._interrupt.is_set()
        try:
            await asyncio.wait_for(self._interrupt.wait(), secs)
            return True
        except asyncio.TimeoutError:
            return False

    async def _sleep(self, secs):
        """Interruptible sleep in scaled time (realtime=0 in tests means instant)."""
        return await self._sleep_real(secs * self.realtime)

    async def _play_timeline(self, tl, dur):
        """Walk the viseme timeline in (scaled) real time. False if interrupted.
        Starts when playback starts, shifted by output latency + lipsync_offset_ms."""
        offset = getattr(self.audio, "output_latency_s", 0.0) + float(self.settings["lipsync_offset_ms"]) / 1000
        t0 = time.monotonic()
        for t, v in tl:
            if await self._sleep_real(max(0.0, t + offset) * self.realtime - (time.monotonic() - t0)):
                return False
            self._mouth(v)
        if await self._sleep_real(dur * self.realtime - (time.monotonic() - t0)):
            return False
        return not self._interrupt.is_set()

    async def _interrupted(self, user_text, spoken):
        self._cut_audio()
        if spoken:
            marker = f'[you were interrupted after: "{spoken[-1][1]}"]'
        else:
            marker = "[you were interrupted before saying anything]"
        self._remember_turn(user_text, spoken, marker)
        said = " ".join(s for _, s in spoken)
        if said:
            self.mem.log("assistant", said + " (interrupted)", emotion=spoken[0][0], mode=self.settings["privacy_mode"])
        if self.sm.state == State.DISCONNECTED:
            return None
        self.sm.to(State.INTERRUPTED)
        self.emit({"type": "interrupted", "said_so_far": said})
        await asyncio.sleep(INTERRUPT_HOLD_S * self.realtime)
        if self.sm.state == State.INTERRUPTED:
            self.sm.to(State.LISTENING)      # mic reopens; user is now talking
        self._interrupt.clear()
        self._touch()
        return None

    # ---------- memory (explicit only: see learn.py)
    def who(self):
        return self.speaker or self.settings.get("owner_name") or "you"

    def _save(self, person, slot, fact, notes):
        replaced = self.mem.add_fact(person, fact, slot)
        if person != "you":
            self.mem.seen(person)
        notes.append(f"Saved about {person}: {fact}." + (f" This replaced the old '{replaced}'." if replaced else ""))
        self.emit({"type": "memory", "kind": "fact", "value": f"{person}: {fact}", "replaced": replaced})

    def _set_speaker(self, name):
        self.speaker = name
        self.mem.seen(name)
        self.emit({"type": "memory", "kind": "person", "value": name})

    def _learn(self, text):
        """Explicit learning only. Fills self.turn_notes so the reply says what was saved."""
        notes, owner = [], self.settings.get("owner_name") or ""
        if self.pending_name:
            p, self.pending_name = self.pending_name, None
            if learn.YES_RX.search(text):
                self._set_speaker(p)
                notes.append(f"They confirmed their name is {p}. Saved it.")
            elif learn.NO_RX.search(text):
                notes.append(f"They said '{p}' was wrong. Nothing saved. Ask them to say their name again.")
        m = learn.NAME_RX.search(text)
        if m:
            n = learn.clean_name(m.group(1))
            if n and owner and n.lower() == owner.lower():
                self.speaker = None                       # it's the owner
                notes.append(f"They said they are {owner}, your owner.")
            elif n:
                self.pending_name = n
                notes.append(f"You heard the name '{n}', but it might be misheard. Ask them to confirm it "
                             f"(is your name {n}?). Do not use or save it until they say yes.")
        q = learn.forget_request(text)
        if q is not None:
            gone = self.mem.forget_matching(lambda f: learn.matches(q, f))
            if gone:
                notes.append("Deleted from memory: " + "; ".join(f"{p}: {f}" for p, f in gone) + ".")
                self.emit({"type": "memory", "kind": "forgot", "value": len(gone)})
            else:
                notes.append(f"They asked you to forget '{q}', but nothing in memory matched. Say so.")
            self.turn_notes = notes
            return
        rem = learn.remember_request(text)
        if rem == []:
            notes.append("They asked you to remember something private (health, address, money, school, numbers). "
                         "Say you won't keep that kind of thing.")
        for slot, fact in (rem if rem is not None else learn.first_person_facts(text)):
            self._save(self.who(), slot, fact, notes)
        known = self.mem.people() + ([owner] if owner else [])
        for person, slot, fact in learn.third_person_facts(text, known):
            self._save(person, slot, fact, notes)
        self.turn_notes = notes

    async def _maybe_search(self, text):
        self.turn_web = None
        if not self.settings.get("web_search") or not websearch.needs_search(text):
            return
        self.emit({"type": "web_search", "query": text[:200]})
        try:
            res = await asyncio.wait_for(asyncio.to_thread(websearch.search, text), 4.0)
        except Exception:
            res = []
        self.turn_web = websearch.block(res)
        self.emit({"type": "web_results", "count": len(res)})

    def _schedule_extract(self, user_text):
        """Background LLM fact guessing was removed (it saved junk). Kept as a no-op for old callers."""
        return

    def _finish_conversation(self):
        hist, self.history, self.speaker, self.pending_name = self.history, [], None, None
        if self.settings["privacy_mode"] != "debug" or not hist:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return                           # no loop (sync caller): skip the summary
        asyncio.ensure_future(self._summarize(hist))

    async def _summarize(self, hist):
        convo = " | ".join(f"{h['role']}: {h['content']}" for h in hist[-10:])
        try:
            s = await asyncio.to_thread(self.llm.chat, "Summarise this conversation in one short sentence, no tags.",
                                        [], convo, {"temperature": 0.3, "num_predict": 60})
            s = re.sub(r"\[[^\]]*\]\s*", "", s or "").strip()
            if s and self.settings["privacy_mode"] == "debug":
                self.mem.set_summary(s.split("\n")[0][:200])
        except Exception as ex:
            log.warning("summary failed: %s", ex)

    # ---------- idle / settings
    async def idle_loop(self):
        if not self._loop:
            self.attach_loop()
        last_purge = 0.0
        while True:
            await asyncio.sleep(1.0)
            if (self.sm.state == State.LISTENING and not self._busy
                    and time.time() - self.last_activity > self.settings["idle_timeout_s"]):
                self.sleep()
            if time.time() - last_purge >= 60:
                self.mem.purge_old()
                last_purge = time.time()

    def set_settings(self, patch: dict, from_ui: bool = False):
        """Validate + apply. Returns {key: error} for rejected keys (empty if all fine)."""
        patch = dict(patch or {})
        pre = {}
        if "persona" in patch and patch["persona"] not in self.personas.names():
            pre["persona"] = "no such persona file"
            patch.pop("persona")
        applied, errors = self.settings.update_from(patch, from_ui=from_ui)
        errors.update(pre)
        if errors:
            log.info("settings rejected: %s", errors)
        if applied:
            self._apply_live(applied)
        self.emit({"type": "settings", "settings": dict(self.settings)})
        return errors

    def _apply_live(self, applied):
        if applied.get("owner_name"):                 # facts saved as "you" before the name was set
            self.mem.rename_person("you", applied["owner_name"])
        if applied.get("privacy_mode") == "faire":
            self.mem.enter_faire_mode()
        if "blocklist" in applied and hasattr(self, "filter"):
            self.filter.set_blocklist(applied["blocklist"])
        if "emotion_map" in applied:
            self.state_face = {s: f for s, f in STATE_FACE.items()}
            for st, emo in applied["emotion_map"].items():
                self.state_face[State(st)] = emo
        if "device_brightness_cap" in applied:
            self.dev.set_brightness(applied["device_brightness_cap"])
        if "log_level" in applied:
            logging.getLogger("hullabaloo").setLevel(applied["log_level"].upper())
        for hook in self.setting_hooks:
            try:
                hook(applied)
            except Exception as ex:
                log.warning("setting hook failed: %s", ex)

    # ---------- device: self test, swap
    async def selftest(self, step_s: float = 1.0):
        """Diagnostics loopback: all 12 faces, then all 6 mouth shapes, one per step_s, straight to the
        device (and the UI preview). Refused while a turn is running. Stops if the link drops."""
        if self._busy or self._selftest_running or self.sm.state in (State.THINKING, State.SPEAKING, State.DISCONNECTED):
            return False
        self._busy = self._selftest_running = True
        self._selftest_stop = False
        steps = [("face", e) for e in EMOTIONS] + [("mouth", v) for v in ("ah", "oh", "ee", "oo", "fv", "closed")]
        done = 0
        try:
            self.dev.set_power(True)
            for i, (kind, name) in enumerate(steps):
                if self._selftest_stop or not self.dev.connected:
                    break
                (self._face if kind == "face" else self._mouth)(name)
                self.emit({"type": "selftest", "step": i + 1, "total": len(steps), "what": kind, "name": name})
                done = i + 1
                await asyncio.sleep(step_s * self.realtime)
        finally:
            self._mouth("closed")
            if self.dev.connected:
                self.dev.set_power(self.sm.state not in (State.SLEEPING, State.DISCONNECTED))
                self._face(self.state_face[self.sm.state])
            self._busy = self._selftest_running = False
            self.emit({"type": "selftest", "step": done, "total": len(steps), "finished": True,
                       "completed": done == len(steps)})
        return done == len(steps)

    async def calibrate_beep(self):
        """Settings 'calibrate': play a beep and flash the mouth shape ah at the moment the beep should be
        heard (output latency + lipsync offset), so the offset can be tuned by eye and ear."""
        if self._busy or self.sm.state in (State.THINKING, State.SPEAKING):
            return False
        self._busy = True
        try:
            rate, secs = 24000, 0.18
            pcm = b"".join(int(0.4 * 32767 * math.sin(2 * math.pi * 880 * i / rate)).to_bytes(2, "little", signed=True)
                           for i in range(int(rate * secs)))
            self.audio.play(pcm, rate)
            offset = getattr(self.audio, "output_latency_s", 0.0) + float(self.settings["lipsync_offset_ms"]) / 1000
            await self._sleep_real(max(0.0, offset) * self.realtime)
            self._mouth("ah")
            await self._sleep_real(secs * self.realtime)
            self._mouth("closed")
            return True
        finally:
            self._busy = False

    def selftest_stop(self):
        self._selftest_stop = True

    def swap_device(self, new_dev):
        """Switch simulator <-> serial at runtime (settings device_mode / serial_port)."""
        old = self.dev
        self._selftest_stop = True
        self._cut_audio()
        self._interrupt.set()
        new_dev.on_event = self._on_device_event_ts
        self.dev = new_dev
        try:
            old.on_event = lambda e: None
            old.close()
        except Exception as ex:
            log.warning("closing old device failed: %s", ex)
        self.settings["content"] = "pg"
        if new_dev.connected:
            self.sm.to(State.SLEEPING, force=True)
        else:
            self.sm.to(State.DISCONNECTED, force=True)
        new_dev.set_brightness(self.settings["device_brightness_cap"])
        new_dev.set_power(self.sm.state not in (State.SLEEPING, State.DISCONNECTED))
        self._face(self.state_face[self.sm.state])
        self.emit({"type": "device_link", "connected": new_dev.connected, "device": new_dev.status()})
        self.emit({"type": "settings", "settings": dict(self.settings)})
        self._loop and self._loop.call_later(0.1, self._interrupt.clear)

    def diagnostics(self):
        return {"latencies": list(self.latencies), "counters": {**self.counters, **self.filter.counts},
                "last_interrupt_ms": self.last_interrupt_ms}

    def snapshot(self):
        return {"state": self.sm.state.value, "face": self.dev.face if hasattr(self.dev, "face") else "neutral",
                "settings": dict(self.settings), "people": self.mem.people(),
                "facts": self.mem.facts(limit=20), "emotions": EMOTIONS,
                "device_connected": self.dev.connected, "device": self.dev.status(), "personas": self.personas.names(),
                "diagnostics": self.diagnostics(),
                "wake_status": getattr(self, "wake_status", {"ok": False, "message": "off", "phrase": ""})}
