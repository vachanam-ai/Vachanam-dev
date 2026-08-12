"""A stdlib logger call must never carry structlog-style keyword fields.

`agent/livekit_minimal/agent.py` binds `logger = logging.getLogger(...)`, but
the codebase also uses structlog, so `logger.info("event", token=..., state=...)`
reads as correct and passes review. It is not: stdlib `Logger._log` accepts only
exc_info/stack_info/stacklevel/extra, so the call raises

    TypeError: Logger._log() got an unexpected keyword argument 'token'

...but ONLY when that level is enabled. Under the default WARNING level
`isEnabledFor` short-circuits before `_log`, so it is silent in a test run and
explodes in production, which runs LOG_LEVEL=info.

Live cost: two calls on the reminder dial path (`reminder_retry_closed`,
`reminder_dial_blocked`) shipped this way. Vinay fixed them in a9fa516 on
2026-08-11; an agent deploy built from a working tree that predated that commit
put them straight back into production on 2026-08-12, because `flyctl deploy`
builds the WORKING TREE, not a git ref. Nothing failed loudly either time.
"""
from __future__ import annotations

import ast
import pathlib

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# Everything stdlib Logger._log actually accepts.
_ALLOWED = {"exc_info", "stack_info", "stacklevel", "extra"}


def _offenders() -> list[str]:
    bad: list[str] = []
    roots = (pathlib.Path("agent"), pathlib.Path("backend"))
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            # Only modules whose logger is a stdlib one. structlog loggers take
            # kwargs by design and must not be flagged.
            if "logging.getLogger" not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:  # not ours to police here
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _LOG_METHODS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"logger", "log"}
                ):
                    continue
                for keyword in node.keywords:
                    if keyword.arg and keyword.arg not in _ALLOWED:
                        bad.append(
                            f"{path}:{node.lineno} "
                            f"logger.{node.func.attr}(..., {keyword.arg}=...)"
                        )
    return sorted(set(bad))


def test_no_structlog_kwargs_on_a_stdlib_logger():
    offenders = _offenders()
    assert not offenders, (
        "stdlib logger called with structlog-style fields — this raises "
        "TypeError at runtime whenever the level is enabled:\n  "
        + "\n  ".join(offenders)
        + "\nUse %s formatting: logger.info('event k=%s', value)"
    )


def test_the_guard_actually_detects_the_bug(tmp_path, monkeypatch):
    """A guard that cannot fail proves nothing — plant the real bug and catch it."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "agent" / "boom.py").write_text(
        "import logging\n"
        'logger = logging.getLogger("x")\n'
        'logger.info("reminder_retry_closed", token="a", state="b")\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    found = _offenders()
    assert len(found) == 2, found  # one per offending keyword
    assert all("boom.py:3" in item for item in found)


def test_stdlib_logger_really_raises_at_info_level(caplog):
    """Pin the behaviour this guard is protecting, so it survives a Python bump."""
    import logging

    import pytest

    logger = logging.getLogger("vachanam-guard-probe")
    with caplog.at_level(logging.INFO, logger="vachanam-guard-probe"):
        with pytest.raises(TypeError, match="unexpected keyword argument 'token'"):
            logger.info("reminder_retry_closed", token="x", state="y")
