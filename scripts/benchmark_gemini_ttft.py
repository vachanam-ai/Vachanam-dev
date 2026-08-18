"""Benchmark Gemini first-token latency with Vachanam's real prompt/tools.

Reads GEMINI_API_KEY from the root .env without printing it.  This is a
diagnostic, not part of the call path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.livekit_minimal.agent import VachanamAgent, _cached_content_tool_dicts
from agent.prompts.system_prompt import DoctorContext
from agent.prompts.grounded_prompt import build_grounded_prompt
from agent.services.meta_stub import MetaService
from agent.session_state import SessionState


def _fixture() -> tuple[str, list[dict]]:
    doctors = [
        DoctorContext(
            id="doctor-1",
            name="Dr. Venkateshwara",
            specialization="Dermatologist",
            routing_keywords=["skin", "hair", "allergy", "చర్మం"],
            booking_type="appointment",
            is_default=True,
            schedule_mode="date_specific",
        ),
        DoctorContext(
            id="doctor-2",
            name="Dr. Lakshmi",
            specialization="General Physician",
            routing_keywords=["fever", "cold", "జ్వరం"],
            booking_type="token",
            is_default=False,
            schedule_mode="date_specific",
        ),
    ]
    prompt = build_grounded_prompt(
        clinic_name="Venkateshwara Clinic",
        doctors=doctors,
        emergency_contact="NOT PROVIDED",
        plan="clinic",
        language="te",
        clinic_address="Hyderabad",
        faq=[
            {"q": "Do you accept walk-ins?", "a": "Only when the doctor has capacity."},
            {"q": "What are the fees?", "a": "Use the database fee returned by the tool."},
        ],
        recording_active=True,
    )
    prompt += f"\nTODAY IS {date.today().isoformat()}."
    schema_agent = VachanamAgent(
        instructions="schema",
        state=SessionState(),
        db=None,
        room=None,
        calendar_service=None,
        meta_service=MetaService(),
        transfer_to="",
    )
    return prompt, _cached_content_tool_dicts(schema_agent.tools)


async def _one(
    client: genai.Client,
    model: str,
    prompt: str,
    tools: list[dict],
    cache: str | None,
    priority: bool,
) -> float:
    thinking = (
        types.ThinkingConfig(thinking_budget=0)
        if model.startswith("gemini-2.5")
        else types.ThinkingConfig(thinking_level="minimal")
    )
    config = types.GenerateContentConfig(
        system_instruction=None if cache else prompt,
        tools=None if cache else tools,
        cached_content=cache,
        thinking_config=thinking,
        max_output_tokens=80,
        service_tier="priority" if priority else None,
    )
    started = time.perf_counter()
    stream = await client.aio.models.generate_content_stream(
        model=model,
        contents="రేపు ఉదయం డాక్టర్ పది గంటలకు అందుబాటులో ఉన్నారా?",
        config=config,
    )
    async for chunk in stream:
        if chunk.candidates:
            return (time.perf_counter() - started) * 1000
    raise RuntimeError("Gemini stream ended without a candidate")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=6)
    parser.add_argument(
        "--models",
        nargs="+",
        default=["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
    )
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--priority", action="store_true")
    parser.add_argument(
        "--vertex",
        action="store_true",
        help="benchmark Vertex asia-south1 using the local service account",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env", override=False)
    if args.vertex:
        credential = ROOT / "google-service-account.json"
        project = json.loads(credential.read_text(encoding="utf-8"))["project_id"]
        import os

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credential)
        client = genai.Client(
            vertexai=True, project=project, location="asia-south1"
        )
    else:
        client = genai.Client()
    prompt, tools = _fixture()
    counted = await client.aio.models.count_tokens(model=args.models[0], contents=prompt)
    print(f"prompt_tokens={counted.total_tokens} tools={len(tools[0].get('function_declarations', []))}")

    for model in args.models:
        cache_name = None
        if args.cached:
            cache = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=prompt,
                    tools=tools,
                    ttl="300s",
                    display_name=f"vachanam-ttft-{int(time.time())}",
                ),
            )
            cache_name = cache.name
            print(f"{model} cached_tokens={cache.usage_metadata.total_token_count}")
        try:
            samples = []
            for _ in range(args.runs):
                samples.append(
                    await _one(client, model, prompt, tools, cache_name, args.priority)
                )
            ordered = sorted(samples)
            p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
            print(
                f"{model} cache={bool(cache_name)} priority={args.priority} samples_ms="
                f"{','.join(f'{x:.1f}' for x in samples)} "
                f"p50={statistics.median(samples):.1f} p95={p95:.1f}"
            )
        finally:
            if cache_name:
                await client.aio.caches.delete(name=cache_name)


if __name__ == "__main__":
    asyncio.run(main())
