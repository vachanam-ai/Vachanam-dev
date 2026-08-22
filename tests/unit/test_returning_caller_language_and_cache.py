"""Regression guards for returning-caller language and cache critical path."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = (ROOT / "agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
MIGRATION = (
    ROOT / "alembic/versions/kkkk57_caller_language_preferences.py"
).read_text(encoding="utf-8")


def test_intro_uses_branch_and_phone_language_before_playback():
    assert 'proc.userdata["caller_languages"] = caller_languages' in AGENT
    assert "_start_early_greeting(cached_route, _caller_lang)" in AGENT
    assert 'f"{cached_route[\'id\']}:{_caller_digits[-10:]}"' in AGENT


def test_legacy_disabled_branch_language_is_blocked_before_early_audio():
    assert "if _warm_default_lang not in supported_codes():" in AGENT
    assert "if default_lang not in supported_codes():" in AGENT


def test_prompt_cache_read_overlaps_remaining_call_setup():
    start = AGENT.index("_main_cache_task = asyncio.create_task(")
    finish = AGENT.index("_cached_llm = await _main_cache_task")
    # Calendar construction and handoff-cache preparation happen while the
    # current-language Redis cache read is already in flight.
    between = AGENT[start:finish]
    assert "_handoff_cache_specs" in between
    assert "calendar_service" in between


def test_language_migration_backfills_existing_patients_and_cascades():
    assert 'down_revision = "jjjj56_founding_unlimited_trial"' in MIGRATION
    assert "SELECT DISTINCT ON (branch_id, phone_last10)" in MIGRATION
    assert 'ondelete="CASCADE"' in MIGRATION
