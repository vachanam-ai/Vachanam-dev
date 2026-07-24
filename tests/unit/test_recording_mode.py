"""Temporary production recording is notice-first and admin-only."""
from pathlib import Path

from backend.config import Settings

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_recording_phone_match_normalizes_indian_formats():
    cfg = Settings(recording_enabled=True, admin_phone="+91 98765 43210")
    assert cfg.recording_allowed_for("98765-43210") is True
    assert cfg.recording_allowed_for("+91 90000 00000") is False
    assert cfg.recording_allowed_for(None) is False


def test_every_session_start_has_an_explicit_record_decision():
    gate = SRC.split("await gate_session.start(", 1)[1][:350]
    main = SRC.split("_start_task = asyncio.create_task(", 1)[1].split(
        "# Time session.start()", 1
    )[0]
    assert "record=False" in gate
    assert "record=(" in main


def test_main_recording_is_audio_only():
    record_block = SRC.split("record=(", 1)[1].split("room_input_options", 1)[0]
    assert '"audio": True' in record_block
    for field in ("transcript", "traces", "logs"):
        assert f'"{field}": False' in record_block
    assert "if _recording_active else False" in record_block


def test_notice_finishes_before_session_start_and_failure_is_unrecorded():
    notice = SRC.index("recording_notice_completed before_capture=True")
    start = SRC.index("_start_task = asyncio.create_task", notice)
    assert notice < start
    fail_closed = SRC[notice:start]
    assert "_recording_active = False" in fail_closed
    assert "recording_fail_closed" in fail_closed


def test_recording_consent_row_is_written_only_when_active():
    consent = SRC.split("consent_type=\"recording\"", 1)[0]
    assert "if _recording_active:" in consent[-800:]
    assert 'notice_version="admin-test-audio-1.0"' in SRC
