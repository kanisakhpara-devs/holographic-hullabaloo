"""Phase 2: TagStream, splitter, normalizer, filters, streaming pipeline, interrupt, latency.
Compact: one case per rule. The exhaustive tables are a later pass."""
import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from companion.textproc import TagStream, clean_for_tts, split_sentences, normalize_tag, FALLBACK
from companion.engine import Engine
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.adapters.base import NullAudioOut
from companion.device import SimDevice
from companion.memory import Memory
from companion.states import State
from companion.persona import build_system_prompt, PersonaStore, CONTENT


def stream(tokens, truncated=False):
    ts = TagStream()
    out = []
    for t in tokens:
        out += ts.feed(t)
    return out + ts.flush(truncated)


@pytest.mark.parametrize("tokens,expected", [
    (["[smug] Hello there. [eyeroll] Sure."], [("smug", "Hello there."), ("eyeroll", "Sure.")]),
    (["[sm", "ug] Hi there, human."], [("smug", "Hi there, human.")]),
    (["[ SMUG ] Hello there friend."], [("smug", "Hello there friend.")]),
    (["[Smug] Hello there friend."], [("smug", "Hello there friend.")]),
    (["[amused] Hello there friend."], [("smug", "Hello there friend.")]),
    (["[irritated] Hello there friend."], [("angry", "Hello there friend.")]),
    (["[chuckle] Hello there friend."], [("laughing", "Hello there friend.")]),
    (["[happy] Hello there friend. [bogus] Still happy here."], [("happy", "Hello there friend."), ("happy", "Still happy here.")]),
    (["No tag at the start. [sad] Then a sad one."], [("neutral", "No tag at the start."), ("sad", "Then a sad one.")]),
    (["[sad] One sad sentence. Another one inherits."], [("sad", "One sad sentence."), ("sad", "Another one inherits.")]),
    (["[smug][eyeroll] Double tag here."], [("eyeroll", "Double tag here.")]),
    (["[smug] Trailing tag here. [happy]"], [("smug", "Trailing tag here.")]),
    (["[smug] Hi. [eyeroll] Whatever, my dear human."], [("smug", "Hi. Whatever, my dear human.")]),
    (["Hullabaloo: [smug] *sighs* Fine, (laughs) fifty 50% & more."], [("smug", "Fine, fifty 50 percent and more.")]),
    (["[smug] Done talking now. [bored] And then it went on and"], [("smug", "Done talking now.")]),
])
def test_tagstream(tokens, expected):
    trunc = tokens[0].endswith("went on and")
    assert stream(tokens, truncated=trunc) == expected


def test_tag_never_spoken_and_char_by_char():
    text = "[smug] Oh, you finally woke me up. [eyeroll] Thrilling stuff, really."
    out = stream(list(text))                       # worst case: one char per token
    assert out == [("smug", "Oh, you finally woke me up."), ("eyeroll", "Thrilling stuff, really.")]
    assert normalize_tag(" Tired ") == "sleepy" and normalize_tag("nope") is None


def test_splitter_edge_cases():
    assert split_sentences("Dr. Who is 3.14 meters tall... maybe. Okay then, fine.") == \
        ["Doctor Who is 3.14 meters tall... maybe.", "Okay then, fine."]
    long = "word, " * 60 + "end."
    parts = split_sentences(long)
    assert len(parts) > 1 and all(len(p) <= 221 for p in parts)


def test_normalizer():
    assert clean_for_tts("Run 5km at 20°C, e.g. now \U0001F600") == "Run 5 kilometers at 20 degrees Celsius, for example now"
    assert clean_for_tts("This is *really* cool") == "This is really cool"
    assert clean_for_tts("\U0001F36A ✨") == ""


# ---------------------------------------------------------------- engine
def make(tmp_path, llm=None, realtime=0.0, tts=None):
    ev = []
    dev = SimDevice()
    audio = NullAudioOut()
    e = Engine(MockSTT(), llm or MockLLM(), tts or MockTTS(), dev, Memory(str(tmp_path / "t.db")),
               emit=ev.append, realtime=realtime, audio=audio)
    return e, dev, audio, ev


def test_first_sentence_spoken_before_llm_finishes(tmp_path):
    async def go():
        script = ["[smug] First sentence is ready. " + " ".join(["[bored] More words keep coming here."] * 5)]
        llm = MockLLM(token_delay_s=0.03, script=script)
        e, dev, audio, ev = make(tmp_path, llm)
        e.wake()
        t = asyncio.create_task(e.on_text("hi"))
        while not any(x["type"] == "say" for x in ev):
            await asyncio.sleep(0.005)
        assert not any(x["type"] == "transcript" and x["role"] == "assistant" for x in ev)
        n_tokens_at_first_say = sum(1 for x in ev if x["type"] == "llm_token")
        await t
        assert n_tokens_at_first_say < sum(1 for x in ev if x["type"] == "llm_token")
        lat = [x for x in ev if x["type"] == "latency"][0]
        assert lat["total_ms"] is not None and lat["llm_first_sentence_ms"] is not None
        assert len(e.latencies) == 1
    asyncio.run(go())


def test_interrupt_within_150ms_and_history_marker(tmp_path):
    async def go():
        e, dev, audio, ev = make(tmp_path, realtime=1.0)
        e.wake()
        t = asyncio.create_task(e.on_text("tell me a joke"))
        while e.sm.state != State.SPEAKING:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.2)
        assert e.button() == "interrupted"
        assert audio.stops >= 1 and dev.mouth == "closed" and e.last_interrupt_ms < 150
        await asyncio.sleep(0.05)
        assert e.sm.state == State.INTERRUPTED and dev.face == "eyeroll"
        await t
        assert e.sm.state == State.LISTENING
        assert "[you were interrupted" in e.history[-1]["content"]
    asyncio.run(go())


