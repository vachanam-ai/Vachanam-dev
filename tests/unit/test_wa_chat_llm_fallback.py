"""A slow or overloaded Gemini must not become "sorry, I had trouble
understanding that".

Vinay, 2026-08-03: he sent "who all doctors available" and got the
`_GEMINI_DOWN_REPLY`. Render logs at 17:06:26:

    {"dependency": "gemini_wa_chat", "error": "", "attempts": 1,
     "circuit": "half_open", "event": "resilience_call_failed"}

The EMPTY error string is the tell: `str(asyncio.TimeoutError())` is "". The
call was one 12s attempt at gemini-2.5-flash-lite with retries=0 and no
fallback model — and flash-lite returns
`503 UNAVAILABLE ... experiencing high demand` often enough to hit a patient.

CLAUDE.md constraint 8 requires an automatic fallback model. These tests pin
that, plus the logging that hid the reason for a day.
"""
import asyncio

import pytest

from backend.services import wa_chat


@pytest.fixture(autouse=True)
def _fresh_breakers():
    """The circuit breaker is process-global; a previous test's failures would
    otherwise open it and short-circuit these."""
    from backend.services import resilience

    resilience._breakers.clear()
    resilience._metrics.clear()
    yield
    resilience._breakers.clear()
    resilience._metrics.clear()


@pytest.mark.asyncio
async def test_the_fallback_model_answers_when_the_primary_fails(monkeypatch):
    calls: list[str] = []

    async def fake(prompt, model="gemini-2.5-flash-lite"):
        calls.append(model)
        if model == "gemini-2.5-flash-lite":
            raise RuntimeError("503 UNAVAILABLE experiencing high demand")
        return '{"intent": "doctor_info"}'

    monkeypatch.setattr(wa_chat, "_call_gemini", fake)

    assert await wa_chat._classify("p") == '{"intent": "doctor_info"}'
    assert calls == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


@pytest.mark.asyncio
async def test_a_primary_timeout_also_reaches_the_fallback(monkeypatch):
    """The exact production failure: asyncio.TimeoutError, whose str() is ''."""
    async def fake(prompt, model="gemini-2.5-flash-lite"):
        if model == "gemini-2.5-flash-lite":
            raise asyncio.TimeoutError()
        return '{"intent": "book"}'

    monkeypatch.setattr(wa_chat, "_call_gemini", fake)
    assert await wa_chat._classify("p") == '{"intent": "book"}'


@pytest.mark.asyncio
async def test_a_healthy_primary_never_calls_the_fallback(monkeypatch):
    calls: list[str] = []

    async def fake(prompt, model="gemini-2.5-flash-lite"):
        calls.append(model)
        return '{"intent": "faq"}'

    monkeypatch.setattr(wa_chat, "_call_gemini", fake)
    await wa_chat._classify("p")
    assert calls == ["gemini-2.5-flash-lite"]


@pytest.mark.asyncio
async def test_both_models_down_still_raises_so_the_caller_can_apologise(monkeypatch):
    async def fake(prompt, model="gemini-2.5-flash-lite"):
        raise RuntimeError("down")

    monkeypatch.setattr(wa_chat, "_call_gemini", fake)
    with pytest.raises(Exception):
        await wa_chat._classify("p")


@pytest.mark.asyncio
async def test_the_two_models_do_not_share_a_circuit_breaker(monkeypatch):
    """flash-lite being overloaded must not open the breaker on the model
    that is still healthy — otherwise one bad minute takes both down."""
    from backend.services import resilience

    async def fake(prompt, model="gemini-2.5-flash-lite"):
        if model == "gemini-2.5-flash-lite":
            raise RuntimeError("503")
        return "{}"

    monkeypatch.setattr(wa_chat, "_call_gemini", fake)
    for _ in range(resilience.FAIL_THRESHOLD + 2):
        await wa_chat._classify("p")

    assert resilience._breaker("gemini_wa_chat").state() == "open"
    assert resilience._breaker("gemini_wa_chat_fallback").state() == "closed"


def test_the_failure_log_carries_the_exception_type(monkeypatch):
    """`error=""` told us nothing for a day. TimeoutError stringifies to
    empty, so the type has to be in the log line."""
    import inspect

    src = inspect.getsource(wa_chat.handle_text)
    assert 'type(e).__name__' in src


def test_the_json_contract_is_not_double_braced():
    """_JSON_CONTRACT is CONCATENATED onto build_chat_prompt()'s output, never
    passed through str.format() — doubled braces literally instructed the
    model to emit `{{...}}`, which is not JSON."""
    assert "{{" not in wa_chat._JSON_CONTRACT
    assert "}}" not in wa_chat._JSON_CONTRACT
    assert '{"intent"' in wa_chat._JSON_CONTRACT


def test_the_genai_client_is_reused_across_calls():
    """Rebuilding genai.Client per message meant a fresh TLS handshake to
    Google on every WhatsApp turn, which is what pushed p95 into the timeout."""
    from backend.services import support_bot

    support_bot._client = object()
    assert support_bot._genai_client() is support_bot._client
    support_bot._client = None
