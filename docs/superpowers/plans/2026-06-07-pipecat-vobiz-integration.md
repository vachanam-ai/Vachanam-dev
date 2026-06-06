# Pipecat + Vobiz Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Per-task TDD checklist (`- [ ]` items) tracks progress. Per CLAUDE.md mandatory-dispatch rule, the orchestrator NEVER edits `agent/`, `backend/`, `infra/`, `tests/`, `scripts/`, `.env`, `.env.example` directly — every task is dispatched to a specialist subagent (voice-agent-engineer, backend-engineer, devops-engineer, tester) with the full task body inline.

**Spec:** `docs/superpowers/specs/2026-06-07-pipecat-vobiz-integration.md`
**Goal:** Replace removed LiveKit Agents + Vobiz SIP code with Pipecat over Vobiz WebSocket; place the first real inbound Telugu call today.
**Architecture:** FastAPI server (`agent/server.py`) on `:7860` accepts Vobiz webhook + WebSocket upgrade. Per-call Pipecat pipeline (`agent/bot.py`) handles STT (Sarvam Saaras v3 `te-IN`) → LLM (Gemini 2.5 Flash → GPT-4o-mini fallback) → TTS (Sarvam Bulbul v3) with VAD on `LLMUserAggregatorParams` and `add_wav_header=False` per Pipecat 1.x telephony spec. Cloudflare Tunnel `vachanam-agent` exposes the server at `https://agent-dev.vachanam.in`.
**Tech Stack:** `pipecat-ai[websocket,silero,openai,google,sarvam]>=1.2.0,<2`, `pipecat-ai-vobiz>=0.0.3,<0.1`, FastAPI 0.110+, uvicorn 0.27+, SQLAlchemy 2.x async, asyncpg, redis 5, structlog, tenacity, loguru, python-multipart, python-dotenv.

---

## Task 1: Environment + config migration

**Owner:** backend-engineer
**Files:**
- Modify: `.env.example` (root)
- Modify: `.env` (root — preserve existing values for renames)
- Modify: `backend/config.py:1-200` (Pydantic settings)
- Modify: `.gitignore` (root)

**What changes:**
- DELETE keys: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_TRUNK_ID`.
- RENAME `VOBIZ_PARTNER_AUTH_ID` → `VOBIZ_AUTH_ID`; `VOBIZ_PARTNER_AUTH_TOKEN` → `VOBIZ_AUTH_TOKEN` (preserve values from existing `.env`).
- ADD keys: `PUBLIC_URL=https://agent-dev.vachanam.in`, `RECORDING_ENABLED=true`, `MAX_CALL_DURATION_SECONDS=0`.
- `backend/config.py` Pydantic `Settings` class adds matching fields with defaults (`recording_enabled: bool = False`, `max_call_duration_seconds: int = 0`, `public_url: str = "http://localhost:7860"`, `vobiz_auth_id: str = ""`, `vobiz_auth_token: str = ""`, `vobiz_did_number: str = ""`). Drop the deleted-key fields. Keep `model_config = ConfigDict(extra="ignore")` so old keys still in some env files do not crash startup.
- `.gitignore` append:
  ```
  agent/recordings/*.mp3
  agent/recordings/*.wav
  agent/recordings/*.ogg
  ```

- [ ] **Step 1: Write failing test for config migration**

```python
# tests/unit/test_config_migration.py
from backend.config import settings

def test_config_has_new_keys():
    assert hasattr(settings, "public_url")
    assert hasattr(settings, "recording_enabled")
    assert hasattr(settings, "max_call_duration_seconds")
    assert hasattr(settings, "vobiz_auth_id")
    assert hasattr(settings, "vobiz_auth_token")

def test_config_drops_livekit_keys():
    assert not hasattr(settings, "livekit_url")
    assert not hasattr(settings, "livekit_api_key")
    assert not hasattr(settings, "livekit_api_secret")

def test_config_drops_vobiz_sip_keys():
    assert not hasattr(settings, "vobiz_sip_domain")
    assert not hasattr(settings, "vobiz_sip_username")
    assert not hasattr(settings, "vobiz_sip_password")
    assert not hasattr(settings, "vobiz_trunk_id")
    assert not hasattr(settings, "vobiz_partner_auth_id")
    assert not hasattr(settings, "vobiz_partner_auth_token")

def test_recording_default_off_when_unset(monkeypatch):
    monkeypatch.delenv("RECORDING_ENABLED", raising=False)
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    assert cfg.settings.recording_enabled is False
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_config_migration.py -v
```
Expected: FAIL — current `settings` has `livekit_url` and is missing `public_url`.

- [ ] **Step 3: Edit `backend/config.py` to add new fields, remove deleted ones, preserve `extra="ignore"`.**

