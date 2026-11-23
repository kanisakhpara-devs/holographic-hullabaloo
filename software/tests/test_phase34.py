"""Phase 3 (lip sync, VAD, mic gating) and phase 4 (settings, memory, auth). Compact."""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pytest
from fastapi.testclient import TestClient
from companion.visemes import build_timeline, phoneme_to_viseme
from companion.listen import UtteranceDetector, EnergyVAD, MicPipeline, FRAME_BYTES
from companion.engine import Engine
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.adapters.base import NullAudioOut
from companion.device import SimDevice
from companion.memory import Memory
from companion.states import State
from companion.settings import SCHEMA, DEFAULTS, validate, Bad, Settings
from companion.server import create_app
from companion import learn


# ---------------------------------------------------------------- lip sync
MISAKI = list("ˈO , ju fˈInᵊli wˈOk mˌi ˌʌp . ")   # real Kokoro output for "Oh, you finally woke me up."


def test_viseme_table_on_real_misaki_output():
    assert phoneme_to_viseme("ˈ") is None and phoneme_to_viseme(",") is None
    assert phoneme_to_viseme("O") == "oh" and phoneme_to_viseme("m") == "closed" and phoneme_to_viseme("f") == "fv"
    assert phoneme_to_viseme("T") is None and phoneme_to_viseme("A") == "ee"


def test_timeline_smoothing_rules():
    tl = build_timeline(MISAKI, 1.6)
    frames = [round(t * 30) for t, _ in tl]
    assert tl[0] == (0.0, "closed") and tl[-1][1] == "closed"
    assert all(b > a for a, b in zip(frames, frames[1:]))           # strictly increasing: <= 30 per second
    assert all(v1 != v2 for (_, v1), (_, v2) in zip(tl, tl[1:]))    # repeats merged
    for (f1, v1), f2 in zip(zip(frames, [v for _, v in tl]), frames[1:]):
        assert f2 - f1 >= 1 and (v1 == "closed" or f2 - f1 >= 2)    # 2 frame hold except gap blinks
    times = [0.3 + i * 0.05 for i in range(len(MISAKI))]
    assert build_timeline(MISAKI, 1.6, times=times)[1][0] >= 0.3      # timestamps are used when given


# ---------------------------------------------------------------- VAD / mic
def tone(ms, amp=0.5):
    n = 16 * ms
    return (np.sin(np.arange(n) * 0.3) * amp * 32767).astype(np.int16).tobytes()


def frames(pcm):
    return [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES)]


def test_utterance_preroll_and_silence_end():
    d = UtteranceDetector(EnergyVAD(), silence_ms=300)
    pcm = bytes(16 * 600 * 2) + tone(900) + bytes(16 * 600 * 2)
    outs = [u for f in frames(pcm) if (u := d.feed(f))]
    assert len(outs) == 1
    secs = len(outs[0]) / 32000
    assert 0.9 + 0.25 < secs < 0.9 + 0.3 + 0.35                    # speech + pre-roll + the silence tail


def test_push_to_talk_ignores_silence():
    d = UtteranceDetector(EnergyVAD(), silence_ms=90)
    d.ptt_down()
    for f in frames(tone(300) + bytes(16 * 900 * 2)):
        assert d.feed(f) is None                                   # VAD end disabled while held
    assert len(d.ptt_up()) / 32000 == pytest.approx(1.2, abs=0.04)


def _eng(tmp_path, ev, **settings):
    e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "m.db")),
               emit=ev.append, realtime=1.0, audio=NullAudioOut(), extract_facts=False)
    e.settings.update(settings)
    return e


def test_hotkey_mode_never_captures_without_ptt(tmp_path):
    """Default mode: frames that arrive without push-to-talk held are ignored completely."""
    async def go():
        ev = []
        e = _eng(tmp_path, ev)
        assert e.settings["mic_mode"] == "hotkey"
        pipe = MicPipeline(e, vad=EnergyVAD(), emit=ev.append)
        pipe.attach_loop()
        e.wake()
        for f in frames(tone(600, 0.8) + bytes(30 * 900 * 2)):
            pipe.on_frame(f)
        await asyncio.sleep(0.05)
        assert pipe.utterances == 0 and not [x for x in ev if x["type"] == "level"]
    asyncio.run(go())


def test_off_mode_refuses_ptt(tmp_path):
    async def go():
        ev = []
        e = _eng(tmp_path, ev, mic_mode="off")
        pipe = MicPipeline(e, vad=EnergyVAD(), emit=ev.append)
        opened = []
        pipe.on_ptt_change = lambda held=None: opened.append(held)
        pipe.attach_loop()
        pipe.ptt_down()
        for f in frames(tone(500, 0.8)):
            pipe.on_frame(f)
        pipe.ptt_up()
        assert pipe.utterances == 0 and opened == [] and any(x["type"] == "toast" for x in ev)
    asyncio.run(go())


