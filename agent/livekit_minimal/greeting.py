"""Instant REAL greeting at answer (Vinay 2026-07-05: "within 2 seconds the
agent needs to speak — not a prerecorded message but the original conversation").

Replaces the canned welcome-bridge clip and the pre-rendered outbound mask:
the actual per-call opening (clinic welcome + disclosure / greet-by-name /
reminder / doctor's question) is synthesized through Soniox tts-rt and streamed
into the room on a temporary track, CONCURRENT with
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
import uuid
from datetime import date as date_cls
from datetime import time as time_cls

import structlog
from livekit import rtc

from agent.i18n import get_lines, get_recording_notice, get_welcome
from agent.services.telugu_dates import telugu_date, telugu_time
from agent.services.tts_sanitizer import sanitize_for_tts
from backend.config import settings

logger = structlog.get_logger()

# ── Soniox voice seam (single source — agent.py imports these) ─────────────
# Current Soniox tts-rt-v1 catalog. A UUID is a project-scoped cloned voice;
# ownership/readiness is enforced by the branch API before it reaches this row.
SONIOX_TTS_VOICES = {
    "Maya", "Daniel", "Noah", "Nina", "Emma", "Jack", "Adrian", "Claire",
    "Grace", "Owen", "Mina", "Kenji", "Rafael", "Mateo", "Lucia", "Sofia",
    "Oliver", "Arthur", "Isla", "Victoria", "Cooper", "Mason", "Ruby", "Elise",
    "Arjun", "Rohan", "Priya", "Meera",
}


def resolve_soniox_voice(voice_id: str) -> str:
    if voice_id in SONIOX_TTS_VOICES:
        return voice_id
    try:
        uuid.UUID(str(voice_id))
        return str(voice_id)
    except (ValueError, TypeError, AttributeError):
        return settings.soniox_tts_default_voice


def greeting_voice_key(voice_id: str) -> str:
    """Soniox voice component for the greeting Redis cache key."""
    return f"sx:{resolve_soniox_voice(voice_id)}"


def normalize_pcm(pcm: bytes, peak_target: float = 0.89, max_gain: float = 6.0) -> bytes:
    """Peak-normalize 16-bit PCM. Measured 2026-07-05 (Vinay: "voice is low"):
    catalog voices can differ in level. Bring every voice to a
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
    recording_active: bool = False,
) -> list[str]:
    """Segments of the REAL inbound opening. Mirrors the session.say fallback
    exactly — both paths must speak the same words (disclosure included, DPDP)."""
    lines = get_lines(lang_code)
    prefix = [get_recording_notice(lang_code)] if recording_active else []
    out = prefix + [get_welcome(lang_code).format(clinic=spk_clinic)]
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
            return prefix + [lines.inbound_intro_known.format(patient=spk_caller, clinic=spk_clinic)]
        out.append(lines.known_caller_greeting.format(patient=spk_caller, clinic=spk_clinic))
    else:
        if lines.inbound_intro:
            return prefix + [lines.inbound_intro.format(clinic=spk_clinic)]
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
    is_question_answer: bool = False,
    recording_active: bool = False,
) -> list[str]:
    """Segments of the REAL outbound opening (welcome line + call-type body).
    The i18n outbound bodies deliberately drop the leading namaskaram — the
    welcome segment speaks it."""
    lines = get_lines(lang_code)
    out = ([get_recording_notice(lang_code)] if recording_active else []) + [
        get_welcome(lang_code).format(clinic=spk_clinic)
    ]
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
    elif is_question_answer:
        # Question-answer callback (2026-08-02). The framing sentence ("you had
        # asked us X, here is the clinic's answer") is composed by the dispatcher
        # and translated into the call's language by _localize_message, so this
        # needs no new hand-written copy per language — only the existing
        # honorific prefix. Answer stays its OWN segment (prosody, lands whole).
        msg = (followup_meta.get("message") or "").strip()
        if msg:
            prefix = (
                lines.followup_name_prefix.format(patient=spk_patient)
                if spk_patient and lines.followup_name_prefix
                else ""
            )
            out.append(f"{prefix}{msg}" if prefix else msg)
    return out


# ------------------------------------------------------------------ synthesis

