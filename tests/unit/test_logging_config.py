"""Unit tests for agent/logging_config.py — Gap 3 bootstrap.

Tests:
  1. configure_structlog_idempotent    — call twice, no exception
  2. configure_structlog_produces_json — captured stdout is valid JSON with 'event' key
  3. configure_structlog_includes_filename_lineno — 'filename' + 'lineno' keys present
"""
import json
import sys
from io import StringIO

import pytest
import structlog

from agent.logging_config import configure_structlog


class TestConfigureStructlog:
    def test_configure_structlog_idempotent(self) -> None:
        """Calling configure_structlog twice must not raise any exception."""
        configure_structlog(log_level="WARNING")
        configure_structlog(log_level="WARNING")  # second call — must be harmless

    def test_configure_structlog_produces_json(self, capsys: pytest.CaptureFixture) -> None:
        """A log call after configure_structlog must produce valid JSON on stdout
        with at least an 'event' key.
        """
        configure_structlog(log_level="DEBUG")
        logger = structlog.get_logger()
        logger.info("test_event_probe", probe=True)

        captured = capsys.readouterr()
        stdout = captured.out.strip()
        # There may be multiple lines if earlier log lines were flushed.
        # Find the line containing our probe event.
        matching_line: str | None = None
        for line in stdout.splitlines():
            try:
                data = json.loads(line)
                if data.get("event") == "test_event_probe":
                    matching_line = line
                    break
            except json.JSONDecodeError:
                continue

        assert matching_line is not None, (
            f"No JSON line with event='test_event_probe' found in stdout.\n"
            f"Full captured output:\n{stdout}"
        )
        parsed = json.loads(matching_line)
        assert "event" in parsed, "JSON log record must contain 'event' key"

    def test_configure_structlog_includes_filename_lineno(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Each log record must include 'filename' and 'lineno' keys
        (added by CallsiteParameterAdder).
        """
        configure_structlog(log_level="DEBUG")
        logger = structlog.get_logger()
        logger.debug("callsite_probe", check="filename_lineno")

        captured = capsys.readouterr()
        stdout = captured.out.strip()

        matching_line: str | None = None
        for line in stdout.splitlines():
            try:
                data = json.loads(line)
                if data.get("event") == "callsite_probe":
                    matching_line = line
                    break
            except json.JSONDecodeError:
                continue

        assert matching_line is not None, (
            f"No JSON line with event='callsite_probe' found in stdout.\n"
            f"Full captured output:\n{stdout}"
        )
        parsed = json.loads(matching_line)
        assert "filename" in parsed, "JSON log record must contain 'filename' key"
        assert "lineno" in parsed, "JSON log record must contain 'lineno' key"