def test_ptt_opens_and_closes_the_stream(tmp_path):
    async def go():
        ev = []
        e = _eng(tmp_path, ev)
        pipe = MicPipeline(e, vad=EnergyVAD(), emit=ev.append)
        calls = []
        pipe.on_ptt_change = calls.append
        pipe.attach_loop()
        pipe.ptt_down()
        for f in frames(tone(600, 0.8)):
            pipe.on_frame(f)
        pipe.ptt_up()
        await asyncio.sleep(0.05)
        assert calls == [True, False] and pipe.utterances == 1
    asyncio.run(go())


class FakeOWW:
    """stands in for openwakeword.model.Model"""
    def __init__(self):
        self.fire_on = set()
        self.n = 0

    def predict(self, pcm):
        self.n += 1
        return {"hey_jarvis": 0.99 if self.n in self.fire_on else 0.0}

    def reset(self):
        pass


def test_wake_mode_only_captures_after_wake_word(tmp_path):
    async def go():
        from companion.listen import WakeWord
        ev = []
        e = _eng(tmp_path, ev, mic_mode="wake")
        fake = FakeOWW()
        ww = WakeWord(model_factory=lambda: fake)
        pipe = MicPipeline(e, vad=EnergyVAD(), wake=ww, emit=ev.append)
        pipe.attach_loop()
        speech = frames(tone(600, 0.8) + bytes(30 * 900 * 2))
        for f in speech:                       # talking before the wake word: not captured
            pipe.on_frame(f)
        await asyncio.sleep(0.05)
        assert pipe.utterances == 0
        fake.fire_on = {fake.n + 1}            # next 80 ms chunk is the wake word
        for f in frames(bytes(3000 * 2)):
            pipe.on_frame(f)
        assert pipe.armed and e.sm.state == State.LISTENING and any(x["type"] == "wake_heard" for x in ev)
        for f in speech:
            pipe.on_frame(f)
        await asyncio.sleep(0.05)
        assert pipe.utterances == 1 and not pipe.armed   # one utterance, then back to waiting
    asyncio.run(go())


def test_wake_word_phrase_names():
    from companion.listen import phrase_of
    assert phrase_of(None) == "hey jarvis" and phrase_of("C:/x/hey_hullabaloo_v0.1.onnx") == "hey hullabaloo"


def test_ignored_speech_counts_once_per_stretch(tmp_path):
    """While it talks, your speech is dropped and counted once per stretch, not once per frame."""
    async def go():
        ev = []
        e = _eng(tmp_path, ev, mic_mode="wake")
        pipe = MicPipeline(e, vad=EnergyVAD(), emit=ev.append)
        pipe.attach_loop()
        e.wake()
        t = asyncio.create_task(e.on_text("tell me a joke"))
        while e.sm.state != State.SPEAKING:
            await asyncio.sleep(0.01)
        pipe.armed, pipe._armed_at = True, __import__("time").monotonic()
        for f in frames(tone(1500, 0.8)):
            pipe.on_frame(f)
        assert pipe.utterances == 0 and e.counters["mic_dropped"] == 1
        await t
    asyncio.run(go())


# ---------------------------------------------------------------- settings
def test_every_setting_default_is_valid_and_has_a_bad_value():
    assert len(SCHEMA) >= 39
    for k, (d, *_ ) in SCHEMA.items():
        assert validate(k, d) == d, k
    bad = {"persona": "Bad Name!", "content": "spicy", "privacy_mode": "x", "reply_length": "huge",
           "sarcasm_level": 7, "temperature": 3, "roast_user": "yes", "blocklist": 5, "vad_silence_ms": 1.5,
           "idle_timeout_s": 0, "volume": 101, "lipsync_offset_ms": 500, "ptt_hotkey": "Ctrl+", "ollama_url":
           "http://example.com:11434", "timezone": "Mars/Base", "voice_overrides": {"smug": {"speed": 9}},
           "emotion_map": {"thinking": "giddy"}, "device_mode": "wifi", "stt_device": "tpu", "ui_scale": 3,
           "device_brightness_cap": -1, "mic_gain": 0, "wake_word_sensitivity": 2}
    for k, v in bad.items():
        with pytest.raises(Bad):
            validate(k, v)


