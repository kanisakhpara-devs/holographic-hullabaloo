import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from companion.engine import Engine
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.device import SimDevice, pack
from companion.memory import Memory
from companion.states import State
from companion.emotions import parse_tagged, EMOTIONS
from companion.visemes import build_timeline


def make(tmp_path, realtime=0.0):
    ev = []
    dev = SimDevice()
    mem = Memory(str(tmp_path / "t.db"))
    e = Engine(MockSTT(), MockLLM(), MockTTS(), dev, mem, emit=ev.append, realtime=realtime)
    return e, dev, mem, ev


def run(c):
    return asyncio.run(c)


def test_parse_tags():
    assert parse_tagged("[smug] Hi. [eyeroll] Sure.") == [("smug", "Hi."), ("eyeroll", "Sure.")]
    assert parse_tagged("no tag")[0][0] == "neutral"
    assert parse_tagged("[bogus] hey")[0] == ("neutral", "hey")


def test_timeline_quantised_and_closed():
    tl = build_timeline(list("hello world"), 1.0)
    assert tl[0][0] == 0.0 and tl[-1][1] == "closed"
    assert all(abs(t * 30 - round(t * 30)) < 1e-6 for t, _ in tl)


def test_full_turn_and_mic_gating(tmp_path):
    async def go():
        e, dev, mem, ev = make(tmp_path)
        assert e.sm.state == State.SLEEPING
        dev.sim_proximity(True)
        assert e.sm.state == State.LISTENING
        said = await e.on_audio(b"my name is Kanishq and I like robots")
        assert said and "Kanishq" in said
        assert e.sm.state == State.LISTENING
        states = [x["state"] for x in ev if x["type"] == "state"]
        assert states == ["waking", "listening", "thinking", "speaking", "listening"]
        assert e.pending_name == "Kanishq" and "Kanishq" not in mem.people()   # saved only after "yes"
        assert any("robots" in f for _, f in mem.facts())
        assert any(l[1] == "mouth" and l[2] != "closed" for l in dev.log)
    run(go())


def test_mic_dropped_while_speaking(tmp_path):
    async def go():
        e, dev, mem, ev = make(tmp_path, realtime=1.0)
        e.wake()
        t = asyncio.create_task(e.on_text("tell me a joke"))
        await asyncio.sleep(0.3)
        assert e.sm.state == State.SPEAKING
        assert await e.on_audio(b"hello?") is None
        assert any(x["type"] == "mic_dropped" for x in ev)
        e.button()
        await t
        assert e.sm.state == State.LISTENING
    run(go())


def test_interrupt_cuts_speech(tmp_path):
    async def go():
        e, dev, mem, ev = make(tmp_path, realtime=1.0)
        e.wake()
        t = asyncio.create_task(e.on_text("tell me a joke"))
        await asyncio.sleep(0.4)
        t0 = time.time()
        assert e.button() == "interrupted"
        await t
        assert time.time() - t0 < 0.5
        assert dev.mouth == "closed"
        assert any(x["type"] == "interrupted" for x in ev)
        assert e.sm.state == State.LISTENING
    run(go())


def test_pg_default_and_ui_only_unfiltered(tmp_path):
    e, *_ = make(tmp_path)
    e.set_settings({"content": "unfiltered"}, from_ui=False)
    assert e.settings["content"] == "pg"
    e.set_settings({"content": "unfiltered"}, from_ui=True)
    assert e.settings["content"] == "unfiltered"
    e2, *_ = make(tmp_path)                 # "reboot": must be PG again
    assert e2.settings["content"] == "pg"


def test_faire_mode_wipes_transcripts_keeps_facts(tmp_path):
    async def go():
        e, dev, mem, ev = make(tmp_path)
        e.wake()
        await e.on_text("my name is Asha and I love chess")
        await e.on_text("yes")                                   # names are saved after confirmation
        assert mem.transcript()
        e.set_settings({"privacy_mode": "faire"}, from_ui=True)
        assert mem.transcript() == [] and "Asha" in mem.people()
        await e.on_text("anything")
        assert mem.transcript() == []
    run(go())


def test_transcript_ttl(tmp_path):
    m = Memory(str(tmp_path / "x.db"))
    m.log("user", "hi")
    assert m.purge_old(now=time.time() + 25 * 3600) == 1


def test_disconnect_and_recover(tmp_path):
    e, dev, mem, ev = make(tmp_path)
    dev.sim_disconnect(True)
    assert e.sm.state == State.DISCONNECTED
    dev.sim_disconnect(False)
    assert e.sm.state == State.SLEEPING


def test_packet_format():
    p = pack("FACE", 5)
    assert p == bytes([0xA5, 1, 5, 0, 6])
    assert len(EMOTIONS) == 12


def test_usage_counts_even_in_faire(tmp_path):
    async def go():
        e, dev, mem, ev = make(tmp_path)
        e.set_settings({"privacy_mode": "faire"}, from_ui=True)
        e.wake()
        await e.on_text("hello")
        await e.on_text("again")
        cum, hours = mem.usage(7)
        assert cum[-1] == 2 and sum(hours) == 2 and len(cum) == 7
    run(go())


def test_daily_minutes_talked(tmp_path):
    m = Memory(str(tmp_path / "u.db"))
    r = m.log_usage()
    m.set_usage_secs(r, 90)
    m.log_usage(30)
    d = m.daily(7)
    assert len(d) == 7 and d[-1]["minutes"] == 2.0 and d[-1]["turns"] == 2 and d[0]["minutes"] == 0
