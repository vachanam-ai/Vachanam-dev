"""Smoke-test: verify all required Pipecat 1.x classes import cleanly.

Corrections from plan Task 3 Step 1 (verified against pipecat-ai 1.3.0 +
pipecat-vobiz 0.0.3 install):

1. Transport path: plan listed `pipecat.transports.websocket.fastapi` — CORRECT,
   the path exists in 1.3.0 and exports FastAPIWebsocketTransport +
   FastAPIWebsocketParams.

2. Sarvam STT: plan listed `pipecat.services.sarvam.stt.SarvamSTTService`
   — CORRECT, class lives in that submodule.

3. Sarvam TTS: plan listed `pipecat.services.sarvam` (top-level __init__)
   — WRONG: `services.sarvam.__init__` is empty. Correct path:
   `pipecat.services.sarvam.tts.SarvamTTSService`.

4. Google LLM: plan listed `pipecat.services.google.GoogleLLMService`
   — WRONG: `services.google.__init__` is empty. Correct path:
   `pipecat.services.google.llm.GoogleLLMService`.

5. OpenAI LLM: plan listed `pipecat.services.openai.OpenAILLMService`
   — WRONG: `services.openai.__init__` is empty. Correct path:
   `pipecat.services.openai.llm.OpenAILLMService`.

6. Vobiz helper: plan listed `pipecat_vobiz.parse_vobiz_start` and plan
   named the PyPI package `pipecat-ai-vobiz` — BOTH WRONG.
   Actual PyPI name is `pipecat-vobiz` (0.0.3). It installs as a namespace
   extension of pipecat (no standalone `pipecat_vobiz` top-level module).
   Correct import: `pipecat.serializers.vobiz.parse_vobiz_start`.
"""


def test_pipecat_transport_imports():
    from pipecat.transports.websocket.fastapi import (  # noqa: F401
        FastAPIWebsocketTransport,
        FastAPIWebsocketParams,
    )


def test_pipecat_pipeline_imports():
    from pipecat.pipeline.pipeline import Pipeline  # noqa: F401
    from pipecat.pipeline.task import PipelineTask, PipelineParams  # noqa: F401
    from pipecat.pipeline.runner import PipelineRunner  # noqa: F401


def test_pipecat_sarvam_imports():
    # SarvamSTTService lives in pipecat.services.sarvam.stt (plan path correct)
    from pipecat.services.sarvam.stt import SarvamSTTService  # noqa: F401
    # SarvamTTSService: plan said pipecat.services.sarvam (top-level) — corrected
    # to pipecat.services.sarvam.tts (services.sarvam.__init__ is empty in 1.3.0)
    from pipecat.services.sarvam.tts import SarvamTTSService  # noqa: F401


def test_pipecat_google_imports():
    # GoogleLLMService: plan said pipecat.services.google (top-level) — corrected
    # to pipecat.services.google.llm (services.google.__init__ is empty in 1.3.0)
    from pipecat.services.google.llm import GoogleLLMService  # noqa: F401


def test_pipecat_openai_imports():
    # OpenAILLMService: plan said pipecat.services.openai (top-level) — corrected
    # to pipecat.services.openai.llm (services.openai.__init__ is empty in 1.3.0)
    from pipecat.services.openai.llm import OpenAILLMService  # noqa: F401


def test_pipecat_vad_imports():
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401


def test_vobiz_helper_imports():
    # Plan: from pipecat_vobiz import parse_vobiz_start
    # Correction: PyPI package is pipecat-vobiz (not pipecat-ai-vobiz).
    # It installs as pipecat.serializers.vobiz (namespace extension) — no
    # standalone pipecat_vobiz top-level module exists.
    from pipecat.serializers.vobiz import parse_vobiz_start  # noqa: F401
