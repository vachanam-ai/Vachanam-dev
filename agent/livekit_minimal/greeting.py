"""Instant REAL greeting at answer (Vinay 2026-07-05: "within 2 seconds the
agent needs to speak — not a prerecorded message but the original conversation").

Replaces the canned welcome-bridge clip and the pre-rendered outbound mask:
the actual per-call opening (clinic welcome + disclosure / greet-by-name /
reminder / doctor's question) is synthesized fresh over the raw smallest.ai
REST /tts and streamed into the room on a temporary track, CONCURRENT with
session.start(). Outbound calls synthesize during RING time, so the patient
hears the real opening the instant they answer.

Composition helpers are pure (unit-testable). Segments stay SHORT — one long
single-shot synth reads rushed/garbled (prod 2026-07-03). RULE 6: every text
is sanitized here, at the synth boundary. RULE 8: callers treat any failure
as "speak the same segments live after session.start" — never a dead call.
"""
from __future__ import annotations

import asyncio
import io
import time as time_mod
import wave
from datetime import date as date_cls
from datetime import time as time_cls

import httpx
import structlog
from livekit import rtc

from agent.i18n import get_lines, get_welcome
from agent.services.telugu_dates import telugu_date, telugu_time
from agent.services.tts_sanitizer import sanitize_for_tts
from backend.config import settings

logger = structlog.get_logger()

_TTS_URL = "https://api.smallest.ai/waves/v1/tts"
_SPEED = 1.0  # matches the live agent — Vinay 07-06: normal speed (1.1 rushed)