- [ ] **Step 4: Edit `.env.example` and `.env` per the change list above. Preserve values from old `VOBIZ_PARTNER_AUTH_*` → new `VOBIZ_AUTH_*`.**

- [ ] **Step 5: Edit `.gitignore` to add the 3 recordings glob patterns.**

- [ ] **Step 6: Run tests, verify GREEN**

```
pytest tests/unit/test_config_migration.py -v
pytest tests/ -k "not integration and not edge_cases" -x
```
Expected: PASS. Other unit tests must not regress.

- [ ] **Step 7: Commit**

```
git add backend/config.py .env.example .env .gitignore tests/unit/test_config_migration.py
git commit -m "refactor(config): migrate from LiveKit/SIP env to Pipecat/Vobiz-webhook env

- Drop LIVEKIT_*, VOBIZ_SIP_*, VOBIZ_TRUNK_ID, VOBIZ_PARTNER_AUTH_*
- Add PUBLIC_URL, RECORDING_ENABLED, MAX_CALL_DURATION_SECONDS
- Rename VOBIZ_PARTNER_AUTH_{ID,TOKEN} -> VOBIZ_AUTH_{ID,TOKEN}
- Gitignore agent/recordings/*.{mp3,wav,ogg}
- model_config extra=ignore preserved for backward compat"
```

---

## Task 2: Stub services (calendar + meta) for booking_tools injection

**Owner:** backend-engineer
**Files:**
- Create: `agent/services/calendar_stub.py`
- Create: `agent/services/meta_stub.py`
- Create: `tests/unit/test_stub_services.py`

`booking_tools.confirm_booking` accepts injected `calendar_service` and `meta_service`. Real Google Calendar + WhatsApp wait for Phase 4 / MVP2. These stubs let booking flow succeed end-to-end during dev calls.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_stub_services.py
import pytest
from datetime import date, time
from agent.services.calendar_stub import CalendarService
from agent.services.meta_stub import MetaService

@pytest.mark.asyncio
async def test_calendar_stub_returns_fake_event_id():
    cal = CalendarService()
    event_id = await cal.create_booking_event(
        calendar_id="cal@example.com",
        patient_name="Test",
        patient_phone="6789",
        token_number=1,
        booking_date=date.today(),
        appointment_time=None,
        doctor_name="Dr Test",
    )
    assert event_id.startswith("stub-")
    assert len(event_id) == len("stub-") + 36  # uuid4

