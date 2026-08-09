"""Measure sequential Cartesia WebSocket first-audio latency.

Uses the same model, voice, language, tokenizer, and persistent connection as
the voice agent.  It consumes every response completely so the connection is
returned to the pool and the next sample genuinely measures reuse.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from statistics import median

import aiohttp
from livekit.agents import tokenize
from livekit.plugins import cartesia

from backend.config import settings


TELUGU_SAMPLES = (
    "అవును అండి. నేను వెంటనే చూసి చెబుతాను.",
    "డాక్టర్ గారు రేపు ఉదయం అందుబాటులో ఉన్నారు.",
    "మీ అపాయింట్మెంట్ విజయవంతంగా బుక్ అయింది.",
)
SANDBOX_VOICE = "cf061d8b-a752-4865-81a2-57570a6e0565"


async def benchmark(samples: int) -> list[dict[str, float | bool]]:
    async with aiohttp.ClientSession() as http:
        engine = cartesia.TTS(
            api_key=settings.cartesia_api_key,
            model=settings.cartesia_model,
            voice=settings.cartesia_voice or SANDBOX_VOICE,
            language="te",
            sample_rate=settings.cartesia_sample_rate,
            word_timestamps=False,
            http_session=http,
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=8,
                stream_context_len=4,
                retain_format=True,
            ),
        )
        engine.prewarm()
        await asyncio.sleep(1)

        rows: list[dict[str, float | bool]] = []
        for index in range(samples):
            stream = engine.stream()
            started = time.perf_counter()
            first_audio: float | None = None
            stream.push_text(TELUGU_SAMPLES[index % len(TELUGU_SAMPLES)])
            stream.end_input()
            async for _event in stream:
                if first_audio is None:
                    first_audio = (time.perf_counter() - started) * 1000
            await stream.aclose()
            row = {
                "ttfb_ms": first_audio or -1.0,
                "acquire_ms": stream._acquire_time * 1000,
                "connection_reused": stream._connection_reused,
            }
            rows.append(row)
            print(
                f"sample={index + 1} ttfb_ms={row['ttfb_ms']:.1f} "
                f"acquire_ms={row['acquire_ms']:.1f} "
                f"connection_reused={row['connection_reused']}"
            )

        await engine.aclose()
        print(f"p50_ttfb_ms={median(float(r['ttfb_ms']) for r in rows):.1f}")
        return rows


async def benchmark_after_cancellations(samples: int) -> None:
    """Reproduce preemptive TTS cancellation followed by a real response."""
    async with aiohttp.ClientSession() as http:
        engine = cartesia.TTS(
            api_key=settings.cartesia_api_key,
            model=settings.cartesia_model,
            voice=settings.cartesia_voice or SANDBOX_VOICE,
            language="te",
            sample_rate=settings.cartesia_sample_rate,
            word_timestamps=False,
            http_session=http,
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=8, stream_context_len=4, retain_format=True,
            ),
        )
        engine.prewarm()
        await asyncio.sleep(1)
        for index in range(samples):
            speculative = engine.stream()
            speculative.push_text(TELUGU_SAMPLES[1] * 4)
            speculative.end_input()
            async for _event in speculative:
                break
            await speculative.aclose()

            real = engine.stream()
            started = time.perf_counter()
            real.push_text(TELUGU_SAMPLES[index % len(TELUGU_SAMPLES)])
            real.end_input()
            first_audio: float | None = None
            async for _event in real:
                if first_audio is None:
                    first_audio = (time.perf_counter() - started) * 1000
            await real.aclose()
            print(
                f"after_cancel={index + 1} ttfb_ms={first_audio:.1f} "
                f"acquire_ms={real._acquire_time * 1000:.1f} "
                f"connection_reused={real._connection_reused}"
            )
        await engine.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--after-cancellations", action="store_true")
    args = parser.parse_args()
    if args.after_cancellations:
        asyncio.run(benchmark_after_cancellations(args.samples))
    else:
        asyncio.run(benchmark(args.samples))


if __name__ == "__main__":
    main()
