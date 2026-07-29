import asyncio

import pytest
from pydantic import ValidationError

from agent.livekit_minimal.agent import (
    _SonioxFinalizeController,
    _prime_soniox_tts_audio,
)
from backend.config import Settings


class _FakeStream:
    def __init__(self) -> None:
        self.audio_queue = asyncio.Queue()


class _PrimeStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        return object()

    async def aclose(self) -> None:
        self.closed = True


class _PrimeTTS:
    def __init__(self) -> None:
        self.stream = _PrimeStream()
        self.text = None

    def synthesize(self, text):
        self.text = text
        return self.stream


@pytest.mark.asyncio
async def test_audio_prime_consumes_one_frame_and_closes_without_playout():
    tts = _PrimeTTS()

    assert await _prime_soniox_tts_audio(tts, "సరే అండి.") is True
    assert tts.text == "సరే అండి."
    assert tts.stream.closed is True


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


def test_config_defaults_to_single_owner_low_latency_endpointing():
    settings = Settings()
    assert settings.soniox_endpoint_latency_level == 2
    assert settings.soniox_max_endpoint_delay_ms == 1500
    assert settings.soniox_endpoint_sensitivity == 0.3
    assert settings.soniox_manual_finalize_delay_ms == 0
