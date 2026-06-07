"""TDD tests for Task 7: LLM fallback wrapper + 5-tool registration.

Tests are written FIRST (TDD red phase). They cover:
1. build_function_schemas() returns schemas for all 5 expected tools.
2. build_llm_with_fallback() wraps Gemini (primary) with GPT-4o-mini (secondary).
3. make_request_human_transfer_handler() sets transfer signal + releases held token.
4. make_request_human_transfer_handler() does NOT release a confirmed token.

No real LLM/Sarvam/network calls are made. All services and external calls mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.session_state import SessionState


# ─── Test 1: All 5 function schemas present ──────────────────────────────────


def test_function_schemas_for_all_five_tools():
    """build_function_schemas() must return schemas for all 5 LLM tools."""
    from agent.bot import build_function_schemas

    schemas = build_function_schemas()
    names = {s.name for s in schemas}
    assert names == {
        "route_to_doctor",
        "check_availability",
        "assign_token",
        "confirm_booking",
        "request_human_transfer",
    }, f"Got tool names: {names}"


def test_function_schemas_have_required_fields():
    """Each schema must have non-empty name, description, properties, required."""
    from agent.bot import build_function_schemas

    schemas = build_function_schemas()
    for schema in schemas:
        assert schema.name, f"Schema missing name: {schema}"
        assert schema.description, f"Schema '{schema.name}' missing description"
        assert isinstance(schema.properties, dict), f"Schema '{schema.name}' properties must be dict"
        assert isinstance(schema.required, list), f"Schema '{schema.name}' required must be list"


def test_route_to_doctor_schema_requires_complaint():
    """route_to_doctor schema must require 'complaint' field."""
    from agent.bot import build_function_schemas

    schemas = {s.name: s for s in build_function_schemas()}
    s = schemas["route_to_doctor"]
    assert "complaint" in s.required
    assert "complaint" in s.properties


def test_request_human_transfer_schema_requires_reason():
    """request_human_transfer schema must require 'reason' field."""
    from agent.bot import build_function_schemas

    schemas = {s.name: s for s in build_function_schemas()}
    s = schemas["request_human_transfer"]
    assert "reason" in s.required
    assert "reason" in s.properties


def test_confirm_booking_schema_required_fields():
    """confirm_booking schema must require doctor_id, patient_name, complaint,
    booking_date, token_number, followup_consent."""
    from agent.bot import build_function_schemas

    schemas = {s.name: s for s in build_function_schemas()}
    s = schemas["confirm_booking"]
    required_set = set(s.required)
    expected = {"doctor_id", "patient_name", "complaint", "booking_date", "token_number", "followup_consent"}
    assert expected.issubset(required_set), (
        f"Missing required fields: {expected - required_set}"
    )


# ─── Test 2: Fallback wraps Gemini with OpenAI secondary ─────────────────────


def test_fallback_wraps_gemini_with_openai_secondary():
    """build_llm_with_fallback must return an object that is not None and
    exposes a register_function method."""
    from agent.bot import build_llm_with_fallback

    llm = build_llm_with_fallback(gemini_key="g-key", openai_key="o-key")
    assert llm is not None
    assert callable(getattr(llm, "register_function", None)), (
        "Returned object must expose register_function"
    )


def test_fallback_is_google_llm_service_subclass():
    """build_llm_with_fallback must return a GoogleLLMService instance (or subclass)
    so the pipeline builder can use it as an LLMService without modification.
    The existing test_build_llm_with_fallback_returns_google_service in
    test_bot_pipeline_builder.py asserts isinstance(llm, GoogleLLMService).
    This test is the Task 7 companion verifying the fallback is wired inside."""
    from agent.bot import build_llm_with_fallback
    from pipecat.services.google.llm import GoogleLLMService

    llm = build_llm_with_fallback(gemini_key="g-key", openai_key="o-key")
    assert isinstance(llm, GoogleLLMService), (
        f"Expected GoogleLLMService (or subclass), got {type(llm).__name__}"
    )


def test_fallback_exposes_fallback_service():
    """build_llm_with_fallback result must expose its OpenAI fallback service
    as _fallback_service attribute (GeminiFallbackLLMService stores it there)."""
    from agent.bot import build_llm_with_fallback
    from pipecat.services.openai.llm import OpenAILLMService

    llm = build_llm_with_fallback(gemini_key="g-key", openai_key="o-key")
    assert hasattr(llm, "_fallback_service"), (
        "Fallback wrapper must expose _fallback_service attribute"
    )
    assert isinstance(llm._fallback_service, OpenAILLMService), (
        f"_fallback_service must be OpenAILLMService, got {type(llm._fallback_service).__name__}"
    )


# ─── Test 3: request_human_transfer handler — signal + token release ─────────


@pytest.mark.asyncio
async def test_request_human_transfer_handler_sets_signal_and_releases_token():
    """Handler must: set signal_map[session_id]=True, call redis.decr on held
    unconfirmed token, write audit row with masked emergency contact, call result_callback."""
    from agent.bot import make_request_human_transfer_handler

    redis = AsyncMock()
    signal_map: dict[str, bool] = {}
    state = SessionState(
        token_held=True,
        token_confirmed=False,
        token_redis_key="token:d:b:2026-06-07",
        token_number=5,
        session_id="CALL_ABC",
    )
    audit_writer = AsyncMock()
    tts_say = AsyncMock()

    handler = make_request_human_transfer_handler(
        session_state=state,
        redis_client=redis,
        signal_map=signal_map,
        audit_writer=audit_writer,
        branch_emergency_contact="+919876543210",
        tts_say=tts_say,
    )

    params = MagicMock()
    params.arguments = {"reason": "explicit_ask"}
    params.result_callback = AsyncMock()

    await handler(params)

    # Signal must be set for this session
    assert signal_map.get("CALL_ABC") is True, (
        f"signal_map['CALL_ABC'] should be True, got {signal_map.get('CALL_ABC')}"
    )

    # Held unconfirmed token must be released via DECR
    redis.decr.assert_awaited_once_with("token:d:b:2026-06-07")

    # Audit row written with PII-masked emergency contact (last 4 only)
    audit_writer.assert_awaited_once()
    audit_kwargs = audit_writer.await_args.kwargs
    assert audit_kwargs["action"] == "human_transfer_requested", (
        f"Expected action='human_transfer_requested', got {audit_kwargs.get('action')!r}"
    )
    metadata = audit_kwargs["metadata"]
    assert metadata["branch_emergency_contact_last4"] == "3210", (
        f"Must log only last 4 of emergency contact, got {metadata.get('branch_emergency_contact_last4')!r}"
    )
    assert metadata["reason"] == "explicit_ask"
    # Full phone must NOT appear in metadata
    full_phone = "+919876543210"
    assert full_phone not in str(metadata), (
        "Full emergency contact phone MUST NOT appear in audit metadata (PII denylist)"
    )

    # result_callback must be called to signal completion to the LLM
    params.result_callback.assert_awaited_once()

    # TTS greeting must be called
    tts_say.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_human_transfer_handler_tts_uses_sanitized_text():
    """TTS say call must pass a string (sanitize_for_tts enforced at handler level)."""
    from agent.bot import make_request_human_transfer_handler

    redis = AsyncMock()
    signal_map: dict[str, bool] = {}
    state = SessionState(
        session_id="CALL_TTSCheck",
        token_held=False,
        token_confirmed=False,
    )
    tts_calls: list[str] = []

    async def capture_tts(text: str) -> None:
        tts_calls.append(text)

    handler = make_request_human_transfer_handler(
        session_state=state,
        redis_client=redis,
        signal_map=signal_map,
        audit_writer=AsyncMock(),
        branch_emergency_contact="+919000000001",
        tts_say=capture_tts,
    )

    params = MagicMock()
    params.arguments = {"reason": "explicit_ask"}
    params.result_callback = AsyncMock()

    await handler(params)

    assert len(tts_calls) == 1, f"Expected 1 TTS call, got {len(tts_calls)}"
    spoken = tts_calls[0]
    # Must not contain markdown patterns that break TTS
    assert "**" not in spoken, "TTS text must not contain ** (bold markdown)"
    assert spoken.startswith("Sare") or len(spoken) > 0, "TTS text must be non-empty"


# ─── Test 4: Confirmed token NOT released on human transfer ──────────────────


@pytest.mark.asyncio
async def test_request_human_transfer_handler_does_not_decr_confirmed_token():
    """Handler must NOT call redis.decr when token_confirmed=True.
    Confirmed tokens are never released (CLAUDE.md RULE 3: DECR is rollback only)."""
    from agent.bot import make_request_human_transfer_handler

    redis = AsyncMock()
    state = SessionState(
        token_held=True,
        token_confirmed=True,
        token_redis_key="k",
        token_number=5,
        session_id="CALL_XYZ",
    )

    handler = make_request_human_transfer_handler(
        session_state=state,
        redis_client=redis,
        signal_map={},
        audit_writer=AsyncMock(),
        branch_emergency_contact="+919000000000",
        tts_say=AsyncMock(),
    )

    params = MagicMock()
    params.arguments = {"reason": "explicit_ask"}
    params.result_callback = AsyncMock()

    await handler(params)

    redis.decr.assert_not_called()


@pytest.mark.asyncio
async def test_request_human_transfer_handler_no_token_no_decr():
    """Handler must not call redis.decr when no token is held."""
    from agent.bot import make_request_human_transfer_handler

    redis = AsyncMock()
    state = SessionState(
        token_held=False,
        token_confirmed=False,
        token_redis_key=None,
        session_id="CALL_NOTOKEN",
    )

    handler = make_request_human_transfer_handler(
        session_state=state,
        redis_client=redis,
        signal_map={},
        audit_writer=AsyncMock(),
        branch_emergency_contact="+919000000000",
        tts_say=AsyncMock(),
    )

    params = MagicMock()
    params.arguments = {"reason": "persistent_pressure: wants doctor only"}
    params.result_callback = AsyncMock()

    await handler(params)

    redis.decr.assert_not_called()


@pytest.mark.asyncio
async def test_request_human_transfer_audit_failure_does_not_block():
    """If audit_writer raises, the handler must still complete (signal set, result_callback called)."""
    from agent.bot import make_request_human_transfer_handler

    redis = AsyncMock()
    signal_map: dict[str, bool] = {}
    state = SessionState(
        session_id="CALL_AUDITFAIL",
        token_held=False,
        token_confirmed=False,
    )

    async def failing_audit(**kwargs: object) -> None:
        raise RuntimeError("DB down")

    handler = make_request_human_transfer_handler(
        session_state=state,
        redis_client=redis,
        signal_map=signal_map,
        audit_writer=failing_audit,
        branch_emergency_contact="+919000000000",
        tts_say=AsyncMock(),
    )

    params = MagicMock()
    params.arguments = {"reason": "explicit_ask"}
    params.result_callback = AsyncMock()

    # Must not raise even though audit fails
    await handler(params)

    # Signal must still be set
    assert signal_map.get("CALL_AUDITFAIL") is True

    # result_callback still called
    params.result_callback.assert_awaited_once()
