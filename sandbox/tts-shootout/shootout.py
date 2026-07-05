"""SANDBOX — smallest.ai Telugu TTS shootout (Fix 2, 2026-07-05). No product code.

Synthesizes 5 real agent lines per (model × voice × speed), concatenates them
into ONE listenable WAV per combo, plus an 8 kHz copy (what a PSTN caller
actually hears). Prints an RMS-loudness table. Vinay listens, picks; the winner
becomes settings.smallest_model / default voice / speed.

Run:  python sandbox/tts-shootout/shootout.py
"""
import io
import sys
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backend.config import settings  # noqa: E402
from backend.services import smallest_voice  # noqa: E402

OUT = Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)

LINES = [
    "నమస్కారం, వాసవి క్లినిక్‌కి స్వాగతం! నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని. చెప్పండి, మీకు ఎలా సహాయం చేయగలను?",
    "అలాగే అండి. రేపు మధ్యాహ్నం రెండున్నరకి డాక్టర్ శ్రీనివాస్ గారి దగ్గర ఖాళీ ఉంది. బుక్ చేయమంటారా?",
    "కంగారు పడకండి అండి, డాక్టర్ గారు చూస్తారు. ఈరోజే వచ్చేయండి.",
    "మీ నంబర్ తొమ్మిది ఎనిమిది ఒకటి రెండు మూడు నాలుగు ఐదు ఆరు ఏడు ఎనిమిది — కరెక్టేనా అండి?",
    "సరే అండి, మీ అపాయింట్మెంట్ కన్ఫర్మ్ అయింది. టోకెన్ నంబర్ పన్నెండు. ధన్యవాదాలు!",
]
MODELS = ["lightning_v3.1", "lightning-large", "lightning-v2"]
SPEEDS = [0.9, 1.0]


def synth(model, voice, speed, text):
    r = httpx.post(
        "https://api.smallest.ai/waves/v1/tts",
        headers={"Authorization": f"Bearer {settings.smallest_api_key}",
                 "Content-Type": "application/json"},
        json={"model": model, "voice_id": voice, "sample_rate": 24000,
              "speed": speed, "language": "te", "output_format": "wav", "text": text},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.content


def pcm_of(wav_bytes):
    wf = wave.open(io.BytesIO(wav_bytes), "rb")
    sr, pcm = wf.getframerate(), wf.readframes(wf.getnframes())
    wf.close()
    return sr, pcm


def write_wav(path, sr, pcm):
    wf = wave.open(str(path), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(pcm)
    wf.close()


def to_8k(sr, pcm):  # ponytail: decimation without filter — fine for A/B listening
    import array
    a = array.array("h", pcm)
    step = sr / 8000
    return array.array("h", (a[int(i * step)] for i in range(int(len(a) / step)))).tobytes()


def rms(pcm):
    import array
    import math
    a = array.array("h", pcm)
    return round(math.sqrt(sum(x * x for x in a) / max(len(a), 1)))


def main():
    voices = [v["voice_id"] for v in smallest_voice.list_voices("te")[:3]]
    print(f"voices: {voices}\n{'combo':44} {'dur':>5} {'rms':>6}")
    gap = b"\x00" * 24000  # 0.5s @ 24k
    for model in MODELS:
        for voice in voices:
            for speed in SPEEDS:
                name = f"{model}_{voice}_{speed}".replace(".", "p")
                try:
                    clips = [pcm_of(synth(model, voice, speed, t)) for t in LINES]
                except Exception as e:
                    print(f"{name:44} FAIL {str(e)[:60]}")
                    break  # model/voice combo dead — skip remaining speeds
                sr = clips[0][0]
                pcm = gap.join(c[1] for c in clips)
                write_wav(OUT / f"{name}.wav", sr, pcm)
                write_wav(OUT / f"{name}_8k.wav", 8000, to_8k(sr, pcm))
                print(f"{name:44} {len(pcm)/2/sr:4.1f}s {rms(pcm):6}")


if __name__ == "__main__":
    main()
