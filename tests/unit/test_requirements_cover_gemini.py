"""#330 regression: the code imports the NEW Gemini SDK (`from google import
genai`, package `google-genai`). The requirements once pinned only the OLD
`google-generativeai` package — prod then threw ImportError on every bot call
and the RULE-8 fallback masked it for days. Keep the real pin present."""
from pathlib import Path


def test_google_genai_pinned():
    reqs = Path("backend/requirements.txt").read_text(encoding="utf-8")
    lines = [l.split("#")[0].strip() for l in reqs.splitlines()]
    assert any(l.startswith("google-genai") for l in lines), (
        "backend/requirements.txt must pin google-genai (the NEW SDK that "
        "support_bot + call_scoring import); google-generativeai is NOT it")
    assert not any(l.startswith("google-generativeai") for l in lines), (
        "old google-generativeai pin is dead weight — nothing imports it")
