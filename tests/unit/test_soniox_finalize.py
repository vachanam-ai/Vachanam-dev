import asyncio

import pytest
from pydantic import ValidationError

from agent.livekit_minimal.agent import _SonioxFinalizeController
from backend.config import Settings


class _FakeStream:
    def __init__(self) -> None:
        self.audio_queue = asyncio.Queue()


@pytest.mark.asyncio
async def test_finalize_waits_for_continuing_silence():
    controller = _SonioxFinalizeController(delay_ms=5)
    stream = _FakeStream()
    controller.register(stream)

    controller.schedule(lambda: True)
    assert stream.audio_queue.empty()
    await asyncio.sleep(0.02)

    assert stream.audio_queue.get_nowait() == '{"type": "finalize"}'


@pytest.mark.asyncio
async def test_resumed_speech_prevents_finalize():
    controller = _SonioxFinalizeController(delay_ms=5)
    stream = _FakeStream()
    controller.register(stream)

    controller.schedule(lambda: False)
    await asyncio.sleep(0.02)

    assert stream.audio_queue.empty()


@pytest.mark.asyncio
async def test_cancelled_timer_never_finalizes():
    controller = _SonioxFinalizeController(delay_ms=5)
    stream = _FakeStream()
    controller.register(stream)

    controller.schedule(lambda: True)
    controller.cancel()
    await asyncio.sleep(0.02)

    assert stream.audio_queue.empty()


@pytest.mark.asyncio
async def test_finalize_controller_isolated_per_call():
    first = _SonioxFinalizeController(delay_ms=5)
    second = _SonioxFinalizeController(delay_ms=5)
    first_stream = _FakeStream()
    second_stream = _FakeStream()
    first.register(first_stream)
    second.register(second_stream)

    first.schedule(lambda: True)
    await asyncio.sleep(0.02)

    assert first_stream.audio_queue.get_nowait() == '{"type": "finalize"}'
    assert second_stream.audio_queue.empty()


@pytest.mark.asyncio
async def test_disabled_controller_never_creates_timer():
    controller = _SonioxFinalizeController(delay_ms=0)
    stream = _FakeStream()
    controller.register(stream)

    controller.schedule(lambda: True)
    await asyncio.sleep(0)

    assert stream.audio_queue.empty()
    assert controller._task is None


@pytest.mark.parametrize("delay_ms", [1, 50, 199, 3001])
def test_config_rejects_unsafe_manual_finalize_delay(delay_ms):
    with pytest.raises(ValidationError):
        Settings(soniox_manual_finalize_delay_ms=delay_ms)


@pytest.mark.parametrize("level", [-1, 4])
def test_config_rejects_invalid_latency_level(level):
    with pytest.raises(ValidationError):
        Settings(soniox_endpoint_latency_level=level)


def test_config_defaults_to_safe_200ms_manual_finalize():
    settings = Settings()
    assert settings.soniox_endpoint_latency_level == 1
    assert settings.soniox_max_endpoint_delay_ms == 2000
    assert settings.soniox_endpoint_sensitivity is None
    assert settings.soniox_manual_finalize_delay_ms == 200
