"""Link a clinic's WhatsApp phone_number_id to its branch.

Inbound WhatsApp is routed by the RECEIVING number: the webhook reads
`value.metadata.phone_number_id` and looks it up against
`Branch.wa_phone_number_id` (RULE 5 — never the sender's number). Until that
row exists every message for the clinic logs `wa_unknown_receiver` and is
dropped, which looks exactly like a dead bot.

Why a script rather than the browser console:
  * super_admin is deliberately locked out of clinic data routes (RULE 1,
    DPDP), so the branch id has to come from an OWNER login while the link
    itself needs a super_admin login — two sessions, awkward to do by hand.
  * this runs once per clinic at onboarding, so it is worth doing repeatably.
  * it goes through the audited PATCH endpoint, never near the database, so the
    change is attributable in audit_log like any other admin action.

Both JWTs come from CLINIC_JWT / SUPER_JWT in .env (gitignored) when set,
otherwise from a hidden prompt. Nothing is echoed or written back. They are
short-lived SESSION tokens — clear them from .env once the link is done.

Usage:
    python scripts/wa_link_branch.py --phone-number-id 1161669197040651
    python scripts/wa_link_branch.py --phone-number-id ... --addon
    python scripts/wa_link_branch.py --phone-number-id ... --branch-id <uuid>
    python scripts/wa_link_branch.py --phone-number-id ... --api http://localhost:8000
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

import httpx

DEFAULT_API = "https://vachanam-backend.onrender.com"

# .env is gitignored, so a session token parked there never reaches the repo.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional — the hidden prompt still works
    pass


def _token(who: str, env_var: str) -> str:
    """Read an existing session JWT rather than signing in.

    /auth/login is protected by Cloudflare Turnstile in production (verified
    2026-08-03: TURNSTILE_SECRET_KEY is set on the API service), so a script
    cannot authenticate with email+password — it would get 403 captcha_failed.
    That is the CAPTCHA doing its job; we borrow the browser's session instead.

    Source order: the env var (usually via .env, which is gitignored), else a
    hidden prompt. Some terminals refuse a paste into a hidden prompt, which is
    why .env is supported at all — these are SHORT-LIVED session tokens, so
    clear them out once the link is done.

    Get the value: DevTools -> Application -> Local Storage -> the dashboard
    origin -> key `vachanam_jwt` -> copy.
    """
    tok = (os.getenv(env_var) or "").strip().strip("\"'")
    if tok:
        print(f"{who}: using {env_var} from the environment")
    else:
        print(f"\n--- paste the {who} JWT (DevTools > Application > Local "
              f"Storage > vachanam_jwt), or set {env_var} in .env ---")
        tok = getpass.getpass("token (hidden): ").strip().strip("\"'")
    if not tok or tok.count(".") != 2:
        sys.exit(
            f"{who}: that does not look like a JWT (expected three "
            f"dot-separated parts). Set {env_var} in .env or paste it."
        )
    return tok


def _branch_ids(client: httpx.Client, api: str, token: str) -> list[str]:
    r = client.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 300:
        sys.exit(f"/auth/me failed ({r.status_code}): {r.text[:200]}")
    return list(r.json().get("branch_ids") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone-number-id", required=True,
                    help="Meta phone number ID (digits, NOT the phone number)")
    ap.add_argument("--branch-id", help="skip the owner login if you already know it")
    ap.add_argument("--addon", action="store_true",
                    help="also grant the Rs1,499 WhatsApp add-on (needed for a "
                         "Lite/Starter clinic — WhatsApp is bundled only into "
                         "clinic/multi/wa, and without this every inbound "
                         "message is dropped as wa_skipped_plan)")
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()

    pnid = args.phone_number_id.strip()
    if not pnid.isdigit():
        sys.exit("--phone-number-id must be all digits — that is the Meta ID, "
                 "not the phone number. Find it with: GET /<WABA_ID>/phone_numbers")

    with httpx.Client(timeout=45, follow_redirects=True) as client:
        branch_id = args.branch_id
        if not branch_id:
            owner_token = _token("CLINIC OWNER", "CLINIC_JWT")
            ids = _branch_ids(client, args.api, owner_token)
            if not ids:
                sys.exit("that account owns no branches — wrong login?")
            if len(ids) == 1:
                branch_id = ids[0]
                print(f"branch: {branch_id}")
            else:
                for i, b in enumerate(ids):
                    print(f"  [{i}] {b}")
                branch_id = ids[int(input("which branch? ").strip())]

        admin_token = _token("SUPER ADMIN", "SUPER_JWT")
        r = client.patch(
            f"{args.api}/admin/branches/{branch_id}/whatsapp",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=({"wa_phone_number_id": pnid, "whatsapp_addon": True}
                  if args.addon else {"wa_phone_number_id": pnid}),
        )

    if r.status_code == 409:
        sys.exit("409 — that phone_number_id is already linked to another "
                 "branch. One WhatsApp number belongs to exactly one clinic; "
                 "unlink it there first.")
    if r.status_code >= 300:
        sys.exit(f"link failed ({r.status_code}): {r.text[:300]}")

    print(f"\nlinked: {r.json()}")
    print("Inbound messages to that number now resolve to this branch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
