"""Instant pre-session welcome clip — kills start-of-call silence.

Measured (Fly bom, 2026-06-21): smallest.ai TTS ttfb ~0.19s, but the main
AgentSession's connect adds ~3s before it can speak — so after pickup the caller
heard several seconds of dead air ("10 seconds before it speaks"). We synth a
short welcome and publish it straight into the room the moment the branch is
resolved, well before session.start(), so the first thing the caller hears is a
warm "welcome to <clinic> clinic" — not silence.

Best-effort by design: ANY failure just skips the clip and the normal disclosure
greeting still plays (RULE 8 — never break a live call, never dead-air a crash).

ponytail: sequential (welcome → session.start → disclosure). A residual gap
remains between the welcome and the disclosure while session.start connects;
overlapping the two needs a second audio track without colliding with the
agent's own publish — not worth the live-call risk until proven necessary.
"""
from __future__ import annotations

import structlog
from livekit import rtc

logger = structlog.get_logger()


async def play_welcome(room: rtc.Room, text: str, tts) -> bool:
    """Synthesize `text` with the given LiveKit TTS plugin and play it into the
    room on a temporary track. Blocks until the clip finishes playing out, then
    unpublishes so session.start() can publish the agent's own audio track.

    Returns True only if the clip was synthesized and played to completion — the
    caller uses this to decide whether an outbound greeting still needs to be
    spoken after session.start() (if the clip failed, it must be; RULE 8)."""
    import time as _time

    _t0 = _time.monotonic()
    source = None
    pub = None
    ok = False
    try:
        # Build the AudioSource from the FIRST frame's OWN sample_rate/channels —
        # not tts.sample_rate. A mismatch between the source's declared rate and
        # the real frame rate makes LiveKit's playout clock wrong (the clip plays
        # stretched/slow — 06-21: 3.7s of audio took ~12s). _samples tracks the
        # true audio duration so we can compare it against wall-clock playout.
        _samples = 0
        async for ev in tts.synthesize(text):
            f = ev.frame
            if source is None:
                logger.info(
                    "welcome_clip_first_frame",
                    sr=f.sample_rate,
                    ch=f.num_channels,
                    synth_s=round(_time.monotonic() - _t0, 2),  # TTS time-to-first-frame
                )  # patient starts hearing audio
                source = rtc.AudioSource(f.sample_rate, f.num_channels)
                track = rtc.LocalAudioTrack.create_audio_track("welcome", source)
                pub = await room.local_participant.publish_track(
                    track,
                    rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
                )
                _sr = f.sample_rate
            _samples += f.samples_per_channel
            await source.capture_frame(f)
        if source is not None:
            await source.wait_for_playout()
            logger.info("welcome_clip_done", audio_s=round(_samples / max(_sr, 1), 2))
            ok = True
    except Exception as e:  # noqa: BLE001 — a welcome clip must never break a call
        logger.warning("welcome_clip_failed", error=str(e)[:160])
    finally:
        if pub is not None:
            try:
                await room.local_participant.unpublish_track(pub.sid)
            except Exception:  # noqa: BLE001
                pass
        if source is not None:
            try:
                await source.aclose()
            except Exception:  # noqa: BLE001
                pass
    return ok
