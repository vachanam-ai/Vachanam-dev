"""Re-exports backend Calendar service for agent runtime.

Agent and backend share the same google-api-python-client install. Both Render
(backend) and Fly.io (agent) mount the SA JSON via env var (GOOGLE_SA_JSON_B64
in production; GOOGLE_APPLICATION_CREDENTIALS in dev).

Usage in agent code:
    from agent.services.calendar_proxy import GoogleCalendarService, CalendarNotConfiguredError

See backend/services/calendar_service.py for full implementation.
See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.1.
"""
from backend.services.calendar_service import (  # noqa: F401 — re-export
    CalendarNotConfiguredError,
    CalendarService,
    CalendarWriteFailed,
    GoogleCalendarService,
)

__all__ = [
    "GoogleCalendarService",
    "CalendarService",  # legacy shim — keeps old booking_tools.py working
    "CalendarNotConfiguredError",
    "CalendarWriteFailed",
]
