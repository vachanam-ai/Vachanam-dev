#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import json
import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.serializers.vobiz import VobizFrameSerializer, parse_vobiz_start
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

load_dotenv(override=True)


async def _resilient_parse_vobiz_start(websocket, timeout: float = 5.0) -> dict:
    """Drain leading binary frames until first text (start) message arrives.

    Vobiz outbound trunk has a race condition where it can emit binary audio
    frames before the start text frame. The default parse_vobiz_start uses
    receive_text() which raises WebSocketDisconnect on binary input.

    Reads at most until `timeout` seconds. Returns same dict shape as
    pipecat.serializers.vobiz.parse_vobiz_start.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    dropped_binary_count = 0
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            logger.error(f"resilient_parse_vobiz_start: timeout, dropped {dropped_binary_count} binary frames")
            return {"stream_id": "", "call_id": "", "encoding": None, "sample_rate": None, "raw": {}}
        try:
            msg = await asyncio.wait_for(websocket.receive(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.error("resilient_parse_vobiz_start: receive() timeout")
            return {"stream_id": "", "call_id": "", "encoding": None, "sample_rate": None, "raw": {}}
        if msg.get("type") == "websocket.disconnect":
            logger.error(f"resilient_parse_vobiz_start: WS disconnected before start (code={msg.get('code')})")
            return {"stream_id": "", "call_id": "", "encoding": None, "sample_rate": None, "raw": {}}
        text = msg.get("text")
        if text:
            if dropped_binary_count:
                logger.warning(f"resilient_parse_vobiz_start: drained {dropped_binary_count} binary frames before start text")
            try:
                parsed_msg = json.loads(text)
            except json.JSONDecodeError:
                logger.error(f"resilient_parse_vobiz_start: first text was not JSON: {text!r}")
                return {"stream_id": "", "call_id": "", "encoding": None, "sample_rate": None, "raw": {}}
            start = parsed_msg.get("start") or {}
            media_format = start.get("mediaFormat") or {}
            rate = media_format.get("sampleRate")
            return {
                "stream_id": start.get("streamId") or "",
                "call_id": start.get("callId") or "",
                "encoding": media_format.get("encoding"),
                "sample_rate": int(rate) if isinstance(rate, (int, float, str)) and str(rate).isdigit() else None,
                "raw": parsed_msg,
            }
        if msg.get("bytes"):
            dropped_binary_count += 1


async def run_bot(transport: BaseTransport, handle_sigint: bool):
    # Gemini 2.5 Flash — fast first token, decent multilingual
    # (Sarvam-105b tested 2026-06-09 and proved worse than Gemini for our use case)
    llm = GoogleLLMService(
        api_key=os.getenv("GEMINI_API_KEY"),
        model="gemini-2.5-flash",
    )

    # Sarvam Saaras v3 STT — streaming, ~200ms first transcript, te-IN native
    stt = SarvamSTTService(
        api_key=os.getenv("SARVAM_API_KEY"),
        model="saaras:v3",
        language=Language.TE_IN,
    )

    # Sarvam Bulbul v3 TTS — Telugu female voice kavitha (Telugu-native)
    # Output: linear16 PCM (Pipecat default). VobizFrameSerializer resamples to 8kHz mulaw.
    # pace=1.3 = 30% faster delivery (default 1.0 sounds robotic-slow on phone)
    # IMPORTANT: feed Telugu script (telugu unicode) to TTS, NOT romanized — romanized
    # gets pronounced as English-like phonemes.
    tts = SarvamTTSService(
        api_key=os.getenv("SARVAM_API_KEY"),
        model="bulbul:v3",
        voice_id="kavitha",
        params=SarvamTTSService.InputParams(
            language=Language.TE_IN,
            pace=1.3,
        ),
    )

    messages = [
        {
            "role": "system",
            "content": (
                "మీరు వచనం, హైదరాబాద్‌లోని ఒక డెంటల్ క్లినిక్‌కి రిసెప్షనిస్ట్. "
                "పేషంట్‌కి అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేయండి. "
                "ప్రతి రిప్లై లో ఒకటి లేదా రెండు చిన్న వాక్యాలే మాట్లాడండి. "
                "ఇది ఫోన్ కాల్ కాబట్టి లిస్ట్‌లు, మార్క్‌డౌన్, స్పెషల్ క్యారెక్టర్‌లు వాడవద్దు. "
                "తెలుగు లోనే మాట్లాడండి. English పదాలు అవసరమైతేనే వాడండి. "
                "మీ సమాధానం తెలుగు లిపిలో ఇవ్వండి, రోమన్ లిపిలో కాదు. "
                "సంభాషణ ఫ్లో: "
                "1) మొదట గ్రీటింగ్ చెప్పి పేరు అడగండి (హార్డ్‌కోడెడ్ గ్రీటింగ్ ఇప్పటికే మాట్లాడబడింది). "
                "2) పేరు తర్వాత, ఏం సమస్య అని అడగండి. "
                "3) రేపు ఉదయం లేదా మధ్యాహ్నం స్లాట్ ఆఫర్ చేయండి. "
                "4) కన్ఫర్మ్ చేసి పొలైట్‌గా కాల్ ముగించండి. "
                "గ్రీటింగ్‌ని ప్రతి టర్న్ లో రిపీట్ చేయవద్దు — మొదట ఒకసారే చెప్పండి."
            ),
        },
    ]

    context = LLMContext(messages)
    # VAD tuned aggressive to reject bot-echo through patient phone speaker→mic:
    # - confidence=0.85 (default 0.5) — only accept high-confidence speech
    # - min_volume=0.8 (default 0.6) — reject quieter audio (bot echo arrives quieter)
    # - start_secs=0.3, stop_secs=0.5 — longer pauses required before triggering
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.85,
            min_volume=0.8,
            start_secs=0.3,
            stop_secs=0.5,
        )
    )
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=vad),
    )

    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            stt,  # Speech-To-Text
            context_aggregator.user(),
            llm,  # LLM
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to client
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,   # Vobiz MULAW input (8kHz telephony)
            audio_out_sample_rate=24000, # OpenAI TTS native (auto-resampled to 8kHz for Vobiz)
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Direct TTS frame — skips LLM, bot speaks within ~500ms of connect.
        # Hardcoded greeting matches what the system prompt instructs the LLM to say first.
        logger.info("Starting call — queuing direct TTS greeting")
        await task.queue_frames([
            TTSSpeakFrame("నమస్కారం, ఇది వచనం డెంటల్ క్లినిక్. మీ పేరు చెప్పగలరా?")
        ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Outbound call ended")
        # task.cancel() is correct when the *caller* hangs up first — the
        # WS is already dead so there is no in-flight TTS to drain. If your
        # bot ends the call itself (e.g. graceful EndFrame from a flow),
        # prefer `await task.stop_when_done()` so queued TTS frames finish
        # playing before the pipeline tears down.
        await task.cancel()

    runner = PipelineRunner(handle_sigint=handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments, call_id: str = None, stream_id: str = None):
    """Main bot entry point compatible with Pipecat Cloud."""

    # Read Vobiz's `start` event off the WebSocket to learn the negotiated
    # wire format (encoding + sample rate + IDs). Env vars are fallback hints.
    env_encoding = os.getenv("VOBIZ_ENCODING", "audio/x-mulaw")
    env_sample_rate = int(os.getenv("VOBIZ_SAMPLE_RATE", "8000"))

    # Resilient parser: Vobiz outbound trunk sometimes sends binary audio frames
    # BEFORE the start text frame. The default parse_vobiz_start uses receive_text()
    # which crashes on binary-first. We drain binary frames until we see the start
    # text or hit a 5s timeout.
    parsed = await _resilient_parse_vobiz_start(runner_args.websocket, timeout=5.0)
    logger.info(
        f"Vobiz start: callId={parsed['call_id']!r}, streamId={parsed['stream_id']!r}, "
        f"mediaFormat=({parsed['encoding']!r}, {parsed['sample_rate']})"
    )
    call_id = call_id or parsed["call_id"]
    stream_id = stream_id or parsed["stream_id"]
    vobiz_encoding = parsed["encoding"] or env_encoding
    vobiz_sample_rate = parsed["sample_rate"] or env_sample_rate

    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=os.getenv("VOBIZ_AUTH_ID", ""),
        auth_token=os.getenv("VOBIZ_AUTH_TOKEN", ""),
        params=VobizFrameSerializer.InputParams(
            vobiz_sample_rate=vobiz_sample_rate,
            encoding=vobiz_encoding,
            sample_rate=None,
            l16_byte_order=os.getenv("VOBIZ_L16_ENDIAN", "be"),
            auto_hang_up=True,
        ),
    )

    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # CRITICAL: Must be False for telephony
            serializer=serializer,
            # NOTE: vad_analyzer is deprecated on FastAPIWebsocketParams in
            # pipecat 1.x. VAD is now wired on LLMUserAggregatorParams above.
        ),
    )

    handle_sigint = runner_args.handle_sigint

    await run_bot(transport, handle_sigint)
