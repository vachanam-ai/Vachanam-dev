"""Send one real WhatsApp template — the go-live smoke test (WA MVP1 Task 8).

Proves the whole chain end to end before pointing any clinic at it: the
access token is valid, the sending number is the one you think it is, the
`booking_confirm` template is APPROVED on this WABA, and a message actually
lands on a phone. Uses `backend.services.wa_templates.booking_confirm` so the
payload shape can never drift from what production sends — this is not a
hand-rolled duplicate of `wa_service.send_template`, it calls the Graph API
directly with the exact same builder.

Usage:
    python scripts/wa_smoke.py <PHONE_NUMBER_ID> <TO_NUMBER>
    python scripts/wa_smoke.py <PHONE_NUMBER_ID> <TO_NUMBER> --dry-run

    <PHONE_NUMBER_ID>  the numeric Meta phone number ID of the SENDING
                       number (Graph API → GET /<WABA_ID>/phone_numbers).
                       This is NOT the phone number itself and NOT the WABA
                       ID — three different IDs, easy to mix up.
    <TO_NUMBER>        E.164, digits only, no leading + (e.g. 919000000001).
                       Must be on the WABA's allowed-recipient list until
                       the app goes Live / the WABA is verified.

Reads META_ACCESS_TOKEN from .env (same convention as wa_create_templates.py)
— never pass a token on the command line, it lands in shell history.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.wa_templates import booking_confirm  # noqa: E402

GRAPH = "https://graph.facebook.com/v21.0"


def _token() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^META_ACCESS_TOKEN=(.*)$", text, re.M)
        if m and m.group(1).strip():
            return m.group(1).strip().strip("\"'")
    tok = os.getenv("META_ACCESS_TOKEN", "").strip()
    if not tok:
        sys.exit("META_ACCESS_TOKEN is not set in .env or the environment.")
    return tok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phone_number_id", help="Meta phone number ID of the SENDER")
    ap.add_argument("to", help="recipient in E.164 digits, no leading +")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    args = ap.parse_args()

    if not args.phone_number_id.isdigit():
        sys.exit("phone_number_id must be all digits — that is the Meta ID, not the "
                  "phone number. Find it with: GET /<WABA_ID>/phone_numbers")
    to = args.to.lstrip("+")
    if not to.isdigit():
        sys.exit("to must be digits only (E.164 without the leading +), e.g. 919000000001")

    name, lang, params, buttons = booking_confirm(
        clinic="Vachanam Smoke Test", doctor="Smoke Test",
        booking_date=date.today(), appointment_time=time(10, 30),
        token_number=None, address=None, token_id="smoke-test", lang="en",
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
            "components": (
                [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
                + [
                    {
                        "type": "button", "sub_type": "quick_reply", "index": str(i),
                        "parameters": [{"type": "payload", "payload": b["id"]}],
                    }
                    for i, b in enumerate(buttons)
                ]
            ),
        },
    }

    if args.dry_run:
        import json

        print(json.dumps(payload, indent=2))
        return 0

    token = _token()
    r = httpx.post(
        f"{GRAPH}/{args.phone_number_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15,
    )
    if r.status_code >= 300:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        err = (body.get("error") or {})
        msg = err.get("message", r.text[:300])
        code = err.get("code")
        print(f"FAILED ({r.status_code}, code {code}): {msg}")
        if "does not exist" in msg.lower() or "template" in msg.lower():
            print("-> the booking_confirm template is probably not APPROVED yet on this "
                  "WABA, or it lives on a DIFFERENT WABA than this phone_number_id "
                  "(templates do not carry across WABAs — see wa_create_templates.py).")
        if code in (131030, 131047, 190):
            print("-> either the recipient is not on the WABA's allowed-recipient list "
                  "yet (unverified app), or the access token is invalid/expired.")
        return 1

    msg_id = (r.json().get("messages") or [{}])[0].get("id", "?")
    print(f"sent — message id {msg_id}")
    print("Check the recipient's phone. If nothing arrives in ~30s, the send "
          "succeeded at the API but delivery failed — check the number is real "
          "WhatsApp and (pre-Live) on the allowed-recipient list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