async def _synth_wavs_soniox(texts: list[str], voice_id: str, lang_code: str) -> list[bytes]:
    """Synthesize segments via Soniox tts-rt (one-shot synthesize per segment,
    sequential on ONE persistent connection) and wrap the PCM in WAV containers
    so the whole downstream machinery (Redis cache, play_wavs, filler PCM decode)
    is provider-agnostic. Raises on failure — caller falls back (RULE 8)."""
    from livekit.plugins import soniox as _sx

    tts = _sx.TTS(
        model=settings.soniox_tts_model,
        voice=resolve_soniox_voice(voice_id),
        language=lang_code,
        sample_rate=settings.soniox_tts_sample_rate,
        api_key=settings.soniox_jp_api_key,
        websocket_url=settings.soniox_jp_tts_ws_url,
    )
    try:
        out: list[bytes] = []
        for text in texts:
            frames: list[bytes] = []
            sr = settings.soniox_tts_sample_rate
            ch = 1
            # Cache warmers run outside Fly's low-latency Mumbai path and can
            # legitimately take >15s for a long disclosure. A timeout here loses
            # the cache and makes the next caller pay live synthesis, the worst
            # possible fallback. Live session TTS has its own retry policy.
            async with asyncio.timeout(30):
                async for ev in tts.synthesize(sanitize_for_tts(text)):  # RULE 6
                    frame = getattr(ev, "frame", None)
                    if frame is not None:
                        frames.append(bytes(frame.data))
                        sr, ch = frame.sample_rate, frame.num_channels
            if not frames:
                raise RuntimeError("soniox synth returned no audio")
            buf = io.BytesIO()
            wf = wave.open(buf, "wb")
            wf.setnchannels(ch)
            wf.setsampwidth(2)  # pcm_s16le
            wf.setframerate(sr)
            wf.writeframes(b"".join(frames))
            wf.close()
            out.append(buf.getvalue())
        return out
    finally:
        try:
            await tts.aclose()
        except Exception:  # noqa: BLE001 — cleanup must not mask a synth result
            pass


