"""Integration tests: verify booking tools are registered with VachananAgent.

These tests do NOT start LiveKit, connect to Vobiz, or hit real infrastructure.
They call _make_booking_tools() with a mocked SessionState and inspect the list
of FunctionTool objects that LiveKit's Agent receives.

genai and AsyncOpenAI are imported lazily inside _llm_call (only called at
routing time), so _make_booking_tools() can be exercised here without those
packages needing to be installed in the test environment.

Acceptance criteria (from D4 dispatch):
  1. _make_booking_tools() returns exactly 4 tools.
  2. All 4 expected tool names are present.
"""
from uuid import uuid4

import pytest

from agent.agent import _make_booking_tools
from agent.session_state import SessionState


EXPECTED_TOOL_NAMES = {
    "route_to_doctor",
    "check_availability",
    "assign_token",
    "confirm_booking",
}


def _make_state() -> SessionState:
    state = SessionState()
    state.branch_id = uuid4()
    state.plan = "clinic"
    return state


def test_make_booking_tools_returns_exactly_4():
    """_make_booking_tools() must return a list of exactly 4 function tools."""
    tools = _make_booking_tools(_make_state())
    assert len(tools) == 4, (
        f"Expected 4 tools, got {len(tools)}: {[type(t).__name__ for t in tools]}"
    )


def test_booking_tool_names_match_expected():
    """All 4 tools must carry the correct snake_case names matching EXPECTED_TOOL_NAMES."""
    tools = _make_booking_tools(_make_state())

    # LiveKit function_tool wraps the function; name lives on .name or .__name__
    actual_names: set[str] = set()
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            actual_names.add(name)

    assert actual_names == EXPECTED_TOOL_NAMES, (
        f"Tool name mismatch. Expected {EXPECTED_TOOL_NAMES}, got {actual_names}"
    )
