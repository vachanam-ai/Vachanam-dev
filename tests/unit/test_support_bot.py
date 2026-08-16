"""Bot grounds on the KB and flags answered/unanswered; LLM failure is safe."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_bot_grounds_and_flags_answered(monkeypatch):
    from backend.services import support_bot

    async def fake_llm(prompt, **_):
        # the KB must actually be in the grounding prompt
        assert "Pricing" in prompt or "plan" in prompt.lower()
        return '{"answer": "Starter is 5,999 rupees a month.", "answered": true}'

    monkeypatch.setattr(support_bot, "_call_gemini", fake_llm)
    out = await support_bot.answer("what does starter cost?", [], "public")
    assert out["answered"] is True
    assert "5,999" in out["answer"]


async def test_bot_llm_failure_is_safe_refusal(monkeypatch):
    from backend.services import support_bot

    async def boom(prompt, **_):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(support_bot, "_call_gemini", boom)
    out = await support_bot.answer("anything", [], "public")
    # RULE 8: never raise; refusal → answered False (becomes an open ticket)
    assert out["answered"] is False
    assert "hello@vachanam.in" in out["answer"] or "team" in out["answer"].lower()


@pytest.mark.parametrize(
    ("question", "grounding_fact"),
    [
        ("How can I add my own voice?", "first 10 clinics"),
        ("Will voice usage auto debit?", "paid manually"),
        ("Is WhatsApp available now?", "planned but not live yet"),
    ],
)
async def test_bot_receives_every_current_product_update(
    monkeypatch, question, grounding_fact
):
    from backend.services import support_bot

    async def grounded(prompt, **_):
        assert grounding_fact in prompt
        return '{"answer": "This is covered by the current product policy.", "answered": true}'

    monkeypatch.setattr(support_bot, "_call_gemini", grounded)
    result = await support_bot.answer(question, [], "clinic")
    assert result == {
        "answer": "This is covered by the current product policy.",
        "answered": True,
    }
