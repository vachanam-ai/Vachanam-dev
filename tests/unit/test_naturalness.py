"""C2 naturalness judge: deterministic pronunciation flags + merged LLM rubric.
Gemini mocked."""
import json

from agent.eval import naturalness


def test_pronunciation_flags_catches_romanized():
    assert naturalness.pronunciation_flags("నాకు time కావాలి") == ["time"]
    # placeholders are template-time, ignored
    assert naturalness.pronunciation_flags("{clinic} నుంచి, {doctor} గారు") == []
    # pure Telugu (incl. Tenglish in Telugu script) → no flags
    assert naturalness.pronunciation_flags("ఓకే అండి, టైం కంఫర్టబుల్ అండి?") == []


class _Resp:
    def __init__(self, text):
        self.text = text


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    class _M:
        pass

    @property
    def models(self):
        outer = self

        class _M:
            def generate_content(self, model, contents):
                return _Resp(json.dumps(outer._payload, ensure_ascii=False))

        return _M()


def test_score_merges_pronunciation_flags(monkeypatch):
    monkeypatch.setattr(naturalness.time, "sleep", lambda *_: None)
    payload = {"scores": {"warmth": 4}, "human_likeness": 4, "suggestions": []}
    client = _FakeClient(payload)
    transcript = [
        {"role": "agent", "text": "నమస్తే అండి, please చెప్పండి"},  # romanized 'please'
        {"role": "user", "text": "అపాయింట్‌మెంట్ కావాలి"},
    ]
    out = naturalness.score_naturalness(transcript, client=client)
    assert out["human_likeness"] == 4
    assert out["pronunciation_flags"] == ["please"]
    assert any("Romanized" in s for s in out["suggestions"])  # flag surfaced
