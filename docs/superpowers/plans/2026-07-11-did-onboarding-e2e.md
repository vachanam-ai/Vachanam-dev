# New-DID / Clinic Telephony Onboarding — End-to-End Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "clinic buys a Vobiz number → agent answers on it, and outbound calls show the clinic's own caller ID" a repeatable process: a manual runbook for the steps that CANNOT be code (Vobiz portal, KYC), plus automation (TD-026) for everything that can — outbound-trunk provisioning from stored sub-account credentials and a preflight endpoint that reports wiring status.

**Architecture:** All DB columns already exist (`branches.did_number`, `vobiz_subaccount_id`, `vobiz_sip_username`, `vobiz_sip_password_enc`, `vobiz_sip_domain`, `outbound_trunk_id` — see `backend/models/schema.py:86-98`). Inbound wiring is already automatic (`sync_did_to_inbound_trunk` on DID save). The gap: outbound trunk creation is a manual script (`scripts/create_vobiz_outbound_trunk.py`), and nothing reports whether a branch is fully wired. This plan moves the script's logic into `backend/services/livekit_sip.py`, exposes it as a POST endpoint, adds a GET preflight endpoint, and a small Settings card.

**Tech Stack:** FastAPI (async), SQLAlchemy 2.x async, LiveKit `livekit-api` SDK, Fernet crypto (`backend/services/crypto.py`), React 18 + TanStack Query (frontend), pytest + pytest-asyncio.

## Global Constraints

- **RULE 1 (tenant isolation):** every endpoint scoped by `assert_branch_access`; role gate `org_admin` exactly like existing telephony endpoints (`backend/routers/branches.py:600,629`).
- **RULE 5:** branch context comes from the DIALED number, never the caller's. Do not touch branch-resolution logic.
- **RULE 8 (graceful external failure):** LiveKit API failures return `{"ok": False, "detail": ...}`, never raise out of the service layer; endpoints surface them as structured responses, not 500s.
- **RULE 9 (PII/secret discipline):** SIP password decrypted ONLY in memory at provision time; NEVER logged, NEVER returned by any endpoint; log phone numbers as last-4 only (`did[-4:]`).
- **No new dependencies. No DB migration** (all columns exist).
- **FIXLOG ritual:** finished work gets a row in `docs/FIXLOG.md` + regression tests; run full suite (`python -m pytest tests/unit tests/integration -q`) — must stay green (724 passed, 2 skipped as of 2026-07-11).
- Conventional commits (`feat:`, `test:`, `docs:`).
- Secrets from env/config only; never commit `.env`.

---

## Part A — Manual Runbook (no code; save as docs, keep with plan)

These steps are inherently external. The implementer's only job for Part A is Task 4 (write them into `docs/GO_LIVE.md`).

