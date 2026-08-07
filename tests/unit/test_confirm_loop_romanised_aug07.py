"""The "shall I book it?" loop, second occurrence — 2026-08-07, prod.

Vinay: "it is unable to book appointments. it got struck in loop 'shall i
book' and never booking."

The Fly logs for that call show confirm_booking blocked on turns 28, 29 and 30
with `booking_blocked_no_caller_authorization`, `language=hi`, and then the
caller hanging up. 2026-08-03 fixed the QUESTION side of this deadlock (the
guard now arms `pending_confirmation` instead of string-matching its own
transcript). The ANSWER side was still a phrase list, and it had two holes:

1. NO ROMANISED FORMS. Every entry was English or native script, but Soniox
   returns Hindi speech in Latin letters, so a caller saying "haan" produced
   no match at all. There is no number of times they can agree that works.

2. THE NEGATION TEST HAD NO WORD BOUNDARIES. It read the letters "no" inside
   "now", so "yes, book it now" was classified as a refusal.

The structural fix: once the guard has DEMANDED the confirmation question, the
answer authorizes unless it is a refusal. The guard's own ToolError tells the
model to ask "in the active language" — so the reply arrives in one of seven
languages in whichever script the STT chose, and a fixed list of yeses can
never be complete. Refusal stays deterministic and fails closed.
"""
import inspect

import pytest

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _caller_affirmed,
    _caller_declined,
    _caller_refused_outright,
)


# ── 1. romanised agreement is agreement ──────────────────────────────────────

@pytest.mark.parametrize("said", [
    # Hindi, as Soniox actually transcribes it — the exact call that looped.
    "haan", "han", "haa", "ji", "ji haan", "jee", "theek hai", "thik hai",
    "bilkul", "kar dijiye",
    # Telugu / Tamil / Kannada / Marathi, same failure mode waiting to happen.
    "sare", "avunu", "alage", "aama", "aamaam", "houdu", "ho", "sari",
    # Native script and English must keep working.
    "हाँ", "जी", "ठीक है", "సరే", "అవును", "yes", "okay", "sure",
])
def test_a_spoken_yes_counts_as_a_yes(said):
    assert _caller_affirmed(said) is True, (
        f"{said!r} is how a patient agrees; not recognising it is the loop"
    )


@pytest.mark.parametrize("said", [
    "haan book kar dijiye", "sare book cheyyandi", "yes please book it",
])
def test_agreement_with_the_action_attached_also_counts(said):
    assert _caller_affirmed(said) is True


# ── 2. "now" is not "no" ─────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "yes book it now", "yes, book it now", "ok book it now", "yes now",
])
def test_now_is_not_a_refusal(said):
    """The substring test vetoed every one of these as a negation."""
    assert _caller_declined(said) is False
    assert _caller_affirmed(said) is True


def test_hindi_matlab_is_not_the_negation_mat():
    """मत (don't) is a substring of मतलब (meaning)."""
    assert _caller_declined("matlab kya hai") is False
    assert _caller_declined("मतलब क्या है") is False


# ── 3. a refusal still fails closed ──────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "no", "no thanks", "don't book it", "not now", "nahi", "nahin",
    "नहीं", "వద్దు", "లేదు", "vaddu", "wait", "cancel that",
    "yes but no not today",
])
def test_a_refusal_is_never_agreement(said):
    assert _caller_declined(said) is True
    assert _caller_affirmed(said) is False


def test_empty_is_neither():
    assert _caller_declined("") is False
    assert _caller_affirmed("") is False


# ── 4. the guards judge the answer the language-independent way ──────────────

def _src(name):
    return inspect.getsource(getattr(VachanamAgent, name))


@pytest.mark.parametrize("tool", ["confirm_booking", "reschedule_booking"])
def test_the_guard_accepts_anything_that_is_not_a_refusal(tool):
    """After the guard has demanded the question, requiring a listed phrase is
    what produced both loops. It must gate on refusal, not on recognition."""
    src = _src(tool)
    assert "not declined" in src, (
        f"{tool} still requires the answer to match a phrase list; a caller "
        f"answering in an unlisted language or script can never authorize it"
    )
    assert "_caller_refused_outright" in src, (
        f"{tool} vetoes on a 'contains a negation' test; that is the same "
        f"brittleness in the other direction"
    )


@pytest.mark.parametrize("tool", ["confirm_booking", "reschedule_booking"])
def test_a_refusal_disarms_the_pending_question(tool):
    """Otherwise the flag armed for a question the caller answered "no" to is
    still standing later in the call, and authorizes a mutation nobody agreed
    to — the exact leak the 08-03 disarm-on-success was added to prevent."""
    src = _src(tool)
    assert "if declined:" in src
    assert "pending_confirmation = None" in src


# ── 5. the veto is a flat no, and nothing else ───────────────────────────────

@pytest.mark.parametrize("said", [
    "no", "nope", "no thanks", "nahi", "nahin", "vaddu", "ledu",
    "नहीं", "వద్దు", "இல்லை", "wait", "leave it",
])
def test_a_flat_no_still_blocks_the_write(said):
    assert _caller_refused_outright(said) is True


@pytest.mark.parametrize("said", [
    # Every one of these contains a refusal word and MEANS yes. A "contains a
    # negation" test vetoes all of them and the caller loops.
    "no problem, go ahead",
    "no worries book it",
    "yes book it now",
    "haan koi dikkat nahi hai",
    "nahi nahi, book kar dijiye",
    # And these are genuinely ambiguous — the model reads them, not a list.
    "no, make it eleven instead",
    "not ten, eleven",
])
def test_anything_longer_than_a_flat_no_is_the_models_call(said):
    assert _caller_refused_outright(said) is False


def test_the_veto_is_exact_not_substring():
    """The precise defect: "now" contains "no"."""
    assert _caller_refused_outright("now") is False
    assert _caller_refused_outright("nothing else") is False
    assert _caller_refused_outright("no") is True


def test_cancellation_still_demands_a_positive_yes():
    """Deliberate asymmetry: cancelling is destructive, so silence or an
    ambiguous reply must not do it. This one keeps requiring an affirmation."""
    src = _src("cancel_booking")
    assert "_caller_affirmed" in src
