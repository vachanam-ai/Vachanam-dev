"""C1 Gemini generator: prompt assembly (few-shot from bank) + parse + retry.
Gemini is mocked — no network."""
import json


from agent.eval.example_bank import ExampleBank
from agent.i18n import te_gen


def test_build_prompt_includes_situations_and_fewshot():
    p = te_gen.build_prompt(
        {"greeting": "answer the phone warmly"},
        {"greeting": ["నమస్తే అండి, {clinic} నుంచి."]},
    )
    assert "greeting" in p
    assert "answer the phone warmly" in p
    assert "నమస్తే అండి" in p              # few-shot example injected
    assert "TELUGU SCRIPT ONLY" in p        # hard rules present


def test_build_prompt_without_examples():
    p = te_gen.build_prompt({"ok": "acknowledge"}, None)
    assert "ok" in p and "APPROVED example" not in p


class _Resp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text, fail_times=0):
        self._text = text
        self._fail = fail_times
        self.calls = 0

    def generate_content(self, model, contents):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("503 high demand")
        return _Resp(self._text)


class _FakeClient:
    def __init__(self, text, fail_times=0):
        self.models = _FakeModels(text, fail_times)


def test_generate_lines_parses_json(monkeypatch):
    monkeypatch.setattr(te_gen.time, "sleep", lambda *_: None)
    client = _FakeClient(json.dumps({"greeting": "నమస్తే అండి."}, ensure_ascii=False))
    out = te_gen.generate_lines({"greeting": "answer warmly"}, client=client)
    assert out == {"greeting": "నమస్తే అండి."}


def test_generate_lines_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(te_gen.time, "sleep", lambda *_: None)
    client = _FakeClient('```json\n{"ok": "ఓకే అండి."}\n```', fail_times=2)
    out = te_gen.generate_lines({"ok": "ack"}, client=client)
    assert out["ok"] == "ఓకే అండి."
    assert client.models.calls == 3  # 2 failures + 1 success


def test_generate_lines_pulls_fewshot_from_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(te_gen.time, "sleep", lambda *_: None)
    bank = ExampleBank(path=tmp_path / "b.json")
    bank.add("greeting", "నమస్తే అండి, {clinic} నుంచి.")

    captured = {}

    class _CaptureModels:
        def generate_content(self, model, contents):
            captured["prompt"] = contents
            return _Resp('{"greeting": "నమస్తే అండి."}')

    class _CaptureClient:
        models = _CaptureModels()

    te_gen.generate_lines({"greeting": "answer"}, bank=bank, client=_CaptureClient())
    assert "నమస్తే అండి, {clinic} నుంచి." in captured["prompt"]  # bank example reached the prompt
