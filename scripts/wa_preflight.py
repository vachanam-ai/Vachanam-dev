"""Verify the five Tech Provider settings before any clinic runs Embedded Signup.

`GET /branches/{id}/whatsapp/signup-config` only reports whether the five values
are non-empty. That is not the same as correct: a wrong app secret, a webhook
Meta never verified, or a missing field subscription all pass that check and
then fail inside a real clinic's popup with an opaque Meta error.

This asks Meta and our own webhook instead:

    python scripts/wa_preflight.py
    python scripts/wa_preflight.py --webhook-url https://api.vachanam.in/webhooks/whatsapp

Read-only. Sends nothing, changes nothing, prints no secret. Exit 0 when the
account is ready to onboard a clinic, 1 otherwise.

ponytail: presence + Graph + webhook echo only. It cannot read Live mode or
Advanced Access (Meta exposes neither to an app token) - App Dashboard shows
both, and step 6 below tells you to look.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402

DEFAULT_WEBHOOK = "https://api.vachanam.in/webhooks/whatsapp"

# docs/runbooks/META_WHATSAPP_SETUP.md section 3. Missing any one of these silently
# drops a whole class of event: no `messages` = no patient ever reaches the bot,
# no `history`/`smb_*` = Coexistence onboarding never completes.
REQUIRED_FIELDS = {
    "messages",
    "message_template_status_update",
    "account_update",
    "history",
    "smb_app_state_sync",
    "smb_message_echoes",
}

OK, BAD = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(status: str, check: str, detail: str) -> None:
    _results.append((status, check, detail))
    print(f"  [{status}] {check}: {detail}")


def check_presence() -> bool:
    """All five must be non-empty - the same gate the signup-config endpoint uses."""
    print("\n1. Settings present")
    required = {
        "META_APP_ID": settings.meta_app_id,
        "META_APP_SECRET": settings.meta_app_secret,
        "META_CONFIG_ID": settings.meta_config_id,
        "META_WEBHOOK_VERIFY_TOKEN": settings.meta_webhook_verify_token,
        "META_GRAPH_VERSION": settings.meta_graph_version,
    }
    complete = True
    for name, value in required.items():
        if not value:
            record(BAD, name, "empty - set it in the backend secret store")
            complete = False
        elif name == "META_APP_SECRET":
            record(OK, name, f"set ({len(value)} chars, not printed)")
        elif name == "META_GRAPH_VERSION" and not value.startswith("v"):
            record(BAD, name, f"{value!r} is not a Graph version (expected e.g. v25.0)")
            complete = False
        else:
            record(OK, name, value)
    return complete


def check_app(client: httpx.Client, app_token: str) -> None:
    """A bad app secret fails here with Meta error 190 and nowhere earlier."""
    print("\n2. App identity (proves APP_ID + APP_SECRET are a real pair)")
    version = settings.meta_graph_version
    r = client.get(
        f"https://graph.facebook.com/{version}/{settings.meta_app_id}",
        params={"fields": "id,name,link", "access_token": app_token},
    )
    if r.status_code != 200:
        err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
        record(
            BAD,
            "app lookup",
            f"HTTP {r.status_code} {err.get('message', r.text[:120])}"
            + (" - app id and secret do not match" if err.get("code") == 190 else ""),
        )
        return
    body = r.json()
    record(OK, "app lookup", f"{body.get('name')} (id {body.get('id')})")


def check_subscriptions(client: httpx.Client, app_token: str) -> None:
    """Meta only lists a callback here once it has VERIFIED it, so an empty
    result means the webhook was never accepted - not merely unsubscribed."""
    print("\n3. Webhook subscription on the app")
    version = settings.meta_graph_version
    r = client.get(
        f"https://graph.facebook.com/{version}/{settings.meta_app_id}/subscriptions",
        params={"access_token": app_token},
    )
    if r.status_code != 200:
        record(BAD, "subscriptions", f"HTTP {r.status_code} {r.text[:160]}")
        return
    objects = r.json().get("data") or []
    waba = next((o for o in objects if o.get("object") == "whatsapp_business_account"), None)
    if waba is None:
        found = ", ".join(o.get("object", "?") for o in objects) or "nothing"
        record(BAD, "whatsapp_business_account", f"not subscribed (found: {found})")
        return
    record(OK, "callback_url", str(waba.get("callback_url")))
    record(OK if waba.get("active") else BAD, "active", str(waba.get("active")))

    subscribed = {f.get("name") for f in (waba.get("fields") or [])}
    missing = REQUIRED_FIELDS - subscribed
    extra = subscribed - REQUIRED_FIELDS
    if missing:
        record(BAD, "fields", f"missing {', '.join(sorted(missing))}")
    else:
        record(OK, "fields", f"all 6 required subscribed{f' (+{len(extra)} extra)' if extra else ''}")


def check_webhook_echo(client: httpx.Client, url: str) -> None:
    """End-to-end proof that the token in THIS environment is the token the
    deployed backend answers with. A local .env that disagrees with Render is
    the failure this catches."""
    print(f"\n4. Webhook verification handshake ({url})")
    challenge = str(secrets.randbelow(10**9))
    try:
        r = client.get(
            url,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": settings.meta_webhook_verify_token,
                "hub.challenge": challenge,
            },
        )
    except httpx.HTTPError as exc:
        record(BAD, "reachable", f"{type(exc).__name__}: {exc}")
        return
    if r.status_code == 200 and r.text.strip().strip('"') == challenge:
        record(OK, "handshake", "challenge echoed - this token matches the deployed backend")
    elif r.status_code == 403:
        record(BAD, "handshake", "403 - the deployed backend has a DIFFERENT verify token")
    else:
        record(BAD, "handshake", f"HTTP {r.status_code} body={r.text[:120]!r}")

    bad = client.get(
        url,
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": challenge},
    )
    record(
        OK if bad.status_code == 403 else BAD,
        "rejects wrong token",
        f"HTTP {bad.status_code}" + ("" if bad.status_code == 403 else " - expected 403"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webhook-url", default=os.getenv("WA_WEBHOOK_URL", DEFAULT_WEBHOOK))
    args = parser.parse_args()

    print("WhatsApp Tech Provider preflight")
    if not check_presence():
        print("\nStopping: fill the missing settings first (docs/runbooks/META_WHATSAPP_SETUP.md section 4).")
        return 1

    # app_id|app_secret is Meta's documented app access token. It never expires
    # and needs no user grant, which is exactly what a preflight wants.
    app_token = f"{settings.meta_app_id}|{settings.meta_app_secret}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        check_app(client, app_token)
        check_subscriptions(client, app_token)
        check_webhook_echo(client, args.webhook_url)

    failures = [c for status, c, _ in _results if status == BAD]
    print("\n" + "=" * 60)
    if failures:
        print(f"NOT READY - {len(failures)} failing: {', '.join(failures)}")
        return 1
    print("Settings verified. Still check by hand in the App Dashboard (not API-readable):")
    print("  5. Advanced Access on whatsapp_business_management + whatsapp_business_messaging")
    print("  6. App is in Live mode - an app in Development receives test webhooks only")
    print("Then run one real Coexistence and one real Cloud API signup (runbook section 8).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
