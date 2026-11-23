"""Mock adapters so the whole loop runs with no models installed."""
import asyncio, math, re, struct
from .base import STT, LLM, TTS, Speech
from ..visemes import text_to_fake_phonemes


class MockSTT(STT):
    """Audio bytes are treated as UTF-8 text, so tests can 'say' things."""
    def transcribe(self, audio: bytes) -> str:
        return audio.decode("utf-8", "ignore").strip()


class MockLLM(LLM):
    """Canned replies. token_delay_s simulates generation speed. `script` (list of strings)
    overrides the canned replies in order, for tests of odd model output."""

    def __init__(self, token_delay_s=0.0, script=None):
        self.token_delay_s = token_delay_s
        self.script = list(script or [])
        self.calls = []

    def _reply(self, system, user):
        if self.script:
            return self.script.pop(0)
        u = user.lower()
        if system.startswith("Summarise") or system.startswith("Summarize"):
            return "They chatted briefly."
        if m := re.search(r"my name is (\w+)", u):
            return f"[smug] {m.group(1).capitalize()}, huh. [eyeroll] Fancy name for a human."
        if "joke" in u:
            return "[laughing] Your posture, honestly. [smug] I'll be here all week."
        if "tired" in u or "sleep" in u:
            return "[sleepy] Same here, buddy. [bored] Go to bed."
        if "?" in u:
            return "[confused] Hm, no idea. [suspicious] Why do you ask?"
        return "[smug] Fascinating stuff. [bored] Truly riveting."

    def chat(self, system, history, user, options=None):
        self.calls.append(("chat", user))
        return self._reply(system, user)

    async def stream(self, system, history, user, options=None):
        self.calls.append(("stream", user, system))
        text = self._reply(system, user)
        self.last_done_reason = "stop"
        for tok in re.findall(r"\S+\s*|\s+", text):
            if self.token_delay_s:
                await asyncio.sleep(self.token_delay_s)
            yield tok


class MockTTS(TTS):
    def __init__(self, synth_delay_s=0.0):
        self.synth_delay_s = synth_delay_s

    def speak(self, text, voice, speed):
        if self.synth_delay_s:
            import time
            time.sleep(self.synth_delay_s)
        ph = text_to_fake_phonemes(text)
        dur = max(0.3, len(ph) * 0.065 / speed)
        sr = 24000
        n = int(sr * dur)
        pcm = b"".join(struct.pack("<h", int(3000 * math.sin(i * 0.05))) for i in range(0, n, 8))
        return Speech(audio=pcm, sample_rate=sr, duration_s=dur, phonemes=ph)
