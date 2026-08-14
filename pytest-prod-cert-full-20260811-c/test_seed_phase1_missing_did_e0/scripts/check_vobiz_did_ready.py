"""Vobiz DID onboarding pre-flight (TD-036).

The June-06 inbound failure ("you are not allowed to dial this number") cost
hours because all three root causes were Vobiz-upstream gates invisible from
our side: account is_verified=false, DID provider="", and a recycled number.
This check makes each one loud BEFORE a clinic's DID goes live.

Usage:
    python scripts/check_vobiz_did_ready.py [--did 91XXXXXXXXXX]

Checks (read-only GETs; exits non-zero on the first hard failure):
  1. Account KYC:   GET /Account/{auth_id}         → is_verified must be true
  2. DID health:    GET /Account/{auth_id}/Number/ → DID present, provider != "",
                    usage_status not empty/disabled
  3. Recycled DID:  released/renewal metadata, when exposed, must be >72h old
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, ".")

from backend.config import settings  # noqa: E402


def _client() -> tuple[str, dict, str]:
    auth_id = settings.vobiz_auth_id
    token = settings.vobiz_auth_token
    if not (auth_id and token):
        print("FAIL: VOBIZ_AUTH_ID / VOBIZ_AUTH_TOKEN not set in .env")
        raise SystemExit(2)
    base = getattr(settings, "vobiz_api_base", "https://api.vobiz.ai/api/v1")
    return base, {"X-Auth-ID": auth_id, "X-Auth-Token": token}, auth_id


def check(did: str | None = None) -> int:
    base, headers, auth_id = _client()
    failures = 0

    with httpx.Client(timeout=20) as c:
        # 1 — account KYC
        r = c.get(f"{base}/Account/{auth_id}", headers=headers)
        if r.status_code != 200:
            print(f"FAIL [account]: HTTP {r.status_code} — cannot read account")
            return 2
        acct = r.json()
        verified = acct.get("is_verified") or acct.get("verified")
        if verified is True or str(verified).lower() == "true":
            print("OK   [kyc]: account is_verified=true")
        else:
            print("FAIL [kyc]: account is_verified is NOT true — inbound calls "
                  "will be rejected upstream. Complete Vobiz KYC first.")
            failures += 1

        # 2 — DID presence + provider + usage_status
        r = c.get(f"{base}/Account/{auth_id}/Number/", headers=headers)
        if r.status_code == 401:
            # Baselined 2026-07-12: the account token passes /Account/ (KYC
            # check) but 401s on /Number/ — number management needs the PARTNER
            # credentials. Retry with them when configured.
            pid = getattr(settings, "vobiz_partner_auth_id", "") or ""
            ptok = getattr(settings, "vobiz_partner_auth_token", "") or ""
            if pid and ptok:
                headers = {"X-Auth-ID": pid, "X-Auth-Token": ptok}
                r = c.get(f"{base}/Account/{auth_id}/Number/", headers=headers)
        if r.status_code != 200:
            print(f"FAIL [numbers]: HTTP {r.status_code} — cannot list DIDs. "
                  "The account token lacks Number scope; set VOBIZ_PARTNER_AUTH_ID/"
                  "TOKEN in .env (they live in the Fly secrets) and re-run.")
            return 2
        nums = r.json()
        objects = nums.get("objects") or nums.get("numbers") or nums.get("data") or []
        want = "".join(ch for ch in (did or "") if ch.isdigit())
        matched = [
            o for o in objects
            if not want or want in "".join(ch for ch in str(o.get("number", "")) if ch.isdigit())
        ]
        if not matched:
            print(f"FAIL [did]: {'DID ' + did if did else 'no DIDs'} not found on the account")
            return 2
        for o in matched:
            n = o.get("number")
            provider = o.get("provider") or ""
            usage = o.get("usage_status") or o.get("status") or ""
            if not provider:
                print(f"FAIL [did {n}]: provider is EMPTY — number not routed "
                      "upstream yet (the June-06 silent killer). Ask Vobiz support.")
                failures += 1
            else:
                print(f"OK   [did {n}]: provider={provider}")
            if usage and str(usage).lower() in ("disabled", "inactive", "suspended"):
                print(f"FAIL [did {n}]: usage_status={usage}")
                failures += 1
            else:
                print(f"OK   [did {n}]: usage_status={usage or '(not exposed)'}")

            # 3 — recycled-number check, where the API exposes it
            released = o.get("released_at") or o.get("released")
            if released:
                try:
                    rel = datetime.fromisoformat(str(released).replace("Z", "+00:00"))
                    if rel.tzinfo is None:
                        rel = rel.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - rel < timedelta(hours=72):
                        print(f"FAIL [did {n}]: released {released} (<72h ago) — "
                              "recycled number may still be propagating upstream")
                        failures += 1
                    else:
                        print(f"OK   [did {n}]: last release {released} (>72h)")
                except ValueError:
                    print(f"WARN [did {n}]: unparseable released_at={released}")
            else:
                print(f"OK   [did {n}]: no recent release recorded")

    print("—" * 40)
    print("READY: all pre-flight checks passed" if failures == 0
          else f"NOT READY: {failures} failing check(s) — fix before onboarding")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--did", help="specific DID to check (default: all on the account)")
    raise SystemExit(check(ap.parse_args().did))
