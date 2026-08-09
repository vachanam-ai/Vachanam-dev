"""One composer, or the cache never hits.

Vinay's 2026-08-09 benchmark call, read out of Redis `lat:turns` (16 turns):

    turns=15  min=1570  p50=2018  p95=2888  max=3970 ms
    cache_hit=False on EVERY SINGLE TURN

Language was `te` — the branch's DEFAULT, which the warmer definitely warmed
that boot (`prompt_cache_warm_complete clinics=2 requested=4 ready=4`). So the
entries were built and never hit. Every turn in production ran uncached.

The cache key is a sha256 of the instructions, and the live call and the warmer
were SEPARATE call sites that had to produce that string byte for byte by
discipline. They drifted twice:

  #491 (fixed 08-08)  the date table moved into the instructions and only the
                      live site was updated
  this one           the INPUTS diverged — the warmer stripped `name_spoken`
                      and decoded the FAQ, the live path could pass an
                      unstripped name, a freshly transliterated one, or the raw
                      ORM value

Uncached is also the degraded state behind the wrong dates (#491) and the
newsreader Telugu (#511), so this is a quality bug wearing a latency bug's
clothes.

Fixed by construction: ONE function both sides call, with normalisation inside
it. Not "remember to keep them in sync" — that instruction has now failed twice.
"""
import ast
import hashlib
import inspect
import pathlib
from datetime import date

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import compose_clinic_instructions

SRC = pathlib.Path(agent_mod.__file__).read_text(encoding="utf-8")


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


BASE = dict(
    clinic_name="Datta Clinic", doctors=[], emergency_contact="999",
    plan="clinic", language="te", clinic_address="Hyd", faq=None,
    recording_active=False, today=date(2026, 8, 9),
)


# ── the normalisation that makes the two sides converge ──────────────────────

def test_the_two_input_styles_produce_one_digest():
    """The live path's unstripped name / None plan against the warmer's
    stripped name / explicit plan — the real historical difference."""
    live = compose_clinic_instructions(
        **{**BASE, "clinic_name": "  Datta Clinic ", "emergency_contact": " 999 ",
           "plan": None, "doctors": None}
    )
    warm = compose_clinic_instructions(**BASE)
    assert _digest(live) == _digest(warm)


def test_a_missing_plan_is_not_a_different_clinic():
    a = compose_clinic_instructions(**{**BASE, "plan": None})
    b = compose_clinic_instructions(**{**BASE, "plan": "clinic"})
    assert _digest(a) == _digest(b)


def test_none_doctors_and_empty_doctors_agree():
    a = compose_clinic_instructions(**{**BASE, "doctors": None})
    b = compose_clinic_instructions(**{**BASE, "doctors": []})
    assert _digest(a) == _digest(b)


def test_a_truthy_recording_flag_is_normalised():
    a = compose_clinic_instructions(**{**BASE, "recording_active": 0})
    b = compose_clinic_instructions(**{**BASE, "recording_active": False})
    assert _digest(a) == _digest(b)


# ── things that SHOULD change the digest ─────────────────────────────────────

def test_a_different_clinic_is_a_different_cache():
    a = compose_clinic_instructions(**BASE)
    b = compose_clinic_instructions(**{**BASE, "clinic_name": "Other Clinic"})
    assert _digest(a) != _digest(b), "two clinics must never share a cache (RULE 1)"


def test_a_different_day_is_a_different_cache():
    """The date table is inside the instructions; a stale 'today' served all
    the next day is exactly what #491 was about."""
    a = compose_clinic_instructions(**BASE)
    b = compose_clinic_instructions(**{**BASE, "today": date(2026, 8, 10)})
    assert _digest(a) != _digest(b)


def test_recording_active_does_not_currently_reach_the_prompt():
    """PINS A SEPARATE BUG, found by this file's own failure.

    The warmer warms both recording variants on the assumption they differ.
    They do not: `{recording}` appears in the template (grounded_prompt.py:967)
    and `recording_active` is computed into it (line 793), yet the rendered
    output is byte-identical either way — so the model is never told whether a
    recording notice was spoken, and half the warmer's Vertex cache creations
    are wasted.

    Asserted as-is rather than "fixed" in passing: it is not the cache-miss
    cause (identical strings cannot cause a miss) and changing prompt content
    needs its own real-call validation. If this test starts failing, the
    recording state has begun reaching the prompt — which is probably correct,
    and at that point the warmer's two variants become meaningful."""
    a = compose_clinic_instructions(**{**BASE, "recording_active": False})
    b = compose_clinic_instructions(**{**BASE, "recording_active": True})
    assert _digest(a) == _digest(b)


# ── and there must be exactly ONE of them ────────────────────────────────────

def test_only_the_shared_composer_builds_clinic_instructions():
    """The whole fix. A second call site is how this broke twice; a third would
    break it again silently."""
    tree = ast.parse(SRC)
    callers = []
    stack = []

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            stack.append(n.name); self.generic_visit(n); stack.pop()
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, n):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "build_grounded_prompt":
                callers.append(">".join(stack))
            self.generic_visit(n)

    V().visit(tree)
    assert callers == ["compose_clinic_instructions"], (
        f"build_grounded_prompt is called from {callers} — every clinic prompt "
        f"must go through compose_clinic_instructions or the cache key drifts "
        f"again"
    )


def test_the_composer_carries_the_date_table_and_brevity():
    src = inspect.getsource(compose_clinic_instructions)
    assert "build_date_table" in src
    assert "brevity" in src


def test_both_sides_log_an_input_fingerprint():
    """So the next cache miss names the field that differs, instead of costing
    another live call to guess."""
    assert 'prompt_inputs live' in SRC
    assert 'prompt_inputs warm' in SRC


def test_the_fingerprint_leaks_no_clinic_text():
    """RULE 9 — lengths, counts and a hash, never the clinic's own words."""
    fp = agent_mod._prompt_inputs_fingerprint(
        "Datta Clinic", [], {"q": "are you open on sunday"}, "clinic", False,
    )
    assert "Datta" not in fp
    assert "sunday" not in fp
    assert fp.startswith("name12:doc0:")