def normalize_pcm(pcm: bytes, peak_target: float = 0.89, max_gain: float = 6.0) -> bytes:
    """Peak-normalize 16-bit PCM. Measured 2026-07-05 (Vinay: "voice is low"):
    smallest voices differ ~13 dB — padmaja (our te default) RMS 1107 vs anitha
    4971 — and clinic-cloned voices are arbitrary. Bring every voice to a
    consistent, phone-loud level. Gain capped so a near-silent/noisy clip is
    never blasted into hiss."""
    import numpy as np

    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return pcm
    peak = float(np.abs(a).max())
    if peak < 1.0:
        return pcm
    gain = min(peak_target * 32767.0 / peak, max_gain)
    if gain <= 1.02:  # already loud enough — don't touch
        return pcm
    return np.clip(a * gain, -32768, 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------- composition

def inbound_greeting_texts(
    lang_code: str,
    spk_clinic: str,
    spk_caller: str | None = None,
    followup_message: str | None = None,
) -> list[str]:
    """Segments of the REAL inbound opening. Mirrors the session.say fallback
    exactly — both paths must speak the same words (disclosure included, DPDP)."""
    lines = get_lines(lang_code)
    out = [get_welcome(lang_code).format(clinic=spk_clinic)]
    if followup_message and lines.inbound_followup_greeting:
        raw = lines.inbound_followup_greeting
        if raw.endswith("{message}"):
            pre = raw[: -len("{message}")].strip()
            if spk_caller and lines.followup_name_prefix:
                pre = lines.followup_name_prefix.format(patient=spk_caller) + pre
            out += [pre, followup_message]
        else:
            out.append(raw.format(message=followup_message))
    elif spk_caller:
        # Trimmed ONE-sentence intro (Vinay 2026-07-10) — replaces the
        # welcome+greeting pair; carries its own namaskaram + AI disclosure.
        if lines.inbound_intro_known:
            return [lines.inbound_intro_known.format(patient=spk_caller, clinic=spk_clinic)]
        out.append(lines.known_caller_greeting.format(patient=spk_caller, clinic=spk_clinic))
    else:
        if lines.inbound_intro:
            return [lines.inbound_intro.format(clinic=spk_clinic)]
        out.append(lines.disclosure_greeting.format(clinic=spk_clinic))
    return out


def outbound_greeting_texts(
    lang_code: str,
    spk_clinic: str,
    spk_patient: str,
    spk_doctor: str,
    meta: dict,
    followup_meta: dict,
    *,
    is_reminder: bool = False,
    is_rebook: bool = False,
    is_followup: bool = False,
) -> list[str]:
    """Segments of the REAL outbound opening (welcome line + call-type body).
    The i18n outbound bodies deliberately drop the leading namaskaram — the
    welcome segment speaks it."""
    lines = get_lines(lang_code)
    out = [get_welcome(lang_code).format(clinic=spk_clinic)]
    if is_reminder:
        raw_t = meta.get("appointment_time", "")
        try:
            t = time_cls.fromisoformat(raw_t)
            spoken_time = telugu_time(t) if lang_code == "te" else t.strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            spoken_time = raw_t
        out.append(lines.reminder_greeting.format(
            patient=spk_patient, clinic=spk_clinic, doctor=spk_doctor, time=spoken_time,
        ))
    elif is_rebook:
        raw_d = meta.get("cancelled_date", "")
        try:
            d = date_cls.fromisoformat(raw_d)
            spoken_date = telugu_date(d) if lang_code == "te" else d.strftime("%d %B").lstrip("0")
        except ValueError:
            spoken_date = raw_d
        out.append(lines.rebook_greeting.format(
            patient=spk_patient, clinic=spk_clinic, doctor=spk_doctor, date=spoken_date,
        ))
    elif is_followup:
        msg = (followup_meta.get("message") or "").strip()
        if msg and lines.followup_greeting_q:
            fg = lines.followup_greeting_q.format(
                patient=spk_patient, clinic=spk_clinic, message=msg
            )
            # Doctor's question as its OWN segment (prosody + must land in full).
            if fg.endswith(msg):
                out += [fg[: -len(msg)].strip(), msg]
            else:
                out.append(fg)
        elif lines.followup_greeting_noq:
            out.append(lines.followup_greeting_noq.format(patient=spk_patient, clinic=spk_clinic))
        else:
            out.append(lines.known_caller_greeting.format(patient=spk_patient, clinic=spk_clinic))
    return out


# ------------------------------------------------------------------ synthesis

async def _synth_one(client: httpx.AsyncClient, text: str, voice_id: str, lang_code: str) -> bytes:
    resp = await client.post(
        _TTS_URL,
        headers={
            "Authorization": f"Bearer {settings.smallest_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.smallest_model,
            "voice_id": voice_id,
            "sample_rate": settings.smallest_sample_rate,
            "speed": _SPEED,
            "language": lang_code,
            "output_format": "wav",
            "text": sanitize_for_tts(text),  # RULE 6 — nothing reaches TTS unsanitized
        },
    )
    resp.raise_for_status()
    return resp.content


async def synth_wavs(texts: list[str], voice_id: str, lang_code: str) -> list[bytes]:
    """Synthesize every segment concurrently. Raises on any failure — the
    caller falls back to the live session.say path (RULE 8)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        return list(await asyncio.gather(
            *(_synth_one(client, t, voice_id, lang_code) for t in texts)
        ))


# ------------------------------------------------------------------- playback

async def play_wavs(room: rtc.Room, wav_items, t_answer: float | None = None) -> bool:
    """Play WAV clips (bytes or awaitables of bytes) sequentially on ONE
    temporary track, then unpublish. Returns True only when EVERY segment
    played — the DPDP disclosure/consent record depends on completeness.

    Queue sized for the whole greeting: session.start() connects on the same
    event loop and starves a small capture queue mid-clip ("words breaking",
    2026-06-24) — buffering everything makes playout engine-driven."""
    source = None
    pub = None
    sr0 = ch0 = None
    ok = False
    try:
        for item in wav_items:
            wav = item if isinstance(item, (bytes, bytearray)) else await item
            wf = wave.open(io.BytesIO(wav), "rb")
            sr, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
            pcm = normalize_pcm(wf.readframes(n))
            wf.close()
            if source is None:
                sr0, ch0 = sr, ch
                source = rtc.AudioSource(sr, ch, queue_size_ms=60_000)
                track = rtc.LocalAudioTrack.create_audio_track("greeting", source)
                pub = await room.local_participant.publish_track(
                    track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
                )
                if t_answer is not None:
                    logger.info(
                        "lat_first_word",
                        answer_to_first_audio=round(time_mod.monotonic() - t_answer, 2),
                    )
            elif (sr, ch) != (sr0, ch0):
                logger.warning("greeting_segment_rate_mismatch", sr=sr, expected=sr0)
                return False
            spf = sr // 100  # 10ms frames
            fb = spf * 2 * ch
            for i in range(0, len(pcm), fb):
                chunk = pcm[i : i + fb]
                if len(chunk) < fb:
                    chunk = chunk + b"\x00" * (fb - len(chunk))
                await source.capture_frame(
                    rtc.AudioFrame(data=chunk, sample_rate=sr, num_channels=ch,
                                   samples_per_channel=spf)
                )
        if source is not None:
            await source.wait_for_playout()
            ok = True
    except Exception as e:  # noqa: BLE001 — a greeting clip must never break a call
        logger.warning("greeting_play_failed", error=str(e)[:160])
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


def _greeting_cache_key(branch_id: str, lang_code: str, voice_id: str, texts: list[str]) -> str:
    """#439: key the cached welcome audio by branch+lang+voice AND a hash of the
    exact text, so a clinic rename / template change auto-misses (never serves
    a stale greeting)."""
    import hashlib

    h = hashlib.sha1(("||".join(texts)).encode("utf-8")).hexdigest()[:12]
    return f"greet:v1:{branch_id}:{lang_code}:{voice_id}:{h}"


async def _greeting_cache_get(key: str) -> list[bytes] | None:
    try:
        import base64
        import json as _json

        from backend.redis_client import get_redis

        r = await get_redis()
        raw = await r.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return [base64.b64decode(b) for b in _json.loads(raw)]
    except Exception as e:  # noqa: BLE001 — cache never breaks the call
        logger.warning("greeting_cache_read_failed", error=str(e)[:120])
        return None


async def _greeting_cache_set(key: str, wavs: list[bytes]) -> None:
    try:
        import base64
        import json as _json

        from backend.redis_client import get_redis

        r = await get_redis()
        await r.set(
            key, _json.dumps([base64.b64encode(w).decode("ascii") for w in wavs]),
            ex=7 * 24 * 3600,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("greeting_cache_write_failed", error=str(e)[:120])


async def synth_and_play(
    room: rtc.Room, texts: list[str], voice_id: str, lang_code: str,
    t_answer: float | None = None, cache_key: str | None = None,
) -> bool:
    """Inbound path: pipeline synth + playback — segment 1 starts playing while
    later segments are still synthesizing, so first audio ≈ one REST round-trip.

    #439: when cache_key is given (STATIC unknown-caller welcome), the audio is
    served from Redis (instant, ~0 synth) instead of a ~10s live smallest.ai
    synth on every call — the call-start latency that made callers hang up. The
    first call for a (branch, lang, voice, text) synths and stores; every call
    after plays the cached bytes. Dynamic greetings (caller's name) pass
    cache_key=None and always synth live."""
    try:
        if cache_key:
            cached = await _greeting_cache_get(cache_key)
            if cached is not None:
                logger.info("greeting_cache_hit", key=cache_key)
                return await play_wavs(room, cached, t_answer=t_answer)
            # Miss: synth everything, play, and store for next time.
            wavs = await synth_wavs(texts, voice_id, lang_code)
            asyncio.create_task(_greeting_cache_set(cache_key, wavs))
            return await play_wavs(room, wavs, t_answer=t_answer)
        # No cache (dynamic greeting): the original pipelined synth+play.
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [
                asyncio.ensure_future(_synth_one(client, t, voice_id, lang_code))
                for t in texts
            ]
            try:
                return await play_wavs(room, tasks, t_answer=t_answer)
            finally:
                for t in tasks:
                    t.cancel()
    except Exception as e:  # noqa: BLE001 — RULE 8
        logger.warning("greeting_synth_failed", error=str(e)[:160])
        return False
