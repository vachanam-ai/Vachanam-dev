# smallest.ai vs Sarvam — TTS comparison sandbox

**Out of flow.** This directory is an isolated trial to compare smallest.ai (Waves)
TTS against the production Sarvam (Bulbul) TTS on real Vachanam Telugu clinic lines.
It imports **nothing** from the live agent and the live agent imports **nothing**
from here. Deleting this folder changes nothing in production.

## What it proves
`compare_tts.py` synthesizes two real agent lines (the greeting + a booking
confirmation, in Telugu script) through both providers and writes WAVs to `out/`,
so the voices can be judged by ear.

## Run
```bash
cd agent/sandbox_smallest_tts
# .env holds SMALLEST_API_KEY (gitignored); SARVAM_API_KEY is read from the repo .env
python compare_tts.py
# then listen to out/smallest_*.wav vs out/sarvam_*.wav
```

## Result (2026-06-14 trial)
- smallest.ai endpoint `POST https://api.smallest.ai/waves/v1/tts`, model
  `lightning_v3.1_pro`, voice `meher` — **accepted Telugu script and returned valid
  24 kHz WAV audio** (greeting 6.2s, confirm 11.7s).
- Sarvam `bulbul:v2` for the same lines (greeting 6.3s, confirm 7.2s).
- Pronunciation quality is a listen-by-ear decision (see `out/`). `meher` rendered
  the confirm line ~60% slower than Sarvam — smallest.ai exposes a `speed`/voice
  choice to tune if adopted.

## Secrets
`SMALLEST_API_KEY` lives only in `agent/sandbox_smallest_tts/.env` (gitignored).
The trial key was pasted in chat — **rotate it** after testing. To wire smallest.ai
into the real agent later, it would replace `sarvam.TTS(...)` in
`agent/livekit_minimal/agent.py` with a smallest.ai TTS adapter — NOT done here.
