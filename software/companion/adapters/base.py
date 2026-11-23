"""Adapter interfaces. The engine only talks to these, so mock and real are swappable."""
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional


class STT:
    def transcribe(self, audio: bytes) -> str: ...


class LLM:
    """stream() yields text tokens. After the loop, self.last_done_reason is 'stop' or 'length'."""
    last_done_reason: Optional[str] = None

    def chat(self, system: str, history: list, user: str, options: Optional[dict] = None) -> str:
        """Blocking, whole reply. Used for summaries and fact extraction (run in a thread)."""
        raise NotImplementedError

    async def stream(self, system: str, history: list, user: str,
                     options: Optional[dict] = None) -> AsyncIterator[str]:
        """Default: fake a stream from chat() (adapters should override)."""
        import asyncio
        text = await asyncio.to_thread(self.chat, system, history, user, options)
        self.last_done_reason = "stop"
        yield text

    async def warm(self):
        """Load the model so the first real turn is fast. Optional."""


@dataclass
class Speech:
    audio: bytes            # PCM16 mono, sample_rate below
    sample_rate: int
    duration_s: float
    phonemes: List[str] = field(default_factory=list)
    # optional per-phoneme start times in seconds (same length as phonemes) if the TTS gives them
    times: Optional[List[float]] = None
    # optional start time (s) of each spoken word, for the karaoke captions on Home
    word_times: Optional[List[float]] = None


class TTS:
    def speak(self, text: str, voice: str, speed: float) -> Speech: ...


class AudioOut:
    """Plays PCM16 mono. play() must return quickly (non-blocking); stop() must be instant."""
    output_latency_s: float = 0.0

    def play(self, pcm: bytes, sample_rate: int): ...
    def stop(self): ...


class NullAudioOut(AudioOut):
    """No speakers (tests, headless). Records what would have played."""
    def __init__(self):
        self.played, self.stops = [], 0

    def play(self, pcm, sample_rate):
        self.played.append(len(pcm))

    def stop(self):
        self.stops += 1
