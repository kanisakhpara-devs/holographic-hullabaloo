"""Nov 25 features: personas, timers and reminders, study buddy, games, night hours, proximity greetings,
rotor health packets and music reactions. All with mock models."""
import asyncio
from datetime import datetime
import numpy as np
import pytest

from companion.engine import Engine
from companion.memory import Memory
from companion.device import SimDevice, PacketParser, pack_rx, pack, decode_rx_event, describe_tx, battery_pct
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.persona import PersonaStore, parse_persona, build_system_prompt
from companion.states import State
from companion import extras
from companion.music import BeatDetector

NOW = datetime(2026, 11, 25, 16, 40)


def eng(tmp_path, llm=None):
    events = []
    e = Engine(MockSTT(), llm or MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "x.db")),
               emit=events.append, realtime=0)
    e.events = events
    return e


# ------------------------------------------------------------------ parsers
@pytest.mark.parametrize("text,want", [
    ("Set a timer for 10 minutes.", ("add", "timer", 600.0, "")),
    ("set a 5 minute timer for the pasta", ("add", "timer", 300.0, "the pasta")),
    ("Timer for an hour and a half", ("add", "timer", 5400.0, "")),
    ("remind me in twenty minutes to call mom", ("add", "reminder", 1200.0, "call mom")),
    ("Remind me to drink water in 45 mins.", ("add", "reminder", 2700.0, "drink water")),
    ("remind me at 5 pm to start physics", ("add", "reminder", 1200.0, "start physics")),
    ("cancel the pasta timer", ("cancel", "pasta")),
    ("cancel all reminders", ("cancel", "all")),
    ("what timers do I have?", ("list",)),
    ("what time is it", None),
    ("I set a record in the 100 metres", None),
])
def test_timer_parser(text, want):
    assert extras.parse_timer_command(text, NOW) == want


def test_study_and_game_parsers():
    assert extras.parse_study_command("start a study session on physics") == ("start", "physics", None)
    assert extras.parse_study_command("lets study chemistry for 30 minutes") == ("start", "chemistry", 30)
    assert extras.parse_study_command("stop studying") == ("stop",)
    assert extras.parse_study_command("I play football") is None
    assert extras.parse_game_command("lets play trivia about space") == ("start", "trivia", "space")
    assert extras.parse_game_command("can we play 20 questions?") == ("start", "twenty_questions", "")
    assert extras.parse_game_command("stop the game") == ("stop",)
    assert extras.parse_game_command("I give up") is None          # in 20 questions that reveals the answer instead


def test_night_window_wraps_midnight():
    assert extras.in_window(datetime(2026, 1, 1, 23, 30), "23:00", "07:00")
    assert extras.in_window(datetime(2026, 1, 1, 6, 59), "23:00", "07:00")
    assert not extras.in_window(datetime(2026, 1, 1, 12, 0), "23:00", "07:00")
    assert extras.in_window(datetime(2026, 1, 1, 14, 0), "13:00", "15:00")


# ------------------------------------------------------------------ personas
def test_each_persona_has_its_own_examples_and_voice():
    st = PersonaStore()
    wiz, hype, smug = st.profile("grumpy_wizard"), st.profile("hype_buddy"), st.profile("smug_sarcastic")
    assert wiz["voice"] == "bm_george" and hype["voice"] == "am_puck" and smug["voice"] == ""
    assert len(wiz["examples"]) >= 5 and len(hype["examples"]) >= 5
    p = build_system_prompt(st.get("grumpy_wizard"))
    assert "young one" in p and "Oh, look who remembered I exist" not in p      # no smug examples in the wizard
    assert "voice:" not in p and "Phil Knight never wrote one" in p             # header stripped, honesty kept


def test_parse_persona_plain_text_still_works():
    p = parse_persona("You are a pirate.")
    assert p == {"text": "You are a pirate.", "voice": "", "speed": 1.0, "examples": []}


