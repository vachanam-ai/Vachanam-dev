"""clone_voice sends a dashboard tag ("Tamil") and falls back tag-less on a
tags-rejecting 400 (smallest dashboard showed 'Not available' for our clones)."""


from backend.services import smallest_voice


class _Resp:
    def __init__(self, status_code, text="", body=None):
        self.status_code = status_code
        self.text = text
        self.content = b"x"
        self._body = body or {}

    def json(self):
        return self._body


def test_tag_included_in_clone_payload(monkeypatch):
    seen = []

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        seen.append(data)
        return _Resp(200, body={"voiceId": "voice_ok"})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(smallest_voice.settings, "smallest_api_key", "k")
    vid = smallest_voice.clone_voice("sree", "s.wav", b"RIFF", language="ta", tag="Tamil")
    assert vid == "voice_ok"
    assert seen[0]["tags"] == "Tamil"


def test_tag_rejected_retries_without(monkeypatch):
    seen = []

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        seen.append(data)
        if "tags" in (data or {}):
            return _Resp(400, text='{"error":"invalid tags field"}')
        return _Resp(200, body={"voiceId": "voice_ok2"})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(smallest_voice.settings, "smallest_api_key", "k")
    vid = smallest_voice.clone_voice("sree", "s.wav", b"RIFF", language="ta", tag="Tamil")
    assert vid == "voice_ok2"
    assert len(seen) == 2 and "tags" not in seen[1]
