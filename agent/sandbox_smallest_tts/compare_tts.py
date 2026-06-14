"""Isolated TTS comparison sandbox: smallest.ai (Waves) vs Sarvam (Bulbul).

OUT OF FLOW — this touches NOTHING in the live agent. It only synthesizes a few
real Vachanam Telugu clinic lines through both providers and saves the WAVs so the
voices can be compared by ear. Run it, listen to out/*.wav, pick a provider.

Secrets are read from the environment / a local .env (gitignored). The key is
NEVER printed in full — only a masked tail. Nothing here is imported by the agent.

Run:
    cd agent/sandbox_smallest_tts
    python compare_tts.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv
    # Load this sandbox's .env (the smallest key) AND the repo root .env (Sarvam key).
    HERE = Path(__file__).resolve().parent
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parents[1] / ".env")  # repo root .env for SARVAM_API_KEY
except Exception:
    pass

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

SMALLEST_KEY = os.getenv("SMALLEST_API_KEY", "")
SARVAM_KEY = os.getenv("SARVAM_API_KEY", "")

# Real Vachanam clinic lines (Telugu script) — the actual things the agent says.
LINES = {
    "greeting": (
        "నమస్కారం! శ్రీ డెంటల్ కేర్ కి స్వాగతం. నేను క్లినిక్ AI అసిస్టెంట్‌ని. "
        "మీకు ఏ విధంగా సహాయపడగలను?"
    ),
    "confirm": (
        "సరే అండి, రేపు ఉదయం పది గంటలకి మీ అపాయింట్‌మెంట్ ఫిక్స్ అయింది. "
        "టోకెన్ నంబర్ మూడు. టైంకి వచ్చేయండి, ధన్యవాదాలు!"
    ),
}


def _mask(key: str) -> str:
    return f"...{key[-4:]}" if key else "(missing)"


# ──────────────────────────────────────────────────────────────────────────
# smallest.ai (Waves)
# ──────────────────────────────────────────────────────────────────────────
SMALLEST_TTS_URL = "https://api.smallest.ai/waves/v1/tts"
SMALLEST_VOICES_URL = "https://api.smallest.ai/waves/v1/voices"


def smallest_list_voices() -> list[dict]:
    """Best-effort voice discovery so we can pick a Telugu-capable voice."""
    headers = {"Authorization": f"Bearer {SMALLEST_KEY}"}
    for url in (SMALLEST_VOICES_URL, "https://api.smallest.ai/waves/v1/get_voices"):
        try:
            r = httpx.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                data = r.json()
                voices = data.get("voices", data) if isinstance(data, dict) else data
                if isinstance(voices, list) and voices:
                    return voices
        except Exception as e:
            print(f"  [voices] {url} -> {e}")
    return []


def smallest_tts(text: str, voice_id: str, model: str, out_path: Path) -> tuple[bool, str]:
    headers = {
        "Authorization": f"Bearer {SMALLEST_KEY}",
        "Content-Type": "application/json",
        "Accept": "audio/wav",
    }
    body = {
        "text": text,
        "voice_id": voice_id,
        "model": model,
        "sample_rate": 24000,
        "output_format": "wav",
    }
    try:
        r = httpx.post(SMALLEST_TTS_URL, headers=headers, json=body, timeout=60)
    except Exception as e:
        return False, f"request error: {e}"
    ctype = r.headers.get("content-type", "")
    if r.status_code == 200 and ("audio" in ctype or r.content[:4] == b"RIFF"):
        out_path.write_bytes(r.content)
        return True, f"OK {len(r.content)} bytes (voice={voice_id}, model={model})"
    return False, f"HTTP {r.status_code} ct={ctype} body={r.text[:300]}"


# ──────────────────────────────────────────────────────────────────────────
# Sarvam (Bulbul) — current production TTS, for A/B
# ──────────────────────────────────────────────────────────────────────────
def sarvam_tts(text: str, out_path: Path) -> tuple[bool, str]:
    import base64

    headers = {"api-subscription-key": SARVAM_KEY, "Content-Type": "application/json"}
    body = {
        "inputs": [text],
        "target_language_code": "te-IN",
        "speaker": "anushka",
        "model": "bulbul:v2",
        "speech_sample_rate": 24000,
    }
    try:
        r = httpx.post(
            "https://api.sarvam.ai/text-to-speech", headers=headers, json=body, timeout=60
        )
    except Exception as e:
        return False, f"request error: {e}"
    if r.status_code == 200:
        try:
            audios = r.json().get("audios", [])
            if audios:
                out_path.write_bytes(base64.b64decode(audios[0]))
                return True, f"OK {out_path.stat().st_size} bytes"
        except Exception as e:
            return False, f"decode error: {e}"
    return False, f"HTTP {r.status_code} body={r.text[:300]}"


def main() -> int:
    print("=" * 70)
    print("Vachanam TTS sandbox — smallest.ai vs Sarvam (Telugu clinic lines)")
    print("=" * 70)
    print(f"smallest.ai key: {_mask(SMALLEST_KEY)}   Sarvam key: {_mask(SARVAM_KEY)}")
    if not SMALLEST_KEY:
        print("ERROR: SMALLEST_API_KEY not set (put it in agent/sandbox_smallest_tts/.env)")
        return 1

    # 1) Discover Telugu-capable voices.
    print("\n[1] Discovering smallest.ai voices...")
    voices = smallest_list_voices()
    telugu_voices: list[str] = []
    if voices:
        print(f"    {len(voices)} voices returned. Scanning for Telugu support...")
        for v in voices:
            blob = json.dumps(v).lower()
            if "telugu" in blob or '"te"' in blob or "te-in" in blob:
                vid = v.get("voiceId") or v.get("voice_id") or v.get("id") or v.get("name")
                if vid:
                    telugu_voices.append(str(vid))
        print(f"    Telugu-capable voice_ids: {telugu_voices[:10] or 'none flagged'}")
    else:
        print("    voices endpoint gave nothing usable — will try candidate voice_ids.")

    # Candidate voices to attempt (Telugu-flagged first, then common multilingual ones).
    candidates = telugu_voices[:3] + ["meher", "anjali", "raghav", "arman"]
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    # 2) Synthesize with smallest.ai — first candidate voice that returns audio wins.
    print("\n[2] smallest.ai synthesis (model lightning_v3.1_pro)...")
    working_voice = None
    for voice in candidates:
        ok, msg = smallest_tts(
            LINES["greeting"], voice, "lightning_v3.1_pro",
            OUT / f"smallest_greeting_{voice}.wav",
        )
        print(f"    voice={voice}: {msg}")
        if ok:
            working_voice = voice
            break
    if working_voice:
        ok2, msg2 = smallest_tts(
            LINES["confirm"], working_voice, "lightning_v3.1_pro",
            OUT / f"smallest_confirm_{working_voice}.wav",
        )
        print(f"    confirm line (voice={working_voice}): {msg2}")
    else:
        print("    No smallest.ai voice produced Telugu audio — see errors above.")

    # 3) Sarvam A/B (optional).
    print("\n[3] Sarvam (bulbul) synthesis for comparison...")
    if SARVAM_KEY:
        for name, text in LINES.items():
            ok, msg = sarvam_tts(text, OUT / f"sarvam_{name}.wav")
            print(f"    {name}: {msg}")
    else:
        print("    SARVAM_API_KEY not set — skipping (smallest.ai is the trial subject).")

    print("\n" + "=" * 70)
    print(f"Done. Audio in: {OUT}")
    print("Listen to smallest_*.wav vs sarvam_*.wav and pick the better Telugu voice.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