def test_switching_persona_clears_history_and_changes_voice(tmp_path):
    e = eng(tmp_path)
    asyncio.run(e.on_text("hello there"))
    assert e.history
    e.set_settings({"persona": "grumpy_wizard"}, from_ui=True)
    assert e.history == []
    assert e.speech_for("smug")["voice"] == "bm_george"
    e.set_settings({"voice_overrides": {"smug": {"voice": "am_adam"}}}, from_ui=True)
    assert e.speech_for("smug")["voice"] == "am_adam"                      # explicit override still wins


# ------------------------------------------------------------------ timers
def test_voice_timer_is_set_and_rings(tmp_path):
    e = eng(tmp_path)

    async def go():
        await e.on_text("set a timer for 10 minutes for the pasta")
        assert len(e.timers.active()) == 1
        assert "set a timer for 'the pasta'" in " ".join(e.turn_notes)
        with e.mem.lock:                                   # pretend 10 minutes went by
            e.mem.db.execute("UPDATE timers SET due=0")
        e.sleep()
        assert e.sm.state == State.SLEEPING
        await e._tick_extras()
        assert e.timers.active() == []
        said = [x for x in e.events if x["type"] == "transcript" and x["role"] == "assistant"]
        assert said, "the timer was spoken"
        assert any(x["type"] == "toast" and "pasta" in x["message"] for x in e.events)
        assert any(x["type"] == "wake" and x["source"] == "event" for x in e.events)
    asyncio.run(go())


def test_cancel_and_list(tmp_path):
    e = eng(tmp_path)

    async def go():
        await e.on_text("remind me in 20 minutes to call mom")
        await e.on_text("what reminders do I have")
        assert "call mom" in " ".join(e.turn_notes)
        await e.on_text("cancel my reminder")
        assert e.timers.active() == [] and "Cancelled" in " ".join(e.turn_notes)
        await e.on_text("cancel my timer")
        assert "nothing was cancelled" in " ".join(e.turn_notes)
    asyncio.run(go())


def test_prompt_never_claims_a_timer_without_a_note(tmp_path):
    e = eng(tmp_path)
    assert "only say one was set" in e.system_prompt()


# ------------------------------------------------------------------ study buddy
def test_study_session_break_quiz_and_nag(tmp_path):
    e = eng(tmp_path)

    async def go():
        await e.on_text("lets study chemistry for 30 minutes")
        assert e.study.active and e.study.subject == "chemistry" and e.study.focus_min == 30
        assert "get back to work" in e.system_prompt()
        await e.on_text("lets play trivia")                 # no games during focus
        assert not e.game.active and "did NOT start" in " ".join(e.turn_notes)
        e.study.ends = 0                                      # focus block over
        await e._tick_extras()
        assert e.study.phase == "break" and e.study.quiz_question_pending
        llm_systems = [c[2] for c in e.llm.calls if c[0] == "stream"]
        assert "quiz question about chemistry" in e.llm.calls[-1][1]
        assert "Judge their answer honestly" in e.system_prompt()
        await e.on_text("stop studying")
        assert not e.study.active
    asyncio.run(go())


# ------------------------------------------------------------------ games
def test_twenty_questions_win(tmp_path):
    e = eng(tmp_path)
    e.game.rng.seed(1)

    async def go():
        await e.on_text("can we play 20 questions")
        assert e.game.active and e.game.secret
        assert e.game.secret in e.system_prompt()
        await e.on_text("is it alive?")
        assert e.game.turns == 1
        word = e.game.secret.split()[-1]
        await e.on_text(f"is it {word}?")
        assert not e.game.active and "They guessed it" in " ".join(e.turn_notes)
    asyncio.run(go())


def test_trivia_stop(tmp_path):
    e = eng(tmp_path)

    async def go():
        await e.on_text("lets play trivia about space")
        assert e.game.name == "trivia" and "about space" in e.system_prompt()
        await e.on_text("stop the game")
        assert not e.game.active
    asyncio.run(go())