def test_interrupt_while_thinking(tmp_path):
    async def go():
        e, dev, audio, ev = make(tmp_path, MockLLM(token_delay_s=0.2), realtime=1.0)
        e.wake()
        t = asyncio.create_task(e.on_text("hello"))
        await asyncio.sleep(0.05)
        assert e.sm.state == State.THINKING and e.button() == "interrupted"
        await t
        assert not any(x["type"] == "say" for x in ev)
        assert "before saying anything" in e.history[-1]["content"]
    asyncio.run(go())


def test_untagged_retry_then_neutral(tmp_path):
    async def go():
        e, *_ = make(tmp_path, MockLLM(script=["No tags in this one.", "[smug] Fine, tagged this time."]))
        e.wake()
        assert await e.on_text("hi") == "Fine, tagged this time."
        assert e.counters["tag_retries"] == 1 and e.counters["untagged_replies"] == 0
        e2, *_ = make(tmp_path, MockLLM(script=["Still no tags here.", "Nope, none at all."]))
        e2.wake()
        assert await e2.on_text("hi") == "Nope, none at all."
        assert e2.counters["untagged_replies"] == 1
    asyncio.run(go())


def test_empty_reply_fallback(tmp_path):
    async def go():
        e, dev, audio, ev = make(tmp_path, MockLLM(script=["[smug] \U0001F600", "[smug] (laughs)"]))
        e.wake()
        assert await e.on_text("hi") == FALLBACK[1]
        assert e.counters["fallbacks"] == 1
    asyncio.run(go())


def test_truncated_reply_trimmed(tmp_path):
    class Cut(MockLLM):
        async def stream(self, *a, **k):
            async for t in super().stream(*a, **k):
                yield t
            self.last_done_reason = "length"

    async def go():
        e, *_ = make(tmp_path, Cut(script=["[smug] A complete sentence here. [bored] And then the model ran"]))
        e.wake()
        assert await e.on_text("hi") == "A complete sentence here."
    asyncio.run(go())


def test_pg_post_filter_and_unfiltered(tmp_path):
    async def go():
        bad = "[smug] What the hell is that thing."
        e, *_ = make(tmp_path, MockLLM(script=[bad]))
        e.wake()
        said = await e.on_text("hi")
        assert "hell" not in said and e.filter.counts["pg_post"] == 1
        e2, *_ = make(tmp_path, MockLLM(script=[bad]))
        e2.set_settings({"content": "unfiltered"}, from_ui=True)
        e2.wake()
        assert "hell" in await e2.on_text("hi")
    asyncio.run(go())


def test_blocklist_pre_filter_skips_llm(tmp_path):
    async def go():
        llm = MockLLM()
        e, *_ = make(tmp_path, llm)
        e.set_settings({"blocklist": "homework, exams"}, from_ui=True)
        e.wake()
        said = await e.on_text("do my homework")
        assert said and not llm.calls and e.filter.counts["block_pre"] == 1
    asyncio.run(go())


def test_face_holds_then_neutral(tmp_path):
    async def go():
        e, dev, audio, ev = make(tmp_path, MockLLM(script=["[smug] Hello there friend. [sad] Goodbye now, friend."]),
                                 realtime=0.05)
        e.wake()
        await e.on_text("hi")
        assert dev.face == "sad"                      # still holding the last emotion
        await asyncio.sleep(0.6 * 0.05 + 0.05)
        assert dev.face == "neutral"
    asyncio.run(go())


def test_wake_from_interrupted_no_crash(tmp_path):
    e, *_ = make(tmp_path)
    e.wake()
    e.sm.to(State.THINKING)
    e.sm.to(State.INTERRUPTED)
    assert e.wake("ui") and e.sm.state == State.LISTENING


def test_system_prompt_parts_and_size():
    store = PersonaStore()
    p = build_system_prompt(store.get("smug_sarcastic"), "pg", ["Kanishq"] * 8, [("Kanishq", "likes robots")] * 12,
                            "They talked about robots.")
    assert p.index("Hullabaloo") < p.index(CONTENT["pg"]) < p.index("Every single sentence") \
        < p.index("Reply in") < p.index("Examples") < p.index("People you know") < p.index("It is ")
    assert p.count("User: ") >= 8 and len(p) / 4 < 1150      # honesty rules added Nov 22 (~1030 tokens, ctx 4096)
    assert CONTENT["unfiltered"] not in p
    assert "Mumbai" in p and "custom" in store.names()


def test_whisper_tag_and_effect():
    from companion.emotions import parse_tagged, face_for, whisperize
    from companion.textproc import normalize_tag
    assert parse_tagged("[smug] Fine. [whisper] I know your secret.") == [("smug", "Fine."), ("whisper", "I know your secret.")]
    assert face_for("whisper") == "suspicious" and normalize_tag("Whispering") == "whisper"
    import numpy as np
    t = np.arange(16000) / 16000
    pcm = (np.sin(2 * np.pi * 150 * t) * 20000).astype(np.int16).tobytes()
    out = np.frombuffer(whisperize(pcm, 16000), np.int16)
    assert len(out) == 16000 and np.abs(out).max() < 0.35 * 32768