async def _synth_wavs_cartesia(texts: list[str], lang_code: str) -> list[bytes]:
    """Cartesia equivalent of the Soniox path, same WAV-out contract.

    Deliberately raw REST rather than the livekit plugin: the greeting warmer
    runs on a background thread, and constructing a plugin there raises
    "Plugins must be registered on the main thread" — which silently emptied
    the whole greeting cache (requested=17 ready=0, 2026-08-12). Soniox only
    escapes this because agent.py imports its plugin at module scope.

    One-shot synthesis also has no use for a streaming client. Cartesia returns
    a WAV container directly, so the downstream cache/playout stays
    provider-agnostic. Raises on failure — caller falls back (RULE 8)."""
    import json as _json

    import aiohttp

    if not settings.cartesia_api_key:
        raise RuntimeError("TTS_PROVIDER=cartesia but CARTESIA_API_KEY is unset")

    out: list[bytes] = []
    async with aiohttp.ClientSession() as sess:
        for text in texts:
            payload = {
                "model_id": settings.cartesia_model,
                "transcript": sanitize_for_tts(text),  # RULE 6
                "language": lang_code,
                # RAW, not "wav": Cartesia's WAV container ships a placeholder
                # frame count (a 2.6s clip declared 89,478s), and play_wavs
                # sizes its read from getnframes(). We wrap the PCM ourselves
                # so the header is honest, same as the Soniox path.
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": settings.cartesia_sample_rate,
                },
            }
            if settings.cartesia_voice:
                payload["voice"] = {"mode": "id", "id": settings.cartesia_voice}
            # Warmers run outside the low-latency path; a short timeout here
            # loses the cache and makes the next caller pay live synthesis.
            async with asyncio.timeout(30):
                async with sess.post(
                    "https://api.cartesia.ai/tts/bytes",
                    data=_json.dumps(payload),
                    headers={
                        "X-API-Key": settings.cartesia_api_key,
                        "Cartesia-Version": "2024-06-10",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:200]
                        raise RuntimeError(
                            f"cartesia synth HTTP {resp.status}: {body}"
                        )
                    pcm = await resp.read()
            if not pcm:
                raise RuntimeError("cartesia synth returned no audio")
            buf = io.BytesIO()
            wf = wave.open(buf, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)  # pcm_s16le
            wf.setframerate(settings.cartesia_sample_rate)
            wf.writeframes(pcm)
            wf.close()
            out.append(buf.getvalue())
    return out


async def synth_wavs(texts: list[str], voice_id: str, lang_code: str) -> list[bytes]:
    """Synthesize greeting segments through the CONFIGURED TTS provider.

    This was Soniox-only, so a Cartesia deployment greeted the caller in
    Soniox's Priya and then switched to a different voice for the conversation
    — one call, two people (Vinay heard this 2026-08-12). The greeting is
    cached per (voice, language) in Redis, so the provider has to be part of
    what the cache key already distinguishes, or a provider swap would serve
    the previous engine's audio.
    """
    if (settings.tts_provider or "soniox").lower() == "cartesia":
        return await _synth_wavs_cartesia(texts, lang_code)
    return await _synth_wavs_soniox(texts, voice_id, lang_code)


# ------------------------------------------------------------------- playback

async def play_wavs(room: rtc.Room, wav_items, t_answer: float | None = None) -> bool:
    """Play WAV clips (bytes or awaitables of bytes/lists) sequentially on ONE
    temporary track, then unpublish. Returns True only when EVERY segment
    played — the DPDP disclosure/consent record depends on completeness.

    Queue sized for the whole greeting: session.start() connects on the same
    event loop and starves a small capture queue mid-clip ("words breaking",
    2026-06-24) — buffering everything makes playout engine-driven."""
    source = None
    pub = None
    sr0 = ch0 = None
    ok = False
    pending = list(wav_items)
    try:
        # A prepared outbound item may resolve to several WAV segments. Keep a
        # mutable queue so the cached welcome can play immediately while the
        # dynamic reminder/follow-up body is still being synthesized.
        while pending:
            item = pending.pop(0)
            wav = item if isinstance(item, (bytes, bytearray)) else await item
            if isinstance(wav, (list, tuple)):
                pending[0:0] = list(wav)
                continue
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
        # If an earlier segment failed or playback was cancelled, do not leave
        # dynamic-body synthesis running without an awaiter.
        for item in pending:
            if isinstance(item, asyncio.Task) and not item.done():
                item.cancel()
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
    a stale greeting).

    The TTS PROVIDER is part of the key (2026-08-12). Without it a Cartesia
    deployment kept serving the Soniox audio already cached under the same
    branch/lang/voice, so the greeting stayed in the old voice no matter what
    synth_wavs did. v1 -> v2 also retires every greeting cached before that fix.
    """
    import hashlib

    provider = (settings.tts_provider or "soniox").lower()
    h = hashlib.sha1(("||".join(texts)).encode("utf-8")).hexdigest()[:12]
    return f"greet:v2:{provider}:{branch_id}:{lang_code}:{voice_id}:{h}"


async def _greeting_cache_get(key: str) -> list[bytes] | None:
    try:
        import base64
        import json as _json

        from backend.redis_client import get_redis

        r = get_redis()
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

        r = get_redis()
        await r.set(
            key, _json.dumps([base64.b64encode(w).decode("ascii") for w in wavs]),
            ex=7 * 24 * 3600,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("greeting_cache_write_failed", error=str(e)[:120])


async def warm_greeting_cache(
    key: str, texts: list[str], voice_id: str, lang_code: str
) -> bool:
    """Ensure one static greeting is synthesized before a caller needs it."""
    if await _greeting_cache_get(key) is not None:
        return True
    try:
        wavs = await synth_wavs(texts, voice_id, lang_code)
        await _greeting_cache_set(key, wavs)
        return True
    except Exception as e:  # noqa: BLE001 — background warm never breaks calls
        logger.warning("greeting_cache_warm_failed", key=key, error=str(e)[:160])
        return False


async def _cached_or_synth_segment(
    key: str, text: str, voice_id: str, lang_code: str
) -> list[bytes]:
    """Return one static segment from Redis, synthesizing only on a miss."""
    cached = await _greeting_cache_get(key)
    if cached is not None:
        logger.info("outbound_greeting_cache_hit", key=key)
        return cached
    wavs = await synth_wavs([text], voice_id, lang_code)
    asyncio.create_task(_greeting_cache_set(key, wavs))
    return wavs


def prepare_outbound_prefix_items(
    branch_id: str,
    prefix_texts: list[str],
    voice_id: str,
    lang_code: str,
    *,
    recording_active: bool = False,
) -> list[asyncio.Task]:
    """Start resolving the static outbound opening without blocking its caller.

    Each prefix is an independent task. `play_wavs` can therefore publish
    the first cached segment as soon as the phone is answered; it does not wait
    for names, message translation, or the dynamic call body.
    """
    items: list[asyncio.Task] = []
    for index, text in enumerate(prefix_texts):
        cache_branch = (
            "recording-notice"
            if recording_active and index == 0
            else f"outbound:{branch_id}"
        )
        key = _greeting_cache_key(
            cache_branch, lang_code, greeting_voice_key(voice_id), [text]
        )
        items.append(asyncio.create_task(
            _cached_or_synth_segment(key, text, voice_id, lang_code)
        ))
    return items


async def synth_and_play(
    room: rtc.Room, texts: list[str], voice_id: str, lang_code: str,
    t_answer: float | None = None, cache_key: str | None = None,
) -> bool:
    """Inbound path: pipeline synth + playback — segment 1 starts playing while
    later segments are still synthesizing, so first audio ≈ one REST round-trip.

    #439: when cache_key is given (STATIC unknown-caller welcome), the audio is
    served from Redis (instant, ~0 synth) instead of live Soniox synthesis. The
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
        wavs = await synth_wavs(texts, voice_id, lang_code)
        return await play_wavs(room, wavs, t_answer=t_answer)
    except Exception as e:  # noqa: BLE001 — RULE 8
        logger.warning("greeting_synth_failed", error=str(e)[:160])
        return False
