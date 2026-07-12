"""Attack-surface sweep — one regression test per OWASP category, mapped to
Vachanam's real endpoints. Companion to the IDOR wall (test_cross_tenant_idor)
and JWT lifecycle (test_jwt); this file covers the categories those two don't:
input-boundary injection, mass-assignment / privilege fields, resource limits,
JWT algorithm confusion, and the "APIs never return HTML" rule.

Taxonomy (OWASP Web Top 10 2021 + API Security Top 10 2023) → coverage:
  A01 Broken Access Control / API1 BOLA ...... test_cross_tenant_idor.py (wall)
  A02 Cryptographic Failures ................. test_crypto_prod_key, test_secrets_not_in_repo
  A03 Injection .............................. HERE: junk-enum 422, uuid-typed path (no raw SQL)
  A04 Resource Consumption / API4 ............ HERE: bounded fields; test_rate_limit* (throttle)
  A05 Security Misconfiguration .............. test_headers, test_cors; HERE: no-HTML rule
  API3 BOPLA / Mass Assignment ............... HERE: register ignores privilege fields
  A07 Auth Failures .......................... test_jwt; HERE: alg=none confusion
  A08 Integrity / webhook signatures ......... test_payments_* (Razorpay HMAC)
  A09 Logging/Monitoring ..................... test_audit_log
  A10 SSRF / API8 ............................ N/A: no endpoint fetches a client-supplied
                                               URL. Every outbound httpx target (Razorpay,
                                               Google, Sarvam/smallest, Vobiz, Turnstile) is a
                                               fixed provider host from config, never request
                                               input. Re-verify if a webhook-URL field is ever
                                               added.
"""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt
from pydantic import ValidationError

from backend.config import settings


def _jwt(branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "sweep@t.test", "role": "org_admin",
            "org_id": str(uuid.uuid4()), "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm="HS256",
    )


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ── A03 Injection: bad enum is a clean 422, never a 500 through the DB enum ──

@pytest.mark.asyncio
async def test_register_rejects_junk_plan_with_422(client):
    r = await client.post("/auth/register", json={
        "clinic_name": "X Clinic", "owner_name": "Owner",
        "email": "a@b.com", "password": "Sup3r$ecret!", "plan": "enterprise",
    })
    # Must reject at the boundary (422) — never reach the DB enum (500) or persist.
    assert r.status_code == 422, f"junk plan should 422, got {r.status_code}: {r.text}"


def test_register_model_validates_plan():
    from backend.routers.auth import RegisterRequest

    base = dict(clinic_name="C", owner_name="O", email="a@b.com", password="x")
    for good in ("solo", "clinic", "multi"):
        assert RegisterRequest(**base, plan=good).plan == good
    with pytest.raises(ValidationError):
        RegisterRequest(**base, plan="enterprise")


# ── A03 Injection: path ids are uuid-typed → a SQLi string can't reach SQL ──

@pytest.mark.asyncio
async def test_sqli_in_branch_path_is_rejected_before_sql(client):
    payload = "1'; DROP TABLE tokens;--"
    tok = _jwt(str(uuid.uuid4()))
    r = await client.get(f"/queue/{payload}/today",
                         headers={"Authorization": f"Bearer {tok}"})
    # uuid path-coercion rejects the string before any query runs. Never 200
    # (would mean it hit the handler), never 500 (would mean it hit SQL).
    assert r.status_code in (400, 422), f"SQLi branch id should be rejected, got {r.status_code}"


# ── API3 BOPLA / Mass Assignment: register can't set privileged fields ──────

def test_register_ignores_privilege_fields():
    """An attacker POSTing role/is_admin/status/org_id must not be able to set
    them — the model has no such fields, so Pydantic drops them. Role is
    hardcoded 'org_admin' in the handler; there is no wire path to super_admin."""
    from backend.routers.auth import RegisterRequest

    m = RegisterRequest(
        clinic_name="C", owner_name="O", email="a@b.com", password="x",
        role="super_admin", is_admin=True, status="active", org_id=str(uuid.uuid4()),
    )
    for forbidden in ("role", "is_admin", "status", "org_id"):
        assert not hasattr(m, forbidden), f"mass-assignment: {forbidden} bound on model"


# ── A04 Resource Consumption: bounded input fields reject oversize / range ──

def test_patient_edit_rejects_oversize_and_out_of_range():
    from backend.routers.patients import PatientEdit

    bid = uuid.uuid4()
    with pytest.raises(ValidationError):
        PatientEdit(branch_id=bid, name="A" * 5000)   # > max_length 255
    with pytest.raises(ValidationError):
        PatientEdit(branch_id=bid, age=999)            # > le 120
    with pytest.raises(ValidationError):
        PatientEdit(branch_id=bid, age=-1)             # < ge 0


# ── A07 Auth: JWT algorithm confusion (alg=none) must be rejected ───────────

@pytest.mark.asyncio
async def test_jwt_alg_none_rejected(client):
    """Classic bypass: forge an unsigned token with header alg=none. The
    middleware pins algorithms=['HS256'], so jose rejects it → 401."""
    def _b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    branch = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    header = _b64({"alg": "none", "typ": "JWT"})
    claims = _b64({
        "sub": str(uuid.uuid4()), "email": "e@e.com", "role": "super_admin",
        "org_id": None, "branch_ids": [branch], "is_admin": True,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=8)).timestamp()),
        "jti": str(uuid.uuid4()),
    })
    forged = f"{header}.{claims}."  # empty signature
    r = await client.get(f"/queue/{branch}/today",
                         headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code in (401, 403), f"alg=none accepted! got {r.status_code}"


# ── A05 / hard rule: APIs return JSON, never HTML (no template/XSS surface) ──

@pytest.mark.asyncio
async def test_api_never_returns_html(client):
    # Unknown route → JSON 404, not an HTML error page.
    r = await client.get("/no/such/route/" + uuid.uuid4().hex)
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")
    assert not r.text.lstrip().lower().startswith("<!doctype")
    assert not r.text.lstrip().lower().startswith("<html")

    # Protected route without auth → JSON error, not HTML.
    r = await client.get(f"/queue/{uuid.uuid4()}/today")
    assert r.status_code in (401, 403)
    assert "text/html" not in r.headers.get("content-type", "")
