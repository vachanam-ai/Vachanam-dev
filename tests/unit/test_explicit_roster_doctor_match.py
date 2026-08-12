"""A caller must be able to name any doctor on the roster, in Telugu.

Live failure 2026-08-12 (session call-4c2b9e8d): the caller asked for
"విష్ణు వర్ధన్ గారి టైమింగ్స్" and the agent kept answering with Lakshmi's
schedule, because the whole-name skeleton 'vsnvrdnrdy' is not a substring of
the spoken 'vsnvrdngrtmgstd'. That doctor could never be named. It stuck
because _resolve_doctor_id returns caller_named_doctor_id unconditionally, so
one missed match latches the wrong doctor for the rest of the call.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from agent.livekit_minimal.agent import _explicit_roster_doctor_id

VISHNU = str(uuid.uuid4())
SRINIVAS = str(uuid.uuid4())
LAKSHMI = str(uuid.uuid4())

ROSTER = [
    SimpleNamespace(id=VISHNU, name="vishnu vardhan reddy"),
    SimpleNamespace(id=SRINIVAS, name="Srinivas"),
    SimpleNamespace(id=LAKSHMI, name="Lakshmi"),
]


@pytest.mark.parametrize("utterance, expected", [
    # The exact live failure: partial name, Telugu, honorific attached.
    ("ఈ విష్ణు వర్ధన్ గారి టైమింగ్స్ ఏంటండీ?", VISHNU),
    # Full name spoken — "రెడ్డి గారి" fuses, so this failed too.
    ("విష్ణు వర్ధన్ రెడ్డి గారి టైమింగ్స్", VISHNU),
    # Single-word names already worked; they must keep working.
    ("లక్ష్మి గారి టైమింగ్స్ ఏంటండీ?", LAKSHMI),
    ("శ్రీనివాస్ గారి అపాయింట్‌మెంట్ కావాలి", SRINIVAS),
    # Latin script, mixed in — real callers code-mix.
    ("Dr Lakshmi timings", LAKSHMI),
])
def test_caller_can_name_any_doctor(utterance, expected):
    assert str(_explicit_roster_doctor_id(utterance, ROSTER)) == expected


def test_no_doctor_named_leaves_state_untouched():
    assert _explicit_roster_doctor_id("నాకు రేపు అపాయింట్‌మెంట్ కావాలి", ROSTER) is None


def test_ambiguous_surname_is_not_guessed():
    """Two Reddys and a bare surname must NOT silently pick one."""
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        SimpleNamespace(id=a, name="vishnu vardhan reddy"),
        SimpleNamespace(id=b, name="anitha reddy"),
    ]
    assert _explicit_roster_doctor_id("రెడ్డి గారి టైమింగ్స్", roster) is None


def test_a_full_name_beats_a_token_collision():
    """Whole-name hits are resolved before per-token ones.

    "Lakshmi" matches wholly; "Lakshmi Narayana" only on a token. The caller
    said exactly the first doctor's name, so the exact tier settles it rather
    than the pair being treated as ambiguous. Note the limit: a caller who
    means Lakshmi Narayana must say more than "Lakshmi".
    """
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        SimpleNamespace(id=a, name="Lakshmi"),
        SimpleNamespace(id=b, name="Lakshmi Narayana"),
    ]
    assert str(_explicit_roster_doctor_id("లక్ష్మి గారు", roster)) == a
    # ...and naming the longer doctor in full still reaches her.
    assert str(_explicit_roster_doctor_id("లక్ష్మి నారాయణ గారు", roster)) == b