def test_settings_persist_but_content_resets(tmp_path):
    db = str(tmp_path / "s.db")
    exp = str(tmp_path / "settings.json")
    s = Settings(Memory(db), exp)
    applied, errors = s.update_from({"volume": 33, "reply_length": "short", "content": "unfiltered", "temperature": 9},
                                    from_ui=True)
    assert errors == {"temperature": "must be 0.5 to 1.2"} and applied["content"] == "unfiltered"
    s2 = Settings(Memory(db))
    assert s2["volume"] == 33 and s2["reply_length"] == "short" and s2["content"] == "pg"
    assert json.load(open(exp))["volume"] == 33 and "content" not in json.load(open(exp))
    _, err = s2.update_from({"content": "unfiltered"}, from_ui=False)
    assert "content" in err and s2["content"] == "pg"


def test_live_settings_take_effect(tmp_path):
    e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "l.db")), realtime=0)
    assert e.set_settings({"emotion_map": {"thinking": "confused"}, "voice_overrides": {"smug": {"speed": 1.2}},
                           "persona": "nope"}) == {"persona": "no such persona file"}
    assert e.state_face[State.THINKING] == "confused" and e.speech_for("smug")["speed"] == 1.2


# ---------------------------------------------------------------- memory / learning
def test_facts_are_explicit_and_newer_replaces_older(tmp_path):
    async def go():
        e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "f.db")), realtime=0)
        e.settings["owner_name"] = "Kanishq"
        e.wake()
        await e.on_text("Yeah, my favorite book would be a shoe dog by Phil Knight")
        assert [f for _, f in e.mem.facts()] == ["favorite book is shoe dog by Phil Knight"]
        assert e.mem.facts()[0][0] == "Kanishq"
        assert any("Saved about Kanishq" in n for n in e.turn_notes)
        await e.on_text("actually my favourite book is Dune")
        assert [f for _, f in e.mem.facts()] == ["favorite book is Dune"]
        assert any("replaced" in n for n in e.turn_notes)
        await e.on_text("I love pizza")
        await e.on_text("I hate pizza")
        facts = [f for _, f in e.mem.facts()]
        assert "hates pizza" in facts and "loves pizza" not in facts
        await e.on_text("tell me a joke, I had a bad day")       # no facts from chit chat or moods
        assert len(e.mem.facts()) == 2
        await e.on_text("forget that my favorite book is Dune")
        assert [f for _, f in e.mem.facts()] == ["hates pizza"]
        await e.on_text("remember that my sister builds robots")
        assert any("sister builds robots" in f for _, f in e.mem.facts())
    asyncio.run(go())


def test_names_need_confirmation(tmp_path):
    async def go():
        e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "n.db")), realtime=0)
        e.wake()
        await e.on_text("I'm Ria and this is Duncan")                # "I'm X" / "this is X" never save names
        assert e.mem.people() == [] and e.pending_name is None
        await e.on_text("my name is Ria")
        assert e.mem.people() == [] and e.pending_name == "Ria"
        assert "Ria" in e.system_prompt() and "confirm" in e.system_prompt()
        await e.on_text("no")
        assert e.mem.people() == [] and e.pending_name is None
        await e.on_text("my name is Riya")
        await e.on_text("yes")
        assert e.mem.people() == ["Riya"] and e.speaker == "Riya"
    asyncio.run(go())


def test_prompt_has_no_example_names_and_has_honesty_rules(tmp_path):
    e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "p.db")), realtime=0)
    p = e.system_prompt()
    assert "Riya" not in p and "false premise" in p and "not sure" in p
    e.settings["owner_name"] = "Kanishq"
    assert "Assume you are talking to Kanishq" in e.system_prompt()


def test_web_search_only_when_on_and_time_sensitive(tmp_path, monkeypatch):
    from companion import websearch
    calls = []
    monkeypatch.setattr(websearch, "search", lambda q, n=3: calls.append(q) or [{"title": "GTA VI", "body": "Released Nov 19 2026", "href": "x"}])
    async def go():
        e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "w.db")), realtime=0)
        e.wake()
        await e.on_text("when did gta 6 come out?")
        assert calls == []                                          # off by default
        e.settings["web_search"] = True
        await e.on_text("tell me a joke")
        assert calls == []                                          # not time-sensitive
        await e.on_text("when did gta 6 come out?")
        assert len(calls) == 1 and "Released Nov 19 2026" in e.system_prompt()
    asyncio.run(go())


def test_sensitive_regex_facts_never_stored():
    assert learn.regex_pass("I live in flat 402 on Worli road")[1] == []
    assert learn.regex_pass("I study at Don Bosco school")[1] == []
    assert learn.regex_pass("I love chess")[1] == ["loves chess"]


def test_retention_hours_left(tmp_path):
    m = Memory(str(tmp_path / "r.db"))
    assert m.retention_hours_left() is None
    m.log("user", "hi")
    assert 23.9 < m.retention_hours_left() <= 24
    assert m.retention_hours_left(now=time.time() + 20 * 3600) < 4.1


