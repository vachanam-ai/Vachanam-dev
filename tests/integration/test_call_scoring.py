"""Proof for the LLM-as-judge scoring job (feedback loop, step 3).

- Only rows WITH a transcript and judged_at IS NULL are scored.
- Scoring writes derived non-PII fields (score/tags/summary/judged_at).
- Idempotent: a second run does not re-score.
- A None verdict (LLM failure) leaves the row unjudged for retry.
The LLM call (_judge_transcript) is monkeypatched — no real Gemini call.
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

import backend.jobs.call_scoring as scoring
from backend.config import settings
from backend.models.schema import Branch, CallQuality, Organization

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def branch(db):
    org = Organization(
        name="Score Org", owner_phone="+919000777001",
        owner_email=f"sc-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="Score Branch",
        whatsapp_number=f"+9177{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return b


async def test_scoring_judges_only_unjudged_with_transcript(branch, db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    calls = {"n": 0}

    async def _fake_judge(transcript, language):
        calls["n"] += 1
        return {"score": 4, "tags": ["misrouted"], "summary": "agent picked the wrong doctor"}

    monkeypatch.setattr(scoring, "_judge_transcript", _fake_judge)

    has_transcript = CallQuality(branch_id=branch.id, language="te",
                                 transcript="patient: ... / agent: ...", created_at=datetime.now(timezone.utc))
    no_transcript = CallQuality(branch_id=branch.id, language="te",
                                transcript=None, created_at=datetime.now(timezone.utc))
    already = CallQuality(branch_id=branch.id, language="te", transcript="x",
                          judge_score=5, judged_at=datetime.now(timezone.utc),
                          created_at=datetime.now(timezone.utc))
    db.add_all([has_transcript, no_transcript, already])
    await db.commit()
    scored_id, skip_id = has_transcript.id, no_transcript.id

    await scoring.run_call_scoring(batch=50)
    assert calls["n"] == 1  # only the one eligible row hit the LLM

    db.expire_all()
    scored = (await db.execute(select(CallQuality).where(CallQuality.id == scored_id))).scalar_one()
    assert scored.judge_score == 4
    assert scored.judge_tags == ["misrouted"]
    assert scored.judged_at is not None
    skipped = (await db.execute(select(CallQuality).where(CallQuality.id == skip_id))).scalar_one()
    assert skipped.judged_at is None  # no transcript → never judged


async def test_scoring_is_idempotent(branch, db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    calls = {"n": 0}

    async def _fake_judge(transcript, language):
        calls["n"] += 1
        return {"score": 5, "tags": ["good"], "summary": "clean call"}

    monkeypatch.setattr(scoring, "_judge_transcript", _fake_judge)
    row = CallQuality(branch_id=branch.id, transcript="t", created_at=datetime.now(timezone.utc))
    db.add(row)
    await db.commit()

    await scoring.run_call_scoring(batch=50)
    await scoring.run_call_scoring(batch=50)  # second pass must not re-judge
    assert calls["n"] == 1


async def test_scoring_failure_leaves_row_unjudged(branch, db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)

    async def _fail(t, lang):
        return None

    monkeypatch.setattr(scoring, "_judge_transcript", _fail)  # LLM failed
    row = CallQuality(branch_id=branch.id, transcript="t", created_at=datetime.now(timezone.utc))
    db.add(row)
    await db.commit()
    rid = row.id

    await scoring.run_call_scoring(batch=50)
    db.expire_all()
    again = (await db.execute(select(CallQuality).where(CallQuality.id == rid))).scalar_one()
    assert again.judged_at is None  # one failed attempt → retried next run
    assert again.judge_attempts == 1  # B21: attempt counted


async def test_b20_judge_transcript_is_async_awaitable():
    """B20: _judge_transcript must be a coroutine so the scoring loop can await
    it (async Gemini client) instead of blocking the shared event loop."""
    import inspect

    assert inspect.iscoroutinefunction(scoring._judge_transcript)


async def test_b21_permanently_failing_row_retired_after_cap(branch, db, monkeypatch):
    """B21: a transcript whose judge call permanently fails must be retired after
    MAX_JUDGE_ATTEMPTS runs (judged_at stamped with a sentinel), so it stops
    being re-selected every run and starving newer calls."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)

    async def _fail(t, lang):
        return None

    monkeypatch.setattr(scoring, "_judge_transcript", _fail)
    row = CallQuality(branch_id=branch.id, transcript="bad", created_at=datetime.now(timezone.utc))
    db.add(row)
    await db.commit()
    rid = row.id

    # Run once per attempt up to the cap.
    for _ in range(scoring.MAX_JUDGE_ATTEMPTS):
        await scoring.run_call_scoring(batch=50)

    db.expire_all()
    retired = (await db.execute(select(CallQuality).where(CallQuality.id == rid))).scalar_one()
    assert retired.judge_attempts >= scoring.MAX_JUDGE_ATTEMPTS
    assert retired.judged_at is not None, "row must be retired (no longer re-selected)"
    assert retired.judge_tags == ["judge_error"]
    assert retired.judge_score is None  # sentinel: retired, not actually scored

    # A subsequent run must NOT re-select it (it now has judged_at set).
    seen = {"n": 0}

    async def _count(t, lang):
        seen["n"] += 1
        return None

    monkeypatch.setattr(scoring, "_judge_transcript", _count)
    await scoring.run_call_scoring(batch=50)
    assert seen["n"] == 0, "retired row must not be re-judged"
