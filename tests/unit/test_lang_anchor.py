"""Phase 4 (2026-07-30 voice-prompt-redesign) — language anti-drift.

The one-time switch drift guard decays: the carried history is all
old-language turns, so within 1-2 turns recency drags the model back (#466,
Vinay live 2026-07-26). The fix is a per-turn active-language anchor that is
refreshed as the LAST context item every turn (never decays, never stacks),
plus a harder trim of the carried old-language history on switch. Both behind
`voice_lang_anchor` (default OFF).
"""
from __future__ import annotations

import inspect
from uuid import UUID

from agent.i18n.languages import get_lang
from agent.livekit_minimal.agent import (
    VachanamAgent,
    _LANG_ANCHOR_PREFIX,
    _append_switch_drift_guard,
)
from agent.session_state import SessionState

BRANCH_ID = UUID("2e6d5a8a-30f0-4a90-9a9c-000000000004")


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content
        self.text_content = content


class _Ctx:
    """Minimal stand-in for livekit ChatContext (list-backed items)."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def add_message(self, role, content):
        self.items.append(_Msg(role, content))

    def truncate(self, max_items):
        if len(self.items) > max_items:
            self.items[:] = self.items[-max_items:]

    def copy(self):
        return _Ctx([_Msg(m.role, m.content) for m in self.items])


def _agent(lang="en"):
    return VachanamAgent(
        instructions="unused",
        state=SessionState(branch_id=BRANCH_ID, branch_timezone="Asia/Kolkata", language=lang),
        db=object(), room=None, calendar_service=None, meta_service=None,
        transfer_to="", lang_code=lang,
    )


def _anchors(ctx):
    return [m for m in ctx.items if str(m.content).lstrip().startswith(_LANG_ANCHOR_PREFIX)]


# ── 4.2 persistent per-turn anchor ───────────────────────────────────────────


def test_flag_defaults_off():
    from backend.config import settings

    assert settings.voice_lang_anchor is False


def test_anchor_is_last_item_and_names_active_language():
    agent = _agent("en")
    ctx = _Ctx([_Msg("user", "నాకు అపాయింట్‌మెంట్ కావాలి"), _Msg("assistant", "సరే")])
    agent._refresh_lang_anchor(ctx)
    assert ctx.items[-1].content.startswith(_LANG_ANCHOR_PREFIX)
    assert get_lang("en").name in ctx.items[-1].content


def test_anchor_never_stacks_across_turns():
    """Refreshed every turn with an intervening user/assistant exchange — still
    exactly ONE anchor, and it stays last (the switch signal never decays)."""
    agent = _agent("en")
    ctx = _Ctx([_Msg("user", "hi")])
    for i in range(5):
        agent._refresh_lang_anchor(ctx)
        # simulate the next real turn landing after the anchor
        ctx.add_message("assistant", f"reply {i}")
        ctx.add_message("user", f"turn {i}")
    agent._refresh_lang_anchor(ctx)
    assert len(_anchors(ctx)) == 1
    assert ctx.items[-1].content.startswith(_LANG_ANCHOR_PREFIX)
    assert get_lang("en").name in ctx.items[-1].content


def test_per_turn_anchor_is_flag_gated():
    src = inspect.getsource(VachanamAgent.on_user_turn_completed)
    assert "settings.voice_lang_anchor" in src
    assert "_refresh_lang_anchor" in src


# ── 4.3 harder trim + pending-question survival ──────────────────────────────


def test_switch_trims_to_flagged_window_and_keeps_pending_question():
    # The pending question sits 5 non-user items before the end, so a keep-4
    # window would drop it — the safeguard must re-insert it.
    items = [_Msg("user", "PENDING QUESTION")] + [
        _Msg("assistant", f"a{i}") for i in range(5)
    ]
    ctx = _Ctx(items)
    _append_switch_drift_guard(ctx, "en", keep=4)
    texts = [m.content for m in ctx.items]
    assert "PENDING QUESTION" in texts
    # the switch guard's own recency directive names the new language
    assert any(get_lang("en").name in t and "continue in" in t for t in texts)


def test_switch_default_keep_is_eight():
    items = [_Msg("user", f"u{i}") for i in range(12)]
    ctx = _Ctx(items)
    _append_switch_drift_guard(ctx, "en")  # keep=None → default _SWITCH_CTX_KEEP (8)
    # 8 carried + 1 appended directive
    assert len(ctx.items) == 9


# ── 4.4 multi-turn drift regression (the bug) ────────────────────────────────


def test_switch_holds_across_many_turns():
    """Structural proof the anchor names the NEW language on turns 1..5 and
    never reverts — the #466 drift can't recur while the anchor is refreshed."""
    agent = _agent("en")
    ctx = _Ctx([_Msg("user", "please switch to english")])
    for i in range(1, 6):
        agent._refresh_lang_anchor(ctx)
        assert ctx.items[-1].content.startswith(_LANG_ANCHOR_PREFIX)
        assert get_lang("en").name in ctx.items[-1].content
        assert len(_anchors(ctx)) == 1
        ctx.add_message("assistant", f"english reply {i}")
        ctx.add_message("user", f"english turn {i}")
