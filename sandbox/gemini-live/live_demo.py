"""SANDBOX — Gemini Live native-audio Telugu demo. NOT wired to the product.

Purpose: hear how Google's speech-to-speech model sounds in Telugu (tone,
pauses, prosody) versus our Sarvam STT -> Gemini -> smallest.ai cascade.
Nothing here touches agent/ or backend/; only GEMINI_API_KEY is reused
from the repo .env.

Run (from repo root, with a mic + HEADPHONES to avoid echo):
    python sandbox/gemini-live/live_demo.py
Options:
    --voice Aoede|Leda|Kore|Puck|Charon|...   (default Leda)
    --model <live model id>                    (default below; alternates:
        gemini-2.5-flash-preview-native-audio-dialog, gemini-live-2.5-flash-preview)
    --speakers   mute mic while agent audio is playing (no headphones; kills barge-in)
    --text       type instead of talking (mic problems / quick checks)

Ctrl+C to hang up. Native-audio sessions cap around 15 min — plenty.
"""
import argparse
import asyncio
import os
import queue
import sys
import threading
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types

# Windows console defaults to cp1252 — Telugu transcript lines would crash print()
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEND_RATE = 16000   # Live API input: 16-bit PCM, 16 kHz, mono
RECV_RATE = 24000   # Live API output: 16-bit PCM, 24 kHz, mono
CHUNK_MS = 50

DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"

SYSTEM_PROMPT = """
You are the receptionist at Sri Dental Care, a dental clinic in Hyderabad.
You are a warm, calm woman answering the clinic's phone.

Speak ONLY Telugu. Mixing everyday English words the way Telugu speakers
naturally do (appointment, doctor, time, scan) is good; full English
sentences are not.

Style: short spoken sentences, one thought at a time. Warm and unhurried.
Use natural backchannels like "అలాగే", "సరే అండి", "అవునండి". Address the
caller with అండి. Never sound like you are reading.

Open the call with: "నమస్కారం! శ్రీ డెంటల్ కేర్. చెప్పండి, మీకు ఎలా సహాయం చేయగలను?"

You can chat about appointments, timings, doctors (Dr. Srinivas is available
today 10 to 1 and 4 to 8), directions. Invent plausible details freely —
this is a voice demo, not a real clinic. Give NO medical advice ever; if
asked, warmly say the doctor will discuss it during the visit.
""".strip()


def load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        env = Path(__file__).resolve().parents[2] / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        sys.exit("GEMINI_API_KEY not found in environment or repo .env")
    return key


class Player:
    """Speaker playback on its own thread; queue drained instantly on barge-in."""

    def __init__(self):
        self.q: queue.Queue[bytes | None] = queue.Queue()
        self.playing = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        with sd.RawOutputStream(samplerate=RECV_RATE, channels=1, dtype="int16") as out:
            while True:
                chunk = self.q.get()
                if chunk is None:
                    return
                self.playing.set()
                out.write(chunk)
                if self.q.empty():
                    self.playing.clear()

    def feed(self, chunk: bytes):
        self.q.put(chunk)

    def flush(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.playing.clear()


async def mic_sender(session, player: Player, half_duplex: bool):
    loop = asyncio.get_running_loop()
    aq: asyncio.Queue[bytes] = asyncio.Queue()
    blocksize = SEND_RATE * CHUNK_MS // 1000

    def cb(indata, frames, t, status):
        loop.call_soon_threadsafe(aq.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=SEND_RATE, blocksize=blocksize,
                           channels=1, dtype="int16", callback=cb):
        print("mic live — talk (Telugu). Ctrl+C to hang up.")
        while True:
            chunk = await aq.get()
            if half_duplex and player.playing.is_set():
                continue  # speakers mode: drop mic while agent talks (echo guard)
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={SEND_RATE}")
            )


async def text_sender(session):
    loop = asyncio.get_running_loop()
    while True:
        text = await loop.run_in_executor(None, input, "you> ")
        if not text.strip():
            continue
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )


async def receiver(session, player: Player):
    agent_line = ""
    while True:
        async for msg in session.receive():
            if msg.data:
                player.feed(msg.data)
            sc = msg.server_content
            if not sc:
                continue
            if sc.interrupted:
                player.flush()
                print("\n[barge-in]")
            if sc.input_transcription and sc.input_transcription.text:
                print(f"\ncaller: {sc.input_transcription.text}", flush=True)
            if sc.output_transcription and sc.output_transcription.text:
                agent_line += sc.output_transcription.text
            if sc.turn_complete and agent_line:
                print(f"agent: {agent_line}", flush=True)
                agent_line = ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--voice", default="Leda")
    ap.add_argument("--speakers", action="store_true",
                    help="no headphones: mute mic while agent audio plays")
    ap.add_argument("--text", action="store_true", help="type instead of talking")
    args = ap.parse_args()

    client = genai.Client(api_key=load_api_key())
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM_PROMPT)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=args.voice)
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    print(f"connecting: {args.model} voice={args.voice}")
    player = Player()
    async with client.aio.live.connect(model=args.model, config=config) as session:
        # nudge the model to speak the greeting first, like a picked-up call
        await session.send_client_content(
            turns=types.Content(role="user",
                                parts=[types.Part(text="[కాల్ కనెక్ట్ అయింది — గ్రీట్ చేయండి]")]),
            turn_complete=True,
        )
        sender = text_sender(session) if args.text else mic_sender(session, player, args.speakers)
        await asyncio.gather(receiver(session, player), sender)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nhung up.")