# ------------------------------------------------------------------ night hours, proximity greeting
def test_night_hours_sleep_and_ignore_proximity(tmp_path):
    e = eng(tmp_path)
    e.set_settings({"night_sleep": True, "night_start": "00:00", "night_end": "23:59"}, from_ui=True)

    async def go():
        e.wake("button")
        await e._tick_extras()
        assert e._night and e.sm.state == State.SLEEPING
        e._on_device_event({"type": "proximity", "near": True})
        assert e.sm.state == State.SLEEPING
        e.wake("button")                                  # the button still works
        assert e.sm.state == State.LISTENING
    asyncio.run(go())


def test_proximity_greeting_with_cooldown(tmp_path):
    e = eng(tmp_path)
    e.set_settings({"proximity_greet": True, "greet_cooldown_min": 10}, from_ui=True)

    async def go():
        e._on_device_event({"type": "proximity", "near": True})
        await e._tick_extras()
        assert any(x["type"] == "transcript" and x["role"] == "assistant" for x in e.events)
        n = len(e._events)
        e.sleep()
        e._on_device_event({"type": "proximity", "near": True})
        assert len(e._events) == n                         # cooldown: no second greeting
    asyncio.run(go())


# ------------------------------------------------------------------ device health packets
def test_rotor_power_and_spin_packets():
    p = PacketParser()
    raw = pack_rx("ROTOR_POWER", (3950 - 2500) // 10, 3) + pack_rx("ROTOR_SPIN", 1500 >> 8, 1500 & 255)
    assert raw.hex(" ") == "5a 06 91 03 9a 5a 07 05 dc e8"              # same as docs/PROTOCOL.md
    (c1, a1, b1), (c2, a2, b2) = p.feed(raw)
    assert decode_rx_event(c1, a1, b1) == {"type": "rotor_power", "battery_mv": 3950, "power_good": True, "charging": True}
    assert decode_rx_event(c2, a2, b2) == {"type": "rotor_spin", "rpm": 1500}
    assert pack("LOOK", -3 & 255).hex(" ") == "a5 08 fd 00 05" and describe_tx(8, 253, 0) == "LOOK -3"
    assert battery_pct(4200) == 100 and battery_pct(3300) == 0


def test_sim_device_health_numbers():
    d = SimDevice()
    d.set_power(True)
    st = d.status()
    assert st["simulated"] and 1400 < st["rpm"] < 1600 and 0 <= st["battery_pct"] <= 100


# ------------------------------------------------------------------ music
def test_beat_detector_finds_music_and_beats():
    det = BeatDetector(0.5)
    evs = []
    rng = np.random.default_rng(0)
    for i in range(600):                                   # about 12.8 s: kicks every ~0.5 s over a quiet bed
        x = 0.03 * rng.standard_normal(1024).astype(np.float32)
        if i % 23 == 0:
            x *= 8
        evs += det.feed(x)
    for _ in range(200):                                   # then silence
        evs += det.feed(np.zeros(1024, np.float32))
    kinds = [e[0] for e in evs]
    assert kinds[0] == "start" and kinds[-1] == "stop"
    assert 15 <= kinds.count("beat") <= 30


def test_music_event_bobs_only_when_idle(tmp_path):
    e = eng(tmp_path)

    async def go():
        e.attach_loop()
        e.music_event(("start",))
        assert e.music["on"] and e.dev.face == "happy"
        e.music_event(("beat", 0.8))
        assert e.dev.look in (2, 3, -2, -3) and e.dev.mouth == "oh"
        e._busy = True
        look = e.dev.look
        e.music_event(("beat", 0.8))
        assert e.dev.look == look                           # busy: no bobbing
        e._busy = False
        e.music_event(("stop",))
        assert not e.music["on"] and e.dev.look == 0
    asyncio.run(go())
