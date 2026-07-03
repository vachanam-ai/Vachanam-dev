"""LLM-as-judge scoring job — the feedback loop's automatic reviewer (step 3).

Reads captured call transcripts and writes a DERIVED, non-PII quality read back
onto the call_quality row: an overall score (1-5), issue tags from a fixed
vocabulary, and a one-line PII-FREE summary. These power the feedback loop
(find what to improve) and the super-admin monitoring page (aggregates only).

Design:
  - Runs from the APScheduler leader (backend/main.py), batched + idempotent
    (only rows with a transcript and judged_at IS NULL).
  - The transcript already goes to Gemini during the live call (Gemini IS the
    conversation LLM) and Gemini is a disclosed sub-processor (DPA), so scoring
    it server-side adds no new data flow. The stored OUTPUT is non-PII.
  - Cheap: gemini-2.5-flash-lite, thinking_budget=0, JSON output, small batches.
  - Tenant isolation: each row carries branch_id; one transcript judged at a
    time, written back to the same row — no cross-tenant mixing.

Per CLAUDE.md: Rule 1 (branch_id on every row), Rule 9 (the judge is instructed
to keep its summary PII-free), Rule 10 (structlog on the run).
"""
import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

import backend.database as _db_module
from backend.config import settings
from backend.models.schema import CallQuality

logger = structlog.get_logger()

# Fixed issue-tag vocabulary — keeps tags aggregatable across calls/clinics.
ISSUE_TAGS = [
    "good",                      # nothing wrong — a clean call
    "misrouted",                 # wrong doctor / specialty for the complaint
    "hallucinated",              # stated a fact no tool returned (hours, price, name)
    "stt_mishear",               # acted on a clearly mis-transcribed name/number/word
    "off_policy",                # broke a hard rule (promised SMS, gave medical advice, etc.)
    "cold_or_rude",              # tone not warm / not the receptionist register
    "abandoned_unnecessarily",   # gave up on a bookable call
    "slow_or_repetitive",        # looped, repeated itself, dragged
    "language_issue",            # wrong/awkward/robotic language for the caller
]

_RUBRIC = (
    "You are a strict QA reviewer for an AI phone receptionist that books clinic "
    "appointments. Read the call transcript (patient/agent turns) and score the "
    "AGENT's performance.\n\n"
    "Return ONLY JSON: {\"score\": <int 1-5>, \"tags\": [<tags>], \"summary\": <string>}.\n"
    "score: 1=poor, 5=excellent (correctness, policy adherence, warmth, efficiency).\n"
    f"tags: choose from EXACTLY this list, 1-3 that apply: {ISSUE_TAGS}.\n"
    "summary: ONE short sentence on what to improve. CRITICAL — it must be PII-FREE: "
    "NEVER include the patient's name, phone number, age, or specific health details; "
    "describe the ISSUE, not the person (e.g. 'agent invented working hours', not "
    "'told Ravi the clinic opens at 9').\n"
    "If the call is clean, score 5 and tags ['good'].\n\n"
    "TRANSCRIPT:\n"
)


# B21: retire a transcript after this many failed judge attempts so it stops
# starving newer calls and re-burning LLM calls every run.
MAX_JUDGE_ATTEMPTS = 3


async def _judge_transcript(transcript: str, language: str | None) -> dict | None:
    """Call the judge LLM for one transcript → {score, tags, summary} or None on
    failure. Isolated so the scoring loop (and tests) can swap it out.

    B20: uses the ASYNC Gemini client (`client.aio...`) — the scoring job runs
    on the SAME asyncio loop as the FastAPI app (in-process APScheduler), so the
    old SYNCHRONOUS client blocked the loop for the full LLM round-trip per row
    (a 50-row batch stalled every request + scheduled job for tens of seconds).
    """
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=_RUBRIC + transcript,
            config=genai_types.GenerateContentConfig(
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        data = json.loads(resp.text or "{}")
    except Exception as exc:  # noqa: BLE001 — a bad row must not kill the batch
        logger.warning("judge_llm_failed", error=str(exc))
        return None

    score = data.get("score")
    if not isinstance(score, int) or not (1 <= score <= 5):
        return None
    tags = [t for t in (data.get("tags") or []) if t in ISSUE_TAGS][:3]
    summary = (data.get("summary") or "").strip()[:300]
    return {"score": score, "tags": tags or ["good"], "summary": summary}


async def run_call_scoring(batch: int = 50) -> None:
    """Score a batch of unjudged transcripts. Idempotent (judged_at gate)."""
    if not settings.gemini_api_key:
        # Visible skip (2026-07-03): 63 prod calls sat unjudged with zero
        # attempts — a silent return here hides a missing key forever.
        logger.warning("call_scoring_skipped_no_gemini_key")
        return
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CallQuality)
                .where(
                    CallQuality.transcript.is_not(None),
                    CallQuality.judged_at.is_(None),
                )
                .order_by(CallQuality.created_at.asc())
                .limit(batch)
            )
        ).scalars().all()

        scored = 0
        retired = 0
        failed = 0
        for row in rows:
            verdict = await _judge_transcript(row.transcript, row.language)
            if verdict is None:
                # B21: count the failed attempt; retire the row after the cap so
                # a permanently-failing transcript stops being re-selected every
                # run (head-of-line blocking of all newer calls).
                row.judge_attempts = (row.judge_attempts or 0) + 1
                failed += 1
                if row.judge_attempts >= MAX_JUDGE_ATTEMPTS:
                    row.judge_tags = ["judge_error"]  # sentinel; no score
                    row.judged_at = datetime.now(timezone.utc)
                    retired += 1
                continue
            row.judge_score = verdict["score"]
            row.judge_tags = verdict["tags"]
            row.judge_summary = verdict["summary"]
            row.judged_at = datetime.now(timezone.utc)
            scored += 1

        # Commit whenever ANYTHING changed — including a bare attempt increment,
        # otherwise the B21 counter would roll back and the row could loop forever.
        if scored or retired or failed:
            await db.commit()
            logger.info(
                "call_scoring_run",
                scored=scored, retired=retired, failed=failed, batch_seen=len(rows),
            )
