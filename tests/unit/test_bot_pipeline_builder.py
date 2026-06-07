"""Unit tests for agent/bot.py pipeline builder functions.

TDD Step 1: Write tests first, verify they FAIL before implementing bot.py.

Import-path corrections vs the original plan (verified against pipecat-ai 1.3.0
in commit 825a60b, and confirmed again here):

- PipelineTask is deprecated in 1.3.0 -> PipelineWorker (pipeline.task module)
- PipelineRunner is deprecated in 1.3.0 -> WorkerRunner (pipeline.runner module)
- Aggregators: LLMUserAggregator, LLMAssistantAggregator, LLMUserAggregatorParams,
  LLMContextAggregatorPair all live in
  pipecat.processors.aggregators.llm_response_universal
  (NOT llm_response, which only has LLMFullResponseAggregator)
- VobizFrameSerializer requires stream_id as first positional arg
- No allow_interruptions param on PipelineWorker - barge-in controlled by VAD

These tests do NOT hit Sarvam/Gemini/OpenAI APIs. Service constructors are
called with fake API keys and assertions use attribute introspection only.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_build_pipeline_resolves_branch_from_did(monkeypatch):
    """resolve_branch_or_raise must raise ValueError('unknown DID: ...') for unknown DID."""
    from agent.bot import resolve_branch_or_raise

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = None

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=fake_result)

    with pytest.raises(ValueError, match="unknown DID"):
        await resolve_branch_or_raise(fake_db, did="+910000000000")


@pytest.mark.asyncio
async def test_resolve_branch_returns_branch_for_known_did():
    """resolve_branch_or_raise must return the Branch row when found."""
    from agent.bot import resolve_branch_or_raise

    fake_branch = MagicMock()
    fake_branch.id = "branch-uuid-1234"
    fake_branch.name = "Test Clinic"

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_branch

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=fake_result)

    branch = await resolve_branch_or_raise(fake_db, did="+914066123456")
    assert branch is fake_branch


def test_build_stt_service_uses_telugu_locale():
    """build_stt_service must produce SarvamSTTService configured with saaras:v3 + te-IN."""
    from agent.bot import build_stt_service

    stt = build_stt_service(api_key="test-key-stt")
    # _settings is a SarvamSTTSettings dataclass exposed by pipecat 1.3.0
    settings_obj = stt._settings
    assert settings_obj.model == "saaras:v3", (
        f"Expected model='saaras:v3' but got {settings_obj.model!r}"
    )
    assert str(settings_obj.language) == "te-IN", (
        f"Expected language='te-IN' but got {settings_obj.language!r}"
    )


def test_build_stt_service_keepalive_interval_set():
    """build_stt_service must set keepalive_interval=5.0 (Pipecat issue #3699 mitigation)."""
    from agent.bot import build_stt_service

    stt = build_stt_service(api_key="test-key-stt")
    assert stt._keepalive_interval == 5.0, (
        f"Expected _keepalive_interval=5.0 but got {stt._keepalive_interval!r}"
    )


def test_build_tts_service_uses_bulbul_telugu():
    """build_tts_service must produce SarvamTTSService with bulbul:v3 + te-IN voice."""
    from agent.bot import build_tts_service

    tts = build_tts_service(api_key="test-key-tts")
    settings_obj = tts._settings
    assert settings_obj.model == "bulbul:v3", (
        f"Expected model='bulbul:v3' but got {settings_obj.model!r}"
    )
    assert str(settings_obj.language) == "te-IN", (
        f"Expected language='te-IN' but got {settings_obj.language!r}"
    )


def test_build_llm_with_fallback_returns_google_service():
    """build_llm_with_fallback (stub for Task 7) must return a GoogleLLMService for now."""
    from agent.bot import build_llm_with_fallback
    from pipecat.services.google.llm import GoogleLLMService

    llm = build_llm_with_fallback(gemini_key="fake-gemini-key", openai_key="fake-openai-key")
    assert isinstance(llm, GoogleLLMService), (
        f"Expected GoogleLLMService but got {type(llm).__name__}"
    )


def test_build_transport_requires_no_wav_header(monkeypatch):
    """build_transport must always set add_wav_header=False (telephony requirement)."""
    from agent.bot import build_transport
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

    fake_ws = MagicMock()
    transport = build_transport(
        websocket=fake_ws,
        public_url="https://agent-dev.vachanam.in",
        stream_id="test-stream-001",
        call_id="CALL_TEST",
    )
    assert isinstance(transport, FastAPIWebsocketTransport)
    # add_wav_header must be False — verify via params
    assert transport._params.add_wav_header is False, (
        f"add_wav_header must be False for telephony but got {transport._params.add_wav_header!r}"
    )


def test_register_tools_is_callable_stub():
    """register_tools stub must be callable (Task 7 fills it)."""
    from agent.bot import register_tools
    import inspect
    assert callable(register_tools), "register_tools must be a callable"


def test_release_token_on_disconnect_stub_is_coroutine():
    """release_token_on_disconnect must be an async function (Task 9 fills real logic)."""
    from agent.bot import release_token_on_disconnect
    import inspect
    assert inspect.iscoroutinefunction(release_token_on_disconnect), (
        "release_token_on_disconnect must be async"
    )


def test_run_pipeline_is_coroutine():
    """run_pipeline entrypoint must be async."""
    from agent.bot import run_pipeline
    import inspect
    assert inspect.iscoroutinefunction(run_pipeline), "run_pipeline must be async"