@pytest.mark.asyncio
async def test_meta_stub_is_noop():
    meta = MetaService()
    result = await meta.send_booking_confirmation(
        to="+919000000000",
        patient_name="Test",
        doctor_name="Dr Test",
        clinic_name="Test Clinic",
        booking_date=date.today(),
        token_number=1,
        appointment_time=None,
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_stub_services.py -v
```
Expected: FAIL — files do not exist.

- [ ] **Step 3: Create `agent/services/calendar_stub.py`**

```python
from datetime import date, time
from uuid import uuid4

import structlog

logger = structlog.get_logger()


class CalendarService:
    """Stub Google Calendar service for dev/test.

    Real impl deferred to Phase 4 onboarding. Returns fake event ID so
    confirm_booking succeeds without external dependency.
    """

    async def create_booking_event(
        self,
        calendar_id: str | None,
        patient_name: str,
        patient_phone: str,
        token_number: int,
        booking_date: date,
        appointment_time: time | None,
        doctor_name: str,
    ) -> str:
        event_id = f"stub-{uuid4()}"
        logger.warning(
            "calendar_stub_used",
            event_id=event_id,
            calendar_id=calendar_id,
            token_number=token_number,
            phone=patient_phone[-4:] if patient_phone else "unknown",
            doctor=doctor_name,
        )
        return event_id
```

- [ ] **Step 4: Create `agent/services/meta_stub.py`**

```python
from datetime import date, time

import structlog

logger = structlog.get_logger()


class MetaService:
    """Stub WhatsApp Meta Cloud API service for dev/test.

    Real impl deferred to MVP2. No-op so booking flow does not block on
    WhatsApp delivery during dev calls. Fire-and-forget contract: caller
    wraps in try/except and treats any exception as a soft failure.
    """

    async def send_booking_confirmation(
        self,
        to: str,
        patient_name: str,
        doctor_name: str,
        clinic_name: str,
        booking_date: date,
        token_number: int,
        appointment_time: time | None,
    ) -> None:
        logger.warning(
            "meta_stub_used",
            to=to[-4:] if to else "unknown",
            token_number=token_number,
            doctor=doctor_name,
        )
        return None
```

- [ ] **Step 5: Run tests, verify GREEN**

```
pytest tests/unit/test_stub_services.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```
git add agent/services/calendar_stub.py agent/services/meta_stub.py tests/unit/test_stub_services.py
git commit -m "feat(agent): add CalendarService + MetaService stubs for Pipecat dev calls

Real Google Calendar deferred to Phase 4 onboarding; WhatsApp to MVP2.
Stubs let confirm_booking succeed end-to-end in dev without external
deps. Both log structured warnings with PII-masked phone (last 4)."
```

---

## Task 3: `agent/requirements.txt` + install verification

**Owner:** voice-agent-engineer
**Files:**
- Create: `agent/requirements.txt`
- Create: `tests/unit/test_pipecat_imports.py`

- [ ] **Step 1: Write failing test that asserts all required Pipecat classes import**

```python
# tests/unit/test_pipecat_imports.py
def test_pipecat_transport_imports():
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams  # noqa

def test_pipecat_pipeline_imports():
    from pipecat.pipeline.pipeline import Pipeline  # noqa
    from pipecat.pipeline.task import PipelineTask, PipelineParams  # noqa
    from pipecat.pipeline.runner import PipelineRunner  # noqa

def test_pipecat_sarvam_imports():
    from pipecat.services.sarvam.stt import SarvamSTTService  # noqa
    from pipecat.services.sarvam import SarvamTTSService  # noqa

def test_pipecat_google_imports():
    from pipecat.services.google import GoogleLLMService  # noqa

def test_pipecat_openai_imports():
    from pipecat.services.openai import OpenAILLMService  # noqa

def test_pipecat_vad_imports():
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa

def test_vobiz_helper_imports():
    from pipecat_vobiz import parse_vobiz_start  # noqa
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_pipecat_imports.py -v
```
Expected: FAIL — packages not installed.

- [ ] **Step 3: Create `agent/requirements.txt`**

```
pipecat-ai[websocket,silero,openai,google,sarvam]>=1.2.0,<2
pipecat-ai-vobiz>=0.0.3,<0.1
fastapi>=0.110
uvicorn[standard]>=0.27
aiohttp>=3.9
python-dotenv>=1.0
loguru>=0.7
python-multipart>=0.0.6
structlog>=24.1
tenacity>=8.2
redis>=5.0
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
```

- [ ] **Step 4: Install + run import test**

```
pip install -r agent/requirements.txt
pytest tests/unit/test_pipecat_imports.py -v
```
Expected: PASS. If any import fails, fix the exact extra name in the requirements line (Pipecat sub-package names sometimes differ between versions — voice-agent-engineer searches `pip show pipecat-ai` to verify available extras before locking).

- [ ] **Step 5: Commit**

```
git add agent/requirements.txt tests/unit/test_pipecat_imports.py
git commit -m "feat(agent): pin Pipecat 1.x + Vobiz transport dependencies

pipecat-ai[websocket,silero,openai,google,sarvam] >=1.2.0,<2
pipecat-ai-vobiz >=0.0.3,<0.1
Import-only smoke test in tests/unit/test_pipecat_imports.py."
```

---

## Task 4: Recording disclosure in system prompt Step 0

**Owner:** voice-agent-engineer
**Files:**
- Modify: `agent/prompts/system_prompt.py`
- Modify: `tests/unit/test_system_prompt.py` (or create if missing)

When `settings.recording_enabled` is True, Step 0 disclosure in Telugu must include "ఈ కాల్ నాణ్యత మెరుగుదల కోసం రికార్డ్ చేయబడుతుంది." When False, this sentence is absent.

- [ ] **Step 1: Read current `agent/prompts/system_prompt.py` to see Step 0 location**

- [ ] **Step 2: Write failing test**

```python
# tests/unit/test_system_prompt.py
from agent.prompts.system_prompt import build_system_prompt

def test_step_0_includes_recording_notice_when_enabled(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    prompt = build_system_prompt(branch_name="Test Clinic", doctors=[], emergency_contact="+919000000000")
    assert "రికార్డ్" in prompt

def test_step_0_omits_recording_notice_when_disabled(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    prompt = build_system_prompt(branch_name="Test Clinic", doctors=[], emergency_contact="+919000000000")
    assert "రికార్డ్" not in prompt
```

- [ ] **Step 3: Run test — verify failure**

```
pytest tests/unit/test_system_prompt.py -v
```
Expected: FAIL.

- [ ] **Step 4: Edit `agent/prompts/system_prompt.py` to inject recording sentence conditionally**

- [ ] **Step 5: Run test — verify GREEN**

- [ ] **Step 6: Commit**

```
git add agent/prompts/system_prompt.py tests/unit/test_system_prompt.py
git commit -m "feat(agent): add recording-consent disclosure to Step 0 (gated)

When RECORDING_ENABLED=true, Step 0 system prompt includes Telugu
recording-consent sentence required by DPDP Act 2023 minimization
principle. When false, sentence is absent. TESTING-ONLY override
per memory entry feedback-no-voice-recording (2026-06-07)."
```

---

## Task 5: `agent/server.py` skeleton + `/answer` XML golden test

**Owner:** voice-agent-engineer
**Files:**
- Create: `agent/server.py`
- Create: `agent/recordings/.gitkeep`
- Create: `tests/integration/test_server_answer.py`

`/answer` returns XML with `<Speak>`, `<Stream>`, and `<Record>` (when `RECORDING_ENABLED=true`). `/health` returns `{"status":"ok"}`. Other endpoints scaffolded as stubs returning 501 until later tasks fill them.

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_server_answer.py
import pytest
import re
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    from agent.server import app
    return TestClient(app)

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

def test_answer_returns_valid_xml(client):
    r = client.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"] or "text/xml" in r.headers["content-type"]
    body = r.text
    assert "<Response>" in body
    assert "<Stream" in body
    assert 'bidirectional="true"' in body
    assert 'contentType="audio/x-mulaw;rate=8000"' in body
    assert "wss://agent-dev.vachanam.in/ws" in body

def test_answer_includes_record_when_enabled(client):
    r = client.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert "<Record" in r.text
    assert "/recording-finished" in r.text

def test_answer_omits_record_when_disabled(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert "<Record" not in r.text
```

- [ ] **Step 2: Run test — verify failure**

```
pytest tests/integration/test_server_answer.py -v
```

- [ ] **Step 3: Create `agent/server.py`** with `/health`, `/answer`, and scaffolds for `/ws`, `/start`, `/recording-finished`, `/recording-ready`, `/transfer-emergency/{call_id}`. Use FastAPI `Form` params for Vobiz callback fields (`From`, `To`, `CallSid`). Return XML with `Response.media_type = "application/xml"`. Build the Stream URL from `settings.public_url` (strip `https://` → `wss://`).

- [ ] **Step 4: Create `agent/recordings/.gitkeep`**

- [ ] **Step 5: Run tests — verify GREEN**

- [ ] **Step 6: Commit**

```
git add agent/server.py agent/recordings/.gitkeep tests/integration/test_server_answer.py
git commit -m "feat(agent): FastAPI server with /answer XML + /health

- /answer returns <Response> with <Speak>, <Stream bidirectional>, <Record>
  (Record gated by RECORDING_ENABLED env flag)
- Stream URL derived from PUBLIC_URL (https -> wss)
- Other endpoints scaffolded for next tasks
- Recordings folder added with .gitkeep; MP3/WAV/OGG gitignored"
```

---

## Task 6: `agent/bot.py` Pipecat pipeline core

**Owner:** voice-agent-engineer
**Files:**
- Create: `agent/bot.py`
- Create: `tests/unit/test_bot_pipeline_builder.py`

`run_pipeline(websocket, call_id, did, caller)`:
1. Resolve `Branch` from `did` (CLAUDE.md RULE 5). Raise `ValueError` if unknown DID.
2. Load active doctors for the branch (`select(Doctor).where(branch_id == X, status == "active")`).
3. Build transport: `FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(add_wav_header=False, serializer=VobizFrameSerializer(), session_timeout=900))`.
4. Build services: `SarvamSTTService(api_key, settings=Settings(model="saaras:v3", language=Language.TE_IN), keepalive_interval=5.0)`, `GoogleLLMService(api_key, model="gemini-2.5-flash")`, `SarvamTTSService(api_key, settings=Settings(model="bulbul:v3", language=Language.TE_IN, voice="anushka"))`.
5. Build LLM context aggregator with `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(...))` per Pipecat 1.x.
6. Build pipeline: `Pipeline([transport.input(), stt, user_agg, llm, assistant_agg, tts, transport.output()])`.
7. Per-call `SessionState(branch_id=..., session_id=call_id, call_start=datetime.utcnow())`. Tools share via closure or `task.set_state()` (verify Pipecat 1.x API in TDD).
8. `PipelineRunner().run(PipelineTask(pipeline))`.

In this task: build the pipeline + return it. Tool registration (Task 7), interceptors (Task 8), disconnect handler (Task 9) come next.

- [ ] **Step 1: Write failing test for pipeline builder**

```python
# tests/unit/test_bot_pipeline_builder.py
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

@pytest.mark.asyncio
async def test_build_pipeline_resolves_branch_from_did(monkeypatch):
    """Pipeline builder must look up branch by DID and raise on unknown."""
    from agent.bot import resolve_branch_or_raise
    fake_db = MagicMock()
    fake_db.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(ValueError, match="unknown DID"):
        await resolve_branch_or_raise(fake_db, did="+910000000000")

@pytest.mark.asyncio
async def test_build_pipeline_uses_telugu_locale():
    """Saaras v3 STT service must use te-IN."""
    from agent.bot import build_stt_service
    stt = build_stt_service(api_key="test")
    # Sarvam SDK exposes settings post-construction; assert via private attr or kwarg capture
    assert "saaras:v3" in str(stt.__dict__.get("_model", "")) or "saaras:v3" in str(stt)
```

- [ ] **Step 2: Run test — verify failure**

- [ ] **Step 3: Implement `agent/bot.py` per spec §4 step 6. Keep `register_tools` and `attach_interceptors` as stub functions called from `run_pipeline` — bodies fill in next tasks.**

- [ ] **Step 4: Run tests — verify GREEN**

- [ ] **Step 5: Commit**

```
git add agent/bot.py tests/unit/test_bot_pipeline_builder.py
git commit -m "feat(agent): Pipecat pipeline core in agent/bot.py

- run_pipeline(websocket, call_id, did, caller) entrypoint
- Branch resolved from dialed DID; unknown DID raises ValueError
- Sarvam Saaras v3 te-IN STT, Gemini 2.5 Flash LLM, Sarvam Bulbul v3 TTS
- VAD on LLMUserAggregatorParams per Pipecat 1.x telephony requirement
- add_wav_header=False, FastAPI WebSocket transport with Vobiz serializer
- Tool registration + emergency interceptor + disconnect handler are stubs"
```

---

## Task 7: LLM fallback + booking tool registration

**Owner:** voice-agent-engineer
**Files:**
- Modify: `agent/bot.py`
- Create: `tests/unit/test_bot_tools_and_fallback.py`

Wire CLAUDE.md RULE 9 (Gemini → GPT-4o-mini fallback) using Pipecat's `LLMFallbackAdapter` (or, if 1.x ships a different class name, the equivalent — voice-agent-engineer verifies via `pipecat.services` introspection). Register the 4 booking tools (`route_to_doctor`, `check_availability`, `assign_token`, `confirm_booking`) via `FunctionSchema` + `llm.register_function(name, handler)`. Each handler unwraps `FunctionCallParams`, calls the booking_tools function with injected `db_session`, `redis_client`, `calendar_service`, `meta_service`, `session_state`, calls `params.result_callback(result_dict)`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_bot_tools_and_fallback.py
import pytest

def test_function_schemas_for_all_four_tools():
    from agent.bot import build_function_schemas
    schemas = build_function_schemas()
    names = {s.name for s in schemas}
    assert names == {"route_to_doctor", "check_availability", "assign_token", "confirm_booking"}

def test_fallback_wraps_gemini_with_openai_secondary():
    from agent.bot import build_llm_with_fallback
    llm = build_llm_with_fallback(gemini_key="g", openai_key="o")
    # Adapter exposes both services as attributes/iterables — exact assertion depends on adapter class
    assert llm is not None
```

- [ ] **Step 2: Run test — verify failure**

- [ ] **Step 3: Implement `build_function_schemas()` returning `list[FunctionSchema]` with full property descriptions matching `booking_tools.py` signatures. Implement `register_tools(llm, session_state, db_session, calendar_service, meta_service)` that wires each schema to an async handler. Implement `build_llm_with_fallback(gemini_key, openai_key)` returning the configured fallback LLM.**

- [ ] **Step 4: Run tests — verify GREEN**

- [ ] **Step 5: Commit**

```
git add agent/bot.py tests/unit/test_bot_tools_and_fallback.py
git commit -m "feat(agent): wire LLM fallback + register 4 booking tools

- Gemini 2.5 Flash primary, GPT-4o-mini fallback per CLAUDE.md RULE 9
- FunctionSchema definitions for route_to_doctor, check_availability,
  assign_token, confirm_booking
- Each handler unwraps FunctionCallParams, calls booking_tools fn,
  passes result via params.result_callback"
```

---

## Task 8: Emergency interceptor + TTS sanitizer frame processors

**Owner:** voice-agent-engineer
**Files:**
- Modify: `agent/bot.py`
- Modify: `agent/server.py` (signal channel from bot back to server for transfer)
- Create: `tests/unit/test_bot_interceptors.py`

Emergency: a Pipecat `FrameProcessor` subclass `EmergencyInterceptor` that watches `TranscriptionFrame`s. On `emergency.detect(text) == True`, it (a) cancels the pipeline (`PipelineFrame.STOP`), (b) signals the server via shared `asyncio.Event` or a per-call signal dict that this call should be transferred. The server, on detecting the signal, returns a fresh `<Response><Dial>{branch.emergency_contact}</Dial></Response>` via the `/transfer-emergency/{call_id}` endpoint OR by closing the WebSocket cleanly and letting Vobiz fall through to a configured fallback URL — voice-agent-engineer confirms the Vobiz semantics in TDD with one probe call before locking the mechanism.

TTS sanitizer: a `FrameProcessor` between LLM and TTS that catches `TextFrame`s, runs `sanitize_for_tts(text)`, replaces `frame.text`. Honors CLAUDE.md RULE 6.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_bot_interceptors.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_emergency_interceptor_fires_on_keyword():
    from agent.bot import EmergencyInterceptor
    from pipecat.frames.frames import TranscriptionFrame
    signal = MagicMock()
    interceptor = EmergencyInterceptor(emergency_signal=signal, branch_emergency_contact="+919000000000")
    frame = TranscriptionFrame(text="నాకు గుండె నొప్పి వస్తోంది", user_id="user", timestamp="t")
    await interceptor.process_frame(frame, direction="downstream")
    signal.set.assert_called_once()

@pytest.mark.asyncio
async def test_tts_sanitizer_strips_markdown():
    from agent.bot import TtsSanitizerProcessor
    from pipecat.frames.frames import TextFrame
    proc = TtsSanitizerProcessor()
    frame = TextFrame(text="**Token #8** confirmed!")
    out = await proc.process_frame(frame, direction="downstream")
    assert "**" not in out.text
    assert "#" not in out.text
```

- [ ] **Step 2: Run test — verify failure**

- [ ] **Step 3: Implement `EmergencyInterceptor` and `TtsSanitizerProcessor` in `agent/bot.py`. Wire both into `Pipeline([...])` between STT/aggregator and LLM (emergency) and between LLM and TTS (sanitizer).**

- [ ] **Step 4: Add `/transfer-emergency/{call_id}` to `agent/server.py` returning `<Response><Dial>{emergency_contact}</Dial></Response>`. Add server-side per-call signal map keyed by `call_id`. Bot triggers it on emergency; server polls/awaits when closing the WebSocket.**

- [ ] **Step 5: Run tests — verify GREEN**

- [ ] **Step 6: Commit**

```
git add agent/bot.py agent/server.py tests/unit/test_bot_interceptors.py
git commit -m "feat(agent): emergency keyword interceptor + TTS sanitizer processors

- EmergencyInterceptor watches TranscriptionFrames, fires asyncio.Event
  on keyword match, stops pipeline. Per feedback-emergency-transfer
  memory: live call transferred to branch.emergency_contact via <Dial>.
- TtsSanitizerProcessor runs sanitize_for_tts() on every TextFrame
  before TTS (CLAUDE.md RULE 6)
- /transfer-emergency/{call_id} returns <Dial> XML
- Per-call signal map keyed by call_id in agent/server.py"
```

---

## Task 9: WebSocket endpoint + disconnect handler with Redis DECR

**Owner:** voice-agent-engineer
**Files:**
- Modify: `agent/server.py` (`/ws` full impl)
- Modify: `agent/bot.py` (wrap PipelineRunner in try/finally that releases tokens)
- Create: `tests/edge_cases/test_disconnect_releases_token.py`

`/ws` accepts WebSocket, validates `to` + `call_id` query params (400 if missing), opens DB + Redis sessions, calls `bot.run_pipeline(websocket, call_id, did, caller)`. On any exception or disconnect, `finally` block: if `session_state.token_held and not session_state.token_confirmed`, `await redis.decr(session_state.token_redis_key)` and log `token_released_on_disconnect` (CLAUDE.md RULE 3).

- [ ] **Step 1: Write failing test**

```python
# tests/edge_cases/test_disconnect_releases_token.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from agent.session_state import SessionState

@pytest.mark.asyncio
async def test_disconnect_releases_unconfirmed_token():
    from agent.bot import release_token_on_disconnect
    redis = AsyncMock()
    state = SessionState(
        token_held=True, token_confirmed=False,
        token_redis_key="token:d:b:2026-06-07", token_number=5,
    )
    await release_token_on_disconnect(state, redis)
    redis.decr.assert_awaited_once_with("token:d:b:2026-06-07")

@pytest.mark.asyncio
async def test_disconnect_keeps_confirmed_token():
    from agent.bot import release_token_on_disconnect
    redis = AsyncMock()
    state = SessionState(token_held=True, token_confirmed=True, token_redis_key="k", token_number=5)
    await release_token_on_disconnect(state, redis)
    redis.decr.assert_not_called()
```

- [ ] **Step 2: Run test — verify failure**

- [ ] **Step 3: Implement `release_token_on_disconnect`, plug into bot.py's `finally` block, plug into server.py's `/ws` handler.**

- [ ] **Step 4: Run tests — verify GREEN**

- [ ] **Step 5: Commit**

```
git add agent/server.py agent/bot.py tests/edge_cases/test_disconnect_releases_token.py
git commit -m "feat(agent): WS endpoint + disconnect releases unconfirmed token

- /ws validates to+call_id query params (400 if missing)
- bot.run_pipeline wrapped in try/finally that releases token via
  Redis DECR when token_held and not token_confirmed (CLAUDE.md RULE 3)
- Confirmed tokens are never released"
```

---

## Task 10: Recording callbacks + outbound `/start` endpoint

**Owner:** voice-agent-engineer
**Files:**
- Modify: `agent/server.py`
- Create: `tests/integration/test_server_recording_and_start.py`

`/recording-finished` (POST) accepts the Vobiz callback metadata, logs structured event, returns 200. `/recording-ready` (POST) accepts `{"recording_url": "..."}`, downloads the MP3 to `agent/recordings/{call_id}.mp3` using aiohttp + the Vobiz auth headers. `/start` (POST) accepts `{"to": "+91..."}`, places an outbound call via Vobiz Partner API. All three are gated by `RECORDING_ENABLED` (the recording two) or available always (`/start`).

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_server_recording_and_start.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_auth_id", "AID")
    monkeypatch.setattr("backend.config.settings.vobiz_auth_token", "ATK")
    from agent.server import app
    return TestClient(app)

def test_recording_finished_logs_and_200s(client):
    r = client.post("/recording-finished", data={"CallSid": "abc", "duration": "12"})
    assert r.status_code == 200

def test_recording_ready_downloads_mp3(client, tmp_path, monkeypatch):
    # mock aiohttp download to write a sentinel file
    ...

def test_start_returns_call_id(client, monkeypatch):
    # mock aiohttp POST to Vobiz API
    ...
```

- [ ] **Step 2: Implement endpoints, run tests, GREEN, commit.**

```
git add agent/server.py tests/integration/test_server_recording_and_start.py
git commit -m "feat(agent): recording callbacks + outbound /start endpoint"
```

---

## Task 11: Dockerfile rewrite for FastAPI agent

**Owner:** devops-engineer
**Files:**
- Modify: `infra/Dockerfile.agent`
- Create: `tests/unit/test_dockerfile_lint.py`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY agent/requirements.txt /app/agent/requirements.txt
RUN pip install --no-cache-dir -r /app/agent/requirements.txt

COPY agent/ /app/agent/
COPY backend/ /app/backend/

ENV PYTHONUNBUFFERED=1
EXPOSE 7860

CMD ["uvicorn", "agent.server:app", "--host", "0.0.0.0", "--port", "7860"]
```

- [ ] **Step 1: Write test that lints Dockerfile** (e.g. asserts `EXPOSE 7860` present, no `livekit-agents` in any COPY/RUN, base is `python:3.12-slim`).

- [ ] **Step 2: Implement, run, GREEN, commit.**

```
git add infra/Dockerfile.agent tests/unit/test_dockerfile_lint.py
git commit -m "build(infra): Dockerfile.agent for FastAPI + Pipecat on port 7860"
```

---

## Task 12: Cloudflare Tunnel setup (Vinay manual + docs)

**Owner:** devops-engineer (writes docs); Vinay runs the commands
**Files:**
- Create: `docs/runbooks/cloudflare-tunnel-setup.md`

Runbook with exact commands:
1. Install: `winget install Cloudflare.cloudflared`
2. Login: `cloudflared tunnel login` (browser auth)
3. Create: `cloudflared tunnel create vachanam-agent` (saves credentials JSON)
4. DNS: `cloudflared tunnel route dns vachanam-agent agent-dev.vachanam.in`
5. Config file `~/.cloudflared/config.yml`:
   ```yaml
   tunnel: vachanam-agent
   credentials-file: C:\Users\vinay\.cloudflared\<TUNNEL_ID>.json
   ingress:
     - hostname: agent-dev.vachanam.in
       service: http://localhost:7860
     - service: http_status:404
   ```
6. Run: `cloudflared tunnel run vachanam-agent`
7. Verify: `curl https://agent-dev.vachanam.in/health` returns `{"status":"ok"}` (after Task 5)

- [ ] **Step 1: devops-engineer writes the runbook**
- [ ] **Step 2: Vinay executes steps 1-6 and reports success**
- [ ] **Step 3: Commit runbook**

```
git add docs/runbooks/cloudflare-tunnel-setup.md
git commit -m "docs(runbooks): Cloudflare Tunnel setup for vachanam-agent dev URL"
```

---

## Task 13: Vobiz Console manual configuration (Vinay)

**Owner:** Vinay (manual)
**No code changes**

Steps:
1. Vobiz Console → Applications → New Application
2. Name: `vachanam-dev`
3. Voice URL (Answer URL): `https://agent-dev.vachanam.in/answer`
4. Voice Method: `POST`
5. Save Application
6. Vobiz Console → Phone Numbers → `+918046733493` → Edit
7. Voice → Application → select `vachanam-dev`
8. Save

- [ ] **Step 1: Vinay completes Vobiz Console steps**
- [ ] **Step 2: Vinay reports back with screenshot or text confirmation**

---

## Task 14: Smoke test — first real inbound call

**Owner:** Vinay (manual call) + voice-agent-engineer (review)

- [ ] **Step 1: Start server**
  ```
  uvicorn agent.server:app --host 0.0.0.0 --port 7860
  ```
- [ ] **Step 2: Start tunnel** (separate terminal)
  ```
  cloudflared tunnel run vachanam-agent
  ```
- [ ] **Step 3: Verify reachable**
  ```
  curl https://agent-dev.vachanam.in/health
  ```
  Expected: `{"status":"ok"}`
- [ ] **Step 4: Vinay dials `+918046733493` from his personal phone**
- [ ] **Step 5: Listen to Telugu greeting, including recording-consent disclosure**
- [ ] **Step 6: Speak a complaint, follow the booking flow to confirmation**
- [ ] **Step 7: Hang up**
- [ ] **Step 8: Verify recording MP3 saved to `agent/recordings/{call_sid}.mp3`**
- [ ] **Step 9: Verify `audit_log` has a `booking.confirmed` row**
  ```sql
  SELECT * FROM audit_log WHERE action = 'booking.confirmed' ORDER BY created_at DESC LIMIT 1;
  ```
- [ ] **Step 10: Play recording back. Vinay's audible sign-off on:**
  - Telugu greeting quality
  - Barge-in feel (cut off the AI mid-sentence; should stop instantly)
  - First-word latency on pickup
  - Booking flow correctness
- [ ] **Step 11: Decision: keep recording-on for further tuning OR flip `RECORDING_ENABLED=false` and proceed.**

Acceptance: one call answered, one booking row, one playable recording, one signed-off-on quality bar.

---

## Final review

After all 14 tasks: dispatch one final code reviewer (`general-purpose` subagent with `requesting-code-review` template) over the full branch diff. Address Critical/Important findings before declaring Phase 1 first-call milestone complete.

---

## Tech-debt entries to append to `docs/TECH_DEBT.md` at sprint close

1. **TD-PIPECAT-01: Recording policy/code mismatch** — Privacy Policy + ToS + DPA say "no voice recording" but `RECORDING_ENABLED=true` for testing. Must reconcile before first paying clinic by either (a) reverting override, (b) rewriting policy. Severity: HIGH.
2. **TD-PIPECAT-02: 4-min Solo cap not enforced** — `MAX_CALL_DURATION_SECONDS=0` (unlimited) in dev. Must wire `asyncio.wait_for(PipelineRunner.run, settings.max_call_duration_seconds)` at Phase 4 onboarding when first Solo clinic activates. Severity: MEDIUM.
3. **TD-PIPECAT-03: Calendar + WhatsApp stubs** — `CalendarService` returns fake event IDs, `MetaService` is no-op. Real Google Calendar at Phase 4, real Meta Cloud API at MVP2. Severity: MEDIUM (booking flow incomplete without these for paying clinics).
4. **TD-PIPECAT-04: Recording cleanup script** — `agent/recordings/` grows unbounded. Add a scheduled cleanup once retention policy is decided. Severity: LOW.
5. **TD-PIPECAT-05: Sarvam STT keepalive auto-reconnect** — Pipecat issue #3699 (Sarvam STT WebSocket dies on long silence). Wire `keepalive_interval=5.0` in Task 6; add auto-reconnect handler if silence-death recurs in real calls. Severity: MEDIUM.
6. **TD-PIPECAT-06: Vobiz `<Dial>` mid-call transfer semantics** — Confirmed via one probe call in Task 8 TDD; if it turns out `<Dial>` is initial-answer-only and not mid-call, replace with Vobiz `/initiate-transfer` REST API + WebSocket close. Severity: HIGH if emergency path breaks.

Links: [[project-vachanam-status]] [[feedback-no-voice-recording]] [[feedback-emergency-transfer]] [[feedback-token-efficiency]] [[feedback-no-procrastination]]
