"""Silence handling state machine for the voice agent.

Pure logic — no I/O, no LiveKit, no Sarvam. Receives elapsed-time events
from the agent; returns a directive ("prompt", "hangup", or "wait"). The
agent decides how to act on directives (call session.say, session.aclose,
or do nothing).

Per spec docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md
§8 (Component 9). Industry-standard timeouts (slightly tightened for
Solo plan margin protection):

  DEFAULT:        prompt 5s/7s, hangup 10s
  WAIT_REQUESTED: prompt 15s/30s, hangup 45s
  EMERGENCY × 2:  default → 10s/14s/20s; wait → 30s/60s/90s
  GARBLED:        counter=3 prompts, hangup on 4th — UNIFORM across all modes

Per CLAUDE.md Rule 7 (emergency MVP) the emergency override applies to silence
timeouts only. The garbled counter is intentionally uniform — at 4 consecutive
garbled turns the patient cannot communicate at all and continued attempts
waste tokens with no chance of resolution.
"""
from dataclasses import dataclass, field
from enum import Enum


class SilenceMode(str, Enum):
    """Which silence-timeout profile is currently active."""

    DEFAULT = "default"          # no wait request, no emergency
    WAIT_REQUESTED = "wait"      # LLM judged patient asked to wait
    EMERGENCY = "emergency"      # emergency keyword detected earlier in call


class Directive(str, Enum):
    """What the agent should do in response to a silence/garble event."""

    NONE = "none"                # no action; keep waiting
    PROMPT_1 = "prompt_1"        # AI should emit first re-prompt
    PROMPT_2 = "prompt_2"        # AI should emit second re-prompt
    HANGUP = "hangup"            # close session with goodbye message
    GARBLED_RETRY = "garbled"    # ask patient to repeat
    GARBLED_HANGUP = "garbled_hangup"  # 4th garbled turn → close


# Timeout table (seconds elapsed since silence began OR since AI's last word)
# Indexed by mode → list[seconds] for [prompt1, prompt2, hangup]
_TIMEOUTS: dict[SilenceMode, tuple[float, float, float]] = {
    SilenceMode.DEFAULT:        (5.0, 7.0, 10.0),
    SilenceMode.WAIT_REQUESTED: (15.0, 30.0, 45.0),
    SilenceMode.EMERGENCY:      (10.0, 14.0, 20.0),  # 2x of DEFAULT (silence only)
}

# In emergency mode, wait-requested silence ALSO extends 2x:
_EMERGENCY_WAIT_TIMEOUTS: tuple[float, float, float] = (30.0, 60.0, 90.0)

# Garbled-input counter — uniform across all modes (no per-mode override).
GARBLED_PROMPT_LIMIT = 3   # 3 prompts emitted, then HANGUP on the 4th failed turn


@dataclass
class SilenceState:
    """Mutable per-call silence-tracking state. One instance per call."""

    mode: SilenceMode = SilenceMode.DEFAULT
    emergency_detected: bool = False  # if True, mode shifts to EMERGENCY automatically
    prompts_emitted: int = 0          # 0, 1, or 2 (incremented as prompts fire)
    garbled_count: int = 0            # 0-3; HANGUP on 4 (i.e., count would become 4)
    # Tracked by the agent and passed in — silence_handler is stateless re. time.

    def reset_silence(self) -> None:
        """Called by agent when user speaks or AI responds (silence broken)."""
        self.prompts_emitted = 0

    def reset_garbled(self) -> None:
        """Called by agent on first comprehensible turn after a garbled streak."""
        self.garbled_count = 0

    def mark_emergency(self) -> None:
        """Called by agent when an emergency keyword fires (one-way: never resets)."""
        self.emergency_detected = True
        # Mode upgrades to EMERGENCY unless WAIT_REQUESTED (which takes priority for
        # wait-specific timeouts; emergency × 2 still applies to wait timeouts below)
        if self.mode == SilenceMode.DEFAULT:
            self.mode = SilenceMode.EMERGENCY

    def mark_wait_requested(self) -> None:
        """Called by agent when LLM signals patient asked to wait (or extend tool)."""
        self.mode = SilenceMode.WAIT_REQUESTED

    def clear_wait(self) -> None:
        """Called when patient resumes normal interaction. Drops back to DEFAULT
        (or EMERGENCY if emergency was previously detected)."""
        if self.emergency_detected:
            self.mode = SilenceMode.EMERGENCY
        else:
            self.mode = SilenceMode.DEFAULT


def _timeouts_for(state: SilenceState) -> tuple[float, float, float]:
    """Return (prompt1_at, prompt2_at, hangup_at) seconds for the current state."""
    if state.mode == SilenceMode.WAIT_REQUESTED:
        # Wait mode in emergency context: × 2 on wait timeouts
        if state.emergency_detected:
            return _EMERGENCY_WAIT_TIMEOUTS
        return _TIMEOUTS[SilenceMode.WAIT_REQUESTED]
    return _TIMEOUTS[state.mode]


def decide_silence_directive(state: SilenceState, elapsed_seconds: float) -> Directive:
    """Pure decision: given current state + elapsed silence time, what to do.

    Called by agent's silence watchdog on each tick. Idempotent — calling with
    the same arguments twice in a row returns the same directive (the agent
    decides whether to act once per threshold crossing using state.prompts_emitted).

    Args:
        state: SilenceState (mode, prompts_emitted, etc.)
        elapsed_seconds: how long the patient has been silent

    Returns:
        Directive — NONE / PROMPT_1 / PROMPT_2 / HANGUP
    """
    prompt1_at, prompt2_at, hangup_at = _timeouts_for(state)

    if elapsed_seconds >= hangup_at:
        return Directive.HANGUP
    if elapsed_seconds >= prompt2_at and state.prompts_emitted < 2:
        return Directive.PROMPT_2
    if elapsed_seconds >= prompt1_at and state.prompts_emitted < 1:
        return Directive.PROMPT_1
    return Directive.NONE


def decide_garbled_directive(state: SilenceState) -> Directive:
    """Pure decision: caller has just produced garbled input. What to do?

    Increment counter (caller's responsibility — call state.garbled_count += 1 BEFORE
    calling this). At limit, HANGUP. Otherwise, RETRY.

    UNIFORM ACROSS ALL MODES — emergency does not extend the garbled counter.
    Rationale: at 4 failed turns the patient cannot communicate at all; emergency
    contact has already been spoken; continued attempts only waste tokens.
    """
    if state.garbled_count > GARBLED_PROMPT_LIMIT:
        return Directive.GARBLED_HANGUP
    return Directive.GARBLED_RETRY


# Canned messages — used when LLM is unavailable OR for the final HANGUP message.
# The agent normally lets the LLM pick prompt content for PROMPT_1 / PROMPT_2 based
# on conversation context. These canned strings are the floor — always available.
CANNED_HANGUP_DEFAULT = "Tarvath mali clinic ki call cheyandi. Dhanyavadalu."
CANNED_HANGUP_GARBLED = "Mee phone sound sariga ledu. Mali try cheyandi please. Dhanyavadalu."
CANNED_GARBLED_RETRY = "Naaku sound saripoga vinipinchledu. Mali cheppagalara?"
CANNED_PROMPT_1_FALLBACK = "Vintunaru?"
CANNED_PROMPT_2_FALLBACK = "Hello? Sound vinipistunda?"
