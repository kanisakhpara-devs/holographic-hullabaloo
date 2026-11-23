"""Adapter contract tests with the REAL models. Skipped unless RUN_REAL=1.

    set RUN_REAL=1 && python -m pytest -q tests/test_real.py -s      (Windows cmd)
    $env:RUN_REAL=1; python -m pytest -q tests/test_real.py -s       (PowerShell)

Each test also skips if its model/runtime is missing. Latency numbers are printed."""
import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL") != "1", reason="set RUN_REAL=1 to run real adapters")
DEVICE = os.environ.get("HH_STT_DEVICE", "cuda")
TTS_DEVICE = os.environ.get("HH_TTS_DEVICE", "cpu")


@pytest.fixture(scope="module")
def kokoro():
    pytest.importorskip("kokoro")
    from companion.adapters.real import KokoroTTS
    k = KokoroTTS(device=TTS_DEVICE)
    k.speak("Warm up.", "am_adam", 1.0)
    return k


@pytest.fixture(scope="module")
def whisper():
    pytest.importorskip("faster_whisper")
    from companion.adapters.real import WhisperSTT
    return WhisperSTT("small", device=DEVICE)


@pytest.fixture(scope="module")
def ollama():
    from companion.adapters.real import OllamaLLM
    llm = OllamaLLM(os.environ.get("HH_LLM", "gemma3:4b"))
    if not llm.is_up() or not llm.has_model():
        pytest.skip("Ollama not running or model not pulled")
    asyncio.run(llm.warm())
    return llm


def test_kokoro_phonemes_and_timing(kokoro):
    t = time.monotonic()
    sp = kokoro.speak("Oh, you finally woke me up.", "am_adam", 0.92)
    ms = (time.monotonic() - t) * 1000
    print(f"\nkokoro {TTS_DEVICE}: {ms:.0f} ms for {sp.duration_s:.2f} s audio, timestamps={sp.times is not None}")
    print("phonemes:", "".join(sp.phonemes))
    assert sp.sample_rate == 24000 and sp.duration_s > 0.8 and sp.phonemes
    from companion.visemes import build_timeline
    tl = build_timeline(sp.phonemes, sp.duration_s, times=sp.times)
    assert len({v for _, v in tl}) >= 3


def test_whisper_roundtrip(kokoro, whisper):
    from companion.audio_io import resample
    sp = kokoro.speak("Hi, my name is Kanishq and I like robots.", "am_michael", 1.0)
    x = resample(np.frombuffer(sp.audio, np.int16).astype(np.float32) / 32768, 24000, 16000)
    pcm = (x * 32767).astype(np.int16).tobytes()
    t = time.monotonic()
    text = whisper.transcribe(pcm)
    print(f"\nwhisper {whisper.device}: {(time.monotonic() - t) * 1000:.0f} ms -> {text!r} {whisper.fallback_reason or ''}")
    assert "robots" in text.lower() and "name" in text.lower()
    assert whisper.transcribe(bytes(32000)) == ""


def test_ollama_first_sentence_under_2500ms(ollama):
    from companion.persona import build_system_prompt, PersonaStore
    from companion.textproc import TagStream

    async def go():
        sysmsg = build_system_prompt(PersonaStore().get("smug_sarcastic"))
        t = time.monotonic()
        ts, first, raw = TagStream(), None, []
        async for tok in ollama.stream(sysmsg, [], "Hi, my name is Kanishq and I like robots.", {"num_predict": 160}):
            raw.append(tok)
            if ts.feed(tok) and first is None:
                first = (time.monotonic() - t) * 1000
        rest = ts.flush(ollama.last_done_reason == "length")
        print(f"\nollama first sentence {first} ms, total {(time.monotonic() - t) * 1000:.0f} ms, tags={ts.saw_tag}")
        print("raw:", "".join(raw))
        return first, ts.saw_tag
    first, tagged = asyncio.run(go())
    assert first is not None and first < 2500
    assert tagged, "model ignored the tag format (the engine retries, but tune the prompt)"