### A1. Vobiz portal (per new clinic)
1. Complete/verify KYC on the (sub-)account — **inbound routing stays dead on unverified accounts**.
2. Buy the DID (local to clinic's city at Phase-4 onboarding; see memory `project-vobiz-region-test`).
3. Point the DID's inbound destination (origination) to the LiveKit project SIP URI (LiveKit dashboard → Telephony → shown as `sip:<project>.sip.livekit.cloud`). Same URI for every DID.
4. For per-clinic outbound (caller ID = clinic's own number): create a Vobiz **sub-account**; note its SIP domain, SIP username (Auth ID), SIP password (Auth Token).

### A2. Vachanam side (after automation below is built — all in dashboard/API)
1. Settings → paste DID into the branch's DID field → Save. (Backend normalizes E.164, rejects cross-clinic duplicates, auto-adds to LiveKit inbound trunk — already built, `backend/routers/branches.py:722-766`.)
2. PATCH `/branches/{id}/telephony` with the sub-account credentials (password encrypted at rest — already built, `branches.py:610-659`).
3. POST `/branches/{id}/telephony/provision-trunk` (Task 1) → creates the LiveKit outbound trunk, stores its id on the branch.
4. GET `/branches/{id}/telephony/preflight` (Task 2) → all checks green.
5. Test call in: dial DID → agent answers with THIS clinic's greeting.
6. Test call out: trigger a reminder (`scripts/_fire_test_reminder.py`) → patient's phone shows the clinic's DID as caller ID.

---

## Part B — Automation Tasks

### Task 1: Outbound-trunk provisioning service + endpoint

**Files:**
- Modify: `backend/services/livekit_sip.py` (append function)
- Modify: `backend/routers/branches.py` (append endpoint after `update_branch_telephony`, i.e. after line ~659)
- Test: `tests/unit/test_provision_trunk.py` (new)

**Interfaces:**
- Produces: `async def create_outbound_trunk_for_branch(branch) -> dict` returning `{"ok": bool, "trunk_id": str | None, "detail": str}`; endpoint `POST /branches/{branch_id}/telephony/provision-trunk` returning `TelephonySettings` (existing model, `branches.py:567`) with `outbound_trunk_id` filled on success, or HTTP 400/409 with detail.
- Consumes: `decrypt_secret(token) -> str` from `backend/services/crypto.py:51`; `TelephonySettings` + `_telephony_payload(branch)` from `branches.py:567-584`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_provision_trunk.py
"""TD-026: outbound-trunk provisioning from stored sub-account credentials.

Contracts:
  * missing credentials -> ok=False, nothing created
  * complete credentials -> trunk created with decrypted password, id returned
  * LiveKit failure -> ok=False detail, never raises (RULE 8)
  * SIP password never appears in the returned dict (RULE 9)
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import livekit_sip as ls
from backend.services.crypto import encrypt_secret


def _branch(**over):
    base = dict(
        did_number="+918012345678",
        vobiz_sip_domain="sub.vobiz.example",
        vobiz_sip_username="SA_TEST1",
        vobiz_sip_password_enc=encrypt_secret("s3cret"),
        outbound_trunk_id=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_missing_creds_refused():
    res = await ls.create_outbound_trunk_for_branch(_branch(vobiz_sip_domain=None))
    assert res["ok"] is False
    assert res["trunk_id"] is None
    assert "credential" in res["detail"].lower() or "missing" in res["detail"].lower()


@pytest.mark.asyncio
async def test_creates_trunk_with_decrypted_password(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s")

    captured = {}

    class FakeSip:
        async def create_sip_outbound_trunk(self, req):
            captured["trunk"] = req.trunk
            return SimpleNamespace(sip_trunk_id="ST_new123")

    fake_api = SimpleNamespace(sip=FakeSip(), aclose=AsyncMock())
    with patch("livekit.api.LiveKitAPI", return_value=fake_api):
        res = await ls.create_outbound_trunk_for_branch(_branch())

    assert res == {"ok": True, "trunk_id": "ST_new123", "detail": "created"}
    assert captured["trunk"].auth_password == "s3cret"      # decrypted in memory
    assert captured["trunk"].numbers == ["+918012345678"]   # caller ID = clinic DID
    assert captured["trunk"].auth_username == "SA_TEST1"


@pytest.mark.asyncio
async def test_livekit_failure_never_raises(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s")

    class FakeSip:
        async def create_sip_outbound_trunk(self, req):
            raise RuntimeError("livekit boom")

    fake_api = SimpleNamespace(sip=FakeSip(), aclose=AsyncMock())
    with patch("livekit.api.LiveKitAPI", return_value=fake_api):
        res = await ls.create_outbound_trunk_for_branch(_branch())
    assert res["ok"] is False
    assert "boom" in res["detail"]
    assert "s3cret" not in str(res)  # RULE 9
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/unit/test_provision_trunk.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'create_outbound_trunk_for_branch'`

- [ ] **Step 3: Implement the service function**

Append to `backend/services/livekit_sip.py`:

```python
async def create_outbound_trunk_for_branch(branch) -> dict:
    """Create a LiveKit OUTBOUND trunk that authenticates to this branch's
    Vobiz sub-account (TD-026 — replaces scripts/create_vobiz_outbound_trunk.py
    for the per-clinic path). Caller stores the returned trunk_id on the branch.

    Returns {"ok": bool, "trunk_id": str | None, "detail": str}. Never raises
    (RULE 8). The SIP password is decrypted only in memory here (RULE 9).
    """
    did = getattr(branch, "did_number", None)
    domain = getattr(branch, "vobiz_sip_domain", None)
    username = getattr(branch, "vobiz_sip_username", None)
    password_enc = getattr(branch, "vobiz_sip_password_enc", None)
    missing = [n for n, v in (
        ("did_number", did), ("vobiz_sip_domain", domain),
        ("vobiz_sip_username", username), ("sip_password", password_enc),
    ) if not v]
    if missing:
        return {"ok": False, "trunk_id": None,
                "detail": f"missing credentials: {', '.join(missing)}"}
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY")):
        return {"ok": False, "trunk_id": None,
                "detail": "LiveKit credentials not configured on this server"}

    try:
        from livekit import api as lk_api

        from backend.services.crypto import decrypt_secret

        lkapi = lk_api.LiveKitAPI()
        try:
            trunk = lk_api.SIPOutboundTrunkInfo(
                name=f"vobiz-{username}",
                address=domain.strip(),
                numbers=[did],
                auth_username=username.strip(),
                auth_password=decrypt_secret(password_enc),
            )
            res = await lkapi.sip.create_sip_outbound_trunk(
                lk_api.CreateSIPOutboundTrunkRequest(trunk=trunk)
            )
            logger.info("outbound_trunk_created", did=did[-4:],
                        trunk_id=res.sip_trunk_id)
            return {"ok": True, "trunk_id": res.sip_trunk_id, "detail": "created"}
        finally:
            await lkapi.aclose()
    except Exception as e:  # noqa: BLE001 — RULE 8, report not raise
        logger.error("outbound_trunk_create_failed", did=did[-4:], error=str(e)[:200])
        return {"ok": False, "trunk_id": None, "detail": str(e)[:200]}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/unit/test_provision_trunk.py -q`
Expected: 3 passed

- [ ] **Step 5: Add the endpoint**

Append to `backend/routers/branches.py` directly after `update_branch_telephony` (after line ~659), same section:

```python
@router.post(
    "/{branch_id}/telephony/provision-trunk",
    response_model=TelephonySettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.trunk_provisioned", resource_type="branch")
async def provision_outbound_trunk(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelephonySettings:
    """Create the per-clinic LiveKit outbound trunk from the stored Vobiz
    sub-account credentials (TD-026). Idempotent: a branch that already has an
    outbound_trunk_id is returned unchanged (delete the field via PATCH first
    to re-provision). org_admin only."""
    from backend.services.livekit_sip import create_outbound_trunk_for_branch

    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can provision telephony")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    if branch.outbound_trunk_id:
        return _telephony_payload(branch)  # idempotent no-op

    res = await create_outbound_trunk_for_branch(branch)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["detail"])

    branch.outbound_trunk_id = res["trunk_id"]
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("branch_trunk_provisioned", branch_id=branch_id, trunk_id=res["trunk_id"])
    return _telephony_payload(branch)
```

- [ ] **Step 6: Endpoint tests** — append to `tests/unit/test_provision_trunk.py`. Follow the existing endpoint-test pattern in `tests/integration/test_branch_telephony.py` if present (Grep for `provision` / `telephony` under `tests/`); assert: 403 for non-org_admin, idempotent no-op when `outbound_trunk_id` set, 400 with detail when service returns not-ok, trunk id persisted on success. Mock `create_outbound_trunk_for_branch` with `AsyncMock(return_value={"ok": True, "trunk_id": "ST_x", "detail": "created"})` — the LiveKit path is already covered by the service tests.

- [ ] **Step 7: Run + commit**

Run: `python -m pytest tests/unit/test_provision_trunk.py tests/integration -q` — all green.

```bash
git add backend/services/livekit_sip.py backend/routers/branches.py tests/unit/test_provision_trunk.py
git commit -m "feat(telephony): provision per-clinic outbound trunk from stored sub-account creds (TD-026)"
```

### Task 2: Telephony preflight endpoint

**Files:**
- Modify: `backend/routers/branches.py` (append after Task 1's endpoint)
- Modify: `backend/services/livekit_sip.py` (append read-only check)
- Test: `tests/unit/test_telephony_preflight.py` (new)

**Interfaces:**
- Produces: `GET /branches/{branch_id}/telephony/preflight` → `{"checks": [{"id": str, "label": str, "ok": bool, "detail": str}], "all_ok": bool}`. Check ids, in order: `did_saved`, `did_on_inbound_trunk`, `subaccount_creds`, `outbound_trunk`.
- Consumes: `async def is_did_on_inbound_trunk(did_number: str) -> dict` (new, `{"ok": bool, "detail": str}` — same shape as `sync_did_to_inbound_trunk` but read-only, list + membership test, no update call).

- [ ] **Step 1: failing tests** — new `tests/unit/test_telephony_preflight.py`: (a) branch with nothing set → all four checks `ok: False`, `all_ok: False`; (b) fully wired branch (did set, LiveKit check mocked ok, creds set, trunk id set) → `all_ok: True`; (c) LiveKit unreachable → `did_on_inbound_trunk` check `ok: False` with detail, endpoint still 200 (RULE 8 — preflight must work when the thing it checks is down); (d) 403 for role `staff`.
- [ ] **Step 2: implement `is_did_on_inbound_trunk`** — copy the list/read portion of `sync_did_to_inbound_trunk` (`livekit_sip.py:34-42`), return `{"ok": did in numbers, "detail": ...}`, never raise.
- [ ] **Step 3: implement the endpoint** — org_admin gate identical to Task 1; build the four checks:
  1. `did_saved`: `bool(branch.did_number)`
  2. `did_on_inbound_trunk`: skip (ok=False, "no DID saved") if no DID, else `await is_did_on_inbound_trunk(branch.did_number)`
  3. `subaccount_creds`: all of `vobiz_sip_domain`, `vobiz_sip_username`, `vobiz_sip_password_enc` present (detail names what's missing)
  4. `outbound_trunk`: `bool(branch.outbound_trunk_id)` (detail: "using global trunk — caller ID will be the shared number" when False; this is a WARNING state, acceptable for pilot)
  `all_ok = checks 1-2 ok` AND (`3-4 ok` OR both intentionally empty — a clinic on the global trunk is valid; put `all_ok = c1.ok and c2.ok` and expose 3/4 as informational. Keep exactly this rule and document it in the response model docstring.)
- [ ] **Step 4: run, commit** — `git commit -m "feat(telephony): preflight wiring checklist endpoint"`

### Task 3: Settings UI — wiring checklist card

**Files:**
- Modify: `frontend/src/api/client.js` (add `fetchTelephonyPreflight = (branchId) => api.get(...)` and `provisionTrunk = (branchId) => api.post(...)`)
- Modify: `frontend/src/pages/Settings.jsx` (new card below the existing DID section, ~line 460)
- Verify: `cd frontend && npm run build` passes (no frontend test framework in repo — build IS the gate)

- [ ] **Step 1:** API client functions (mirror the existing patterns in `client.js`).
- [ ] **Step 2:** `TelephonyChecklist` component in `Settings.jsx`: `useQuery` on preflight (refetch on window focus only — no polling); render the four checks as rows with green check / amber dash / red cross + `detail` text; if `subaccount_creds` ok AND `outbound_trunk` not ok, show a "Provision outbound trunk" button → `useMutation(provisionTrunk)` → invalidate preflight query on success, toast the error detail on failure. Visible to org_admin only (same conditional the existing telephony-adjacent UI uses; check how Settings gates owner-only sections and reuse it).
- [ ] **Step 3:** `npm run build` green. Commit `feat(settings): telephony wiring checklist + provision button`.

### Task 4: Runbook into docs + FIXLOG

**Files:**
- Modify: `docs/GO_LIVE.md` (add/replace a "New DID onboarding" section with Part A verbatim, updated to reference the new endpoints)
- Modify: `docs/TECH_DEBT.md` (close/annotate TD-026: provisioning automated; Vobiz sub-account CREATION still manual in portal — that part has no public API)
- Modify: `docs/FIXLOG.md` (one row: TD-026 provisioning + preflight, listing the regression tests)

- [ ] **Step 1:** docs edits above.
- [ ] **Step 2:** full suite `python -m pytest tests/unit tests/integration -q` — green (baseline 724 passed, 2 skipped).
- [ ] **Step 3:** commit `docs(telephony): DID onboarding runbook, TD-026 closure, FIXLOG row`.

---

## Explicitly OUT of scope (do not build)

- Vobiz sub-account auto-creation / DID purchase via API — Vobiz exposes no usable public API for this; stays manual in the portal.
- Auto-pointing the DID at the LiveKit SIP URI — same reason (documented as manual step A1.3).
- Retiring the global outbound trunk fallback — `backend/services/telephony.py:49-52` fallback chain stays; clinics without a sub-account keep working on the shared caller ID.
- Deleting `scripts/create_vobiz_outbound_trunk.py` — keep as ops escape hatch; add a comment pointing to the new endpoint.

## Verification (end-to-end, after implementation)

1. Full suite green.
2. Staging/prod smoke with a real spare DID: runbook A1 → A2 steps 1-4 all through the dashboard, preflight all green.
3. Inbound test call → correct clinic greeting (RULE 5).
4. Outbound test reminder → patient handset shows the clinic's DID as caller ID (the actual TD-026 acceptance criterion).
5. RULE 1 check: second clinic's org_admin gets 403/404 on the first clinic's preflight + provision endpoints (covered by tests, spot-check in staging).
