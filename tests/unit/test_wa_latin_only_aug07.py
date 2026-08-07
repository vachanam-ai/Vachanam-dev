"""WhatsApp replies go out in English letters, always.

Vinay 2026-08-07: "for keeping it professional. lets keep every reply in
English. if user/patient explicitly asked/mentioned telugu. then, we can use
Tenglish", and on what actually bothered him: "issue with Telugu is if user
speaks in Tenglish, AI may reply in telugu. which users may find
unprofessional."

So the rule is about SCRIPT, not language: Telugu script never goes out. The
language still follows the patient (English by default, Tenglish when they
write or ask for Telugu) — a patient who can only write Telugu script still
gets a reply they can read, just in Latin letters.

The prompt asks the model for this. `wa_service.send_text` guarantees it: every
free-text reply in the product is sent through that one function, so the check
lives there rather than at each of its fourteen call sites.
"""
import pytest

from agent.i18n import transliterate
from backend.services import wa_agent, wa_service


# ── the guarantee ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_indic_script_is_romanised_before_sending(monkeypatch):
    sent = {}

    async def fake_send(branch, plan, to, payload, kind, sub):
        sent["body"] = payload["text"]["body"]
        return True

    async def fake_hop(text, src, tgt):
        assert src == "te-IN" and tgt == "en-IN"
        return "Mee appointment confirm ayindi"

    monkeypatch.setattr(wa_service, "_send", fake_send)
    monkeypatch.setattr(transliterate, "_sarvam_hop", fake_hop)
    transliterate._cache.clear()

    await wa_service.send_text(object(), "+919000000000", "మీ అపాయింట్‌మెంట్ కన్ఫర్మ్ అయింది")

    assert sent["body"] == "Mee appointment confirm ayindi"
    assert not any("ఀ" <= ch <= "౿" for ch in sent["body"])


@pytest.mark.asyncio
async def test_latin_text_is_sent_untouched_and_costs_no_network_hop(monkeypatch):
    """The overwhelmingly common case must not pay for an HTTP round trip."""
    sent = {}

    async def fake_send(branch, plan, to, payload, kind, sub):
        sent["body"] = payload["text"]["body"]
        return True

    async def explode(*a, **k):
        raise AssertionError("Latin text must never be sent to Sarvam")

    monkeypatch.setattr(wa_service, "_send", fake_send)
    monkeypatch.setattr(transliterate, "_sarvam_hop", explode)

    await wa_service.send_text(object(), "+919000000000", "Sare, repu 10 gantalaki book chesanu")

    assert sent["body"] == "Sare, repu 10 gantalaki book chesanu"


@pytest.mark.asyncio
async def test_a_dead_transliterator_never_swallows_the_reply(monkeypatch):
    """RULE 8. A reply in the wrong script still beats no reply at all."""
    sent = {}

    async def fake_send(branch, plan, to, payload, kind, sub):
        sent["body"] = payload["text"]["body"]
        return True

    async def fail(*a, **k):
        return None

    monkeypatch.setattr(wa_service, "_send", fake_send)
    monkeypatch.setattr(transliterate, "_sarvam_hop", fail)
    transliterate._cache.clear()

    await wa_service.send_text(object(), "+919000000000", "మీ అపాయింట్‌మెంట్")

    assert sent["body"] == "మీ అపాయింట్‌మెంట్"


@pytest.mark.asyncio
async def test_every_free_text_reply_goes_through_the_guarded_sender():
    """If a new call site sends Meta a text payload directly, the guarantee
    quietly stops being one."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "backend"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in ("wa_service.py",):
            continue
        body = path.read_text(encoding="utf-8")
        if re.search(r'"type"\s*:\s*"text"', body):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"these build a text payload outside send_text: {offenders}"


# ── the instruction ──────────────────────────────────────────────────────────

def test_the_prompt_forbids_indic_script():
    p = wa_agent.SYSTEM_PROMPT
    assert "ALWAYS WRITE IN ENGLISH LETTERS" in p
    assert "Never send Telugu, Devanagari" in p


def test_the_prompt_defaults_to_english_but_keeps_tenglish():
    p = wa_agent.SYSTEM_PROMPT
    assert "English unless they gave you a reason" in p
    assert "Telugu written in English letters" in p


def test_the_prompt_no_longer_asks_the_model_to_mirror_the_script():
    """The old rule said to match "its language and its script, exactly as they
    used it" — which is what put Telugu script on the wire."""
    assert "its script, exactly as they used" not in wa_agent.SYSTEM_PROMPT