# ---------------------------------------------------------------- REST + auth
def test_token_auth_and_memory_endpoints(tmp_path):
    app = create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "a.db"), realtime=0.0,
                     token="sekrit", data_dir=str(tmp_path), extract_facts=False)
    H = {"X-Token": "sekrit"}
    with TestClient(app) as c:
        assert c.get("/api/snapshot").status_code == 401
        assert c.get("/api/snapshot", headers={"X-Token": "wrong"}).status_code == 401
        with pytest.raises(Exception):
            with c.websocket_connect("/ws") as ws:
                ws.receive_text()
        with c.websocket_connect("/ws?token=sekrit") as ws:
            assert json.loads(ws.receive_text())["type"] == "snapshot"
            for said in ("my name is Asha and I love chess", "yes"):    # name saved after "yes"
                ws.send_text(json.dumps({"type": "text", "text": said}))
                while True:
                    ev = json.loads(ws.receive_text())
                    if ev["type"] == "transcript" and ev["role"] == "assistant":
                        break
        mem = c.get("/api/memory", headers=H).json()
        assert mem["people"][0]["name"] == "Asha" and mem["facts"][0]["fact"] == "loves chess"
        assert c.delete(f"/api/memory/fact/{mem['facts'][0]['id']}", headers=H).json()["ok"]
        assert c.post("/api/memory/forget_all", headers=H, json={}).status_code == 400
        assert c.post("/api/memory/forget_all", headers=H, json={"confirm": True}).json()["ok"]
        assert c.get("/api/memory", headers=H).json()["people"] == []
        r = c.put("/api/settings", headers=H, json={"volume": 500})
        assert r.status_code == 422 and "volume" in r.json()["errors"]
        assert c.put("/api/settings", headers=H, json={"volume": 50}).json()["settings"]["volume"] == 50
        assert "custom" in [p["name"] for p in c.get("/api/personas", headers=H).json()]
        assert c.put("/api/emotion_map", headers=H, json={"smug": {"speed": 5}}).status_code == 422
        assert c.get("/api/memory/export", headers=H).headers["content-type"].startswith("application/json")
        assert c.get("/api/health", headers=H).json()["llm"]["type"] == "MockLLM"


def test_live_partial_captions_while_holding_ptt(tmp_path):
    class SlowSTT(MockSTT):
        def transcribe(self, audio):
            return "so far %d" % len(audio)
    async def go():
        ev = []
        e = Engine(SlowSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "pc.db")),
                   emit=ev.append, realtime=1.0, audio=NullAudioOut(), extract_facts=False)
        pipe = MicPipeline(e, vad=EnergyVAD(), emit=ev.append)
        pipe.attach_loop()
        pipe.PARTIAL_EVERY_S = 0.0
        pipe.ptt_down()
        for f in frames(tone(1500, 0.8)):
            pipe.on_frame(f)
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        parts = [x for x in ev if x["type"] == "partial"]
        assert parts and parts[0]["text"].startswith("so far")
        pipe.ptt_up()
    asyncio.run(go())


def test_facts_before_owner_name_move_to_it(tmp_path):
    async def go():
        e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "o.db")), realtime=0)
        e.wake()
        await e.on_text("I love chess")
        assert e.mem.facts()[0][0] == "you"
        e.set_settings({"owner_name": "Kanishq"}, from_ui=True)
        assert e.mem.facts()[0][0] == "Kanishq"
    asyncio.run(go())


def test_shutdown_endpoint_dry_run(tmp_path, monkeypatch):
    from companion import power
    monkeypatch.setattr(power, "unload_ollama", lambda url, timeout=3.0: ["gemma3:4b"])
    app = create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "sd.db"), realtime=0.0,
                     extract_facts=False)
    with TestClient(app) as c:
        assert c.post("/api/shutdown", json={}).status_code == 400
        assert c.post("/api/shutdown", json={"confirm": True}, headers={"Origin": "https://evil.com"}).status_code == 403
        r = c.post("/api/shutdown", json={"confirm": True, "dry_run": True}).json()
        assert r["ok"] and r["unloaded"] == ["gemma3:4b"] and r["killed"] == []


def test_hotkey_still_works_in_wake_word_mode(tmp_path):
    """The 'hotkey + wake word' mode: holding the hotkey captures speech without saying the wake word."""
    async def go():
        ev = []
        e = _eng(tmp_path, ev, mic_mode="wake")
        pipe = MicPipeline(e, vad=EnergyVAD(), wake=None, emit=ev.append)
        calls = []
        pipe.on_ptt_change = calls.append
        pipe.attach_loop()
        pipe.ptt_down()
        for f in frames(tone(600, 0.8)):
            pipe.on_frame(f)
        pipe.ptt_up()
        await asyncio.sleep(0.05)
        assert pipe.utterances == 1 and calls == [True, False]
    asyncio.run(go())
