"""Telugu STT bench: Soniox JP stt-rt-v5 vs Sarvam saaras:v3.

Answers the one question the latency ladder can't: `stt_finalize_ms` p50 is
409ms in the Cartesia sandbox and 380ms in production, both on Soniox Japan.
Is that the Tokyo round trip, or Soniox's endpointing decision? Sarvam is
in-region, so running the SAME audio through both separates the two.

Run it on the Fly bom worker, not a laptop — the network under test IS the
result:

    flyctl ssh console -a vachanam-agent-sandbox -C \
      "python scripts/benchmark_stt.py --pstn sandbox/gemini-live/samples/*.wav"

Audio is paced in real time (20ms frames). Endpointing only behaves like a
real call when the audio arrives like a real call; pushing the whole file at
once measures nothing. `--pstn` resamples to 8kHz first, which is what a
Vobiz SIP leg actually delivers.

Reports, per provider per clip:
  first_interim_ms  — end of audio -> first partial transcript
  final_ms          — end of audio -> FINAL transcript (this is stt_finalize)
  transcript        — for eyeballing Telugu accuracy; pass --truth for CER
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit import rtc
from livekit.agents import stt as agent_stt
from livekit.agents.utils import http_context

FRAME_MS = 20


def load_pcm(path: Path, target_rate: int) -> tuple[bytes, int]:
    """Mono 16-bit PCM at target_rate, anti-alias filtered.

    Nearest-neighbour decimation was tried first and both providers returned
    EMPTY transcripts from clean speech — 24k->8k without a low-pass folds
    every harmonic above 4kHz back over the formants. resample_poly filters."""
    import numpy as np
    from scipy.signal import resample_poly

    with wave.open(str(path)) as w:
        assert w.getsampwidth() == 2, f"{path}: expected 16-bit"
        rate, ch = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())

    samples = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        samples = samples[::ch]
    if rate != target_rate:
        g = math.gcd(rate, target_rate)
        samples = resample_poly(samples.astype(np.float32),
                                target_rate // g, rate // g)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes(), target_rate


def cer(hyp: str, ref: str) -> float:
    """Character error rate — word-level WER is meaningless across Telugu
    tokenizations that disagree about where a word ends."""
    a, b = ref.replace(" ", ""), hyp.replace(" ", "")
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(len(a), 1)


def build(provider: str, lang: str):
    from backend.config import settings

    if provider == "soniox":
        from livekit.plugins import soniox

        return soniox.STT(
            api_key=settings.soniox_jp_api_key,
            base_url=settings.soniox_jp_stt_ws_url,
            params=soniox.STTOptions(
                model="stt-rt-v5",
                language_hints=[lang],
                language_hints_strict=True,
                max_endpoint_delay_ms=settings.soniox_max_endpoint_delay_ms,
                endpoint_sensitivity=settings.soniox_endpoint_sensitivity,
                endpoint_latency_adjustment_level=settings.soniox_endpoint_latency_level,
            ),
        )
    if provider == "sarvam":
        from livekit.plugins import sarvam

        return sarvam.STT(
            api_key=settings.sarvam_api_key,
            model="saaras:v3",
            language=f"{lang}-IN",
            flush_signal=True,
        )
    raise SystemExit(f"unknown provider {provider}")


SILENCE_MS = 1500


async def run_clip(provider: str, lang: str, pcm: bytes, rate: int) -> dict:
    """Time from END OF SPEECH to the final transcript — the same span the live
    ladder calls `stt_finalize_ms`.

    Two things this has to get right or it measures nothing:
    trailing silence must keep flowing after the words stop (that silence is
    what endpointing decides on — a real caller stops talking, the RTP keeps
    coming), and finals that land mid-clip must be kept, because Sarvam
    finalizes per VAD segment rather than once at the end."""
    stt = build(provider, lang)
    stream = stt.stream()
    result: dict = {"first_interim_ms": None, "final_ms": None, "text": ""}
    marks: dict = {"speech_end": None}
    finals: list[tuple[float, str]] = []

    async def collect() -> None:
        async for ev in stream:
            now = time.perf_counter()
            if ev.type == agent_stt.SpeechEventType.INTERIM_TRANSCRIPT:
                if result["first_interim_ms"] is None and marks["speech_end"]:
                    result["first_interim_ms"] = (now - marks["speech_end"]) * 1000
            elif ev.type == agent_stt.SpeechEventType.FINAL_TRANSCRIPT:
                if ev.alternatives and ev.alternatives[0].text:
                    finals.append((now, ev.alternatives[0].text))

    task = asyncio.create_task(collect())
    chunk = int(rate * FRAME_MS / 1000) * 2
    silence = b"\x00" * chunk
    speech_frames = (len(pcm) - chunk) // chunk
    total_frames = speech_frames + SILENCE_MS // FRAME_MS
    t0 = time.perf_counter()
    for i in range(total_frames):
        data = pcm[i * chunk:(i + 1) * chunk] if i < speech_frames else silence
        stream.push_frame(rtc.AudioFrame(
            data=data, sample_rate=rate,
            num_channels=1, samples_per_channel=chunk // 2))
        if i == speech_frames - 1:
            marks["speech_end"] = time.perf_counter()
        # Pace to wall clock so endpointing sees a real speaking rate.
        await asyncio.sleep(max(0, (i + 1) * FRAME_MS / 1000 - (time.perf_counter() - t0)))
    stream.end_input()
    await asyncio.sleep(2.0)  # let a late final land

    await stream.aclose()
    task.cancel()
    await stt.aclose()

    if finals:
        result["text"] = " ".join(t for _, t in finals)
        result["final_ms"] = (finals[-1][0] - marks["speech_end"]) * 1000
    return result


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--lang", default="te")
    ap.add_argument("--pstn", action="store_true", help="resample to 8kHz first")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--truth", help="file of ground-truth lines, one per clip")
    args = ap.parse_args()

    rate = 8000 if args.pstn else 16000
    truth = Path(args.truth).read_text(encoding="utf-8").splitlines() if args.truth else []

    for provider in ("soniox", "sarvam"):
        print(f"\n=== {provider} ({'8kHz PSTN' if args.pstn else '16kHz'}) ===")
        finals: list[float] = []
        for idx, clip in enumerate(args.clips):
            pcm, r = load_pcm(Path(clip), rate)
            for run in range(args.repeat):
                try:
                    res = await run_clip(provider, args.lang, pcm, r)
                except Exception as exc:  # noqa: BLE001 - bench, report and continue
                    print(f"  {Path(clip).name} run{run} ERROR {exc}")
                    continue
                if res["final_ms"] is not None:
                    finals.append(res["final_ms"])
                fmt = lambda v: f"{round(v):>5}" if v is not None else "    -"  # noqa: E731
                print(f"  {Path(clip).name:16} run{run} "
                      f"interim={fmt(res['first_interim_ms'])} final={fmt(res['final_ms'])} "
                      f"| {res['text'][:70]}")
                if truth and idx < len(truth) and run == 0:
                    print(f"    CER={cer(res['text'], truth[idx]):.3f} vs: {truth[idx][:60]}")
        if finals:
            print(f"  final_ms n={len(finals)} min={min(finals):.0f} "
                  f"med={statistics.median(finals):.0f} max={max(finals):.0f}")


async def _entry() -> None:
    # Plugins fetch their aiohttp session from the worker's job context; outside
    # the worker we have to open one ourselves.
    async with http_context.open():
        await main()


if __name__ == "__main__":
    asyncio.run(_entry())
