"""Create Vachanam's required WhatsApp templates on a WABA.

Every clinic owns its own WhatsApp Business Account (spec
2026-08-02-whatsapp-tech-provider-design.md), and templates live PER WABA —
they do not carry across accounts. So this runs once per clinic at onboarding,
and once for our own pilot number.

Doing it by hand in WhatsApp Manager is a per-clinic chance to get a
name, a language code or a button count subtly wrong — and every one of those
mistakes surfaces later as an opaque "template does not exist" or parameter
mismatch at send time, usually to a real patient. Definitions are imported
from the website's template installer, so the CLI and UI cannot drift.

Usage:
    python scripts/wa_create_templates.py <WABA_ID>
    python scripts/wa_create_templates.py <WABA_ID> --dry-run

Reads META_ACCESS_TOKEN from .env (never pass a token on the command line — it
lands in shell history). Idempotent: a template that already exists is reported
and skipped, not duplicated.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.wa_template_admin import SYSTEM_TEMPLATE_DEFINITIONS

GRAPH = "https://graph.facebook.com/v21.0"

# Language MUST match what wa_templates.template_lang() sends. English only —
# clinics use English on WhatsApp (spec D5), and one approved copy per template
# beats four half-approved translations.
LANG = "en"


def _payload(spec: dict) -> dict:
    body = {
        "type": "BODY",
        "text": spec["body"],
        "example": {"body_text": [spec["examples"]]},
    }
    components = [body]
    if spec["buttons"]:
        components.append({
            "type": "BUTTONS",
            "buttons": [
                {"type": "QUICK_REPLY", "text": title}
                for title in spec["buttons"]
            ],
        })
    return {
        "name": spec["name"],
        "category": "UTILITY",
        "language": LANG,
        "components": components,
    }


TEMPLATES = [_payload(spec) for spec in SYSTEM_TEMPLATE_DEFINITIONS]


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
    ap.add_argument("waba_id")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be created, call nothing")
    args = ap.parse_args()

    if args.dry_run:
        for t in TEMPLATES:
            print(f"{t['name']:18} {t['language']:5} {t['category']}")
            print(json.dumps(t["components"], indent=2))
        return 0

    token = _token()
    url = f"{GRAPH}/{args.waba_id}/message_templates"
    failures = 0

    with httpx.Client(timeout=30) as client:
        for t in TEMPLATES:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=t,
            )
            if r.status_code < 300:
                print(f"created  {t['name']}  -> {r.json().get('id')}")
                continue
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            msg = (body.get("error") or {}).get("message", r.text[:200])
            # Re-running after a partial failure must not be scary.
            if "already exists" in msg.lower():
                print(f"exists   {t['name']}  (skipped)")
                continue
            failures += 1
            print(f"FAILED   {t['name']}: {msg}")

    if failures:
        print(f"\n{failures} template(s) failed. Fix and re-run — this is idempotent.")
        return 1
    print("\nAll templates submitted. Meta review usually takes minutes to a day;"
          " check status with:\n"
          f"  GET /{args.waba_id}/message_templates?fields=name,status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
