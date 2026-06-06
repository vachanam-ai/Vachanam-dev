"""Structlog JSON config for Vachanam — shared by agent + backend.

Call configure_structlog() once at process start before any logger use.
JSON output goes to stdout. Timestamps in ISO 8601 UTC.

Usage
-----
from agent.logging_config import configure_structlog

configure_structlog(log_level="INFO")   # call once, before first logger use
"""
import logging
import sys

import structlog


def configure_structlog(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output to stdout.

    Idempotent — safe to call multiple times. Sets:
    - JSON renderer (machine-parseable)
    - ISO 8601 UTC timestamps
    - Caller filename + line number (debug aid)
    - stdlib logging integration so libraries (asyncpg, httpx)
      also emit JSON-formatted records.

    Args:
        log_level: Standard Python log level string e.g. "INFO", "DEBUG",
                   "WARNING". Defaults to "INFO". Unknown strings fall back
                   to INFO.
    """
    level: int = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
