"""Companion state machine. States match the 7 UI states in the mockup brief."""
from enum import Enum


class State(str, Enum):
    SLEEPING = "sleeping"
    WAKING = "waking"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    DISCONNECTED = "disconnected"


ALLOWED = {
    State.DISCONNECTED: {State.SLEEPING, State.WAKING},
    State.SLEEPING:     {State.WAKING, State.DISCONNECTED},
    State.WAKING:       {State.LISTENING, State.SLEEPING, State.DISCONNECTED},
    State.LISTENING:    {State.THINKING, State.SLEEPING, State.DISCONNECTED, State.LISTENING},
    State.THINKING:     {State.SPEAKING, State.LISTENING, State.INTERRUPTED, State.DISCONNECTED},
    State.SPEAKING:     {State.LISTENING, State.INTERRUPTED, State.DISCONNECTED},
    State.INTERRUPTED:  {State.LISTENING, State.SLEEPING, State.DISCONNECTED},
}

# Default face emotion shown in each state (the speaking state overrides per sentence).
STATE_FACE = {
    State.SLEEPING: "sleepy",
    State.WAKING: "surprised",
    State.LISTENING: "neutral",
    State.THINKING: "suspicious",
    State.SPEAKING: "neutral",
    State.INTERRUPTED: "eyeroll",
    State.DISCONNECTED: "neutral",
}


class IllegalTransition(Exception):
    pass


class StateMachine:
    def __init__(self, on_change=None, initial=State.DISCONNECTED):
        self.state = initial
        self._cb = on_change

    def to(self, new: State, force: bool = False):
        if new == self.state:
            return
        if not force and new not in ALLOWED[self.state]:
            raise IllegalTransition(f"{self.state.value} -> {new.value}")
        old, self.state = self.state, new
        if self._cb:
            self._cb(old, new)
