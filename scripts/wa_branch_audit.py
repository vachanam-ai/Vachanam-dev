"""Read-only WhatsApp readiness audit for one production clinic.

Prints no patient names, phone numbers, message bodies, or access tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal
from backend.models.schema import (
    Branch,
    FollowupTask,
    Organization,
    Token,
    WhatsAppDelivery,
)
from backend.services import wa_service, wa_template_admin, wa_template_registry
from backend.services.meta_graph import url as graph_url

# Meta template copy can contain emoji that the Windows console code page
# cannot encode. Keep the audit running and escape only unsupported glyphs.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")


async def audit(name: str) -> int:
    async with AsyncSessionLocal() as db:
        matches = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(Branch.name.ilike(f"%{name}%"))
            )
        ).all()
        if len(matches) != 1:
            print(f"Expected one branch, found {len(matches)}")
            return 1
        branch, plan = matches[0]
        deliveries = (
            await db.execute(
                select(
                    WhatsAppDelivery.purpose,
                    WhatsAppDelivery.status,
                    func.count(),
                    func.max(WhatsAppDelivery.updated_at),
                )
                .where(WhatsAppDelivery.branch_id == branch.id)
                .group_by(WhatsAppDelivery.purpose, WhatsAppDelivery.status)
                .order_by(WhatsAppDelivery.purpose, WhatsAppDelivery.status)
            )
        ).all()
        token_counts = Counter(
            dict(
                (
                    await db.execute(
                        select(Token.status, func.count())
                        .where(Token.branch_id == branch.id)
                        .group_by(Token.status)
                    )
                ).all()
            )
        )
        followups = Counter(
            dict(
                (
                    await db.execute(
                        select(FollowupTask.status, func.count())
                        .where(FollowupTask.branch_id == branch.id)
                        .group_by(FollowupTask.status)
                    )
                ).all()
            )
        )

    print("Branch")
    print(f"  name={branch.name}")
    print(f"  plan={plan} addon={branch.whatsapp_addon} status={branch.wa_status}")
    print(
        "  phone_id={} waba={} token={} enabled={}".format(
            bool(branch.wa_phone_number_id),
            bool(branch.wa_waba_id),
            bool(wa_service.token_for(branch)),
            wa_service.wa_enabled(branch, plan),
        )
    )
    print(f"  address={branch.address or 'MISSING'}")
    print(
        f"  reminder_calls={branch.reminder_calls_enabled} "
        f"followup_calls={branch.followup_calls_enabled}"
    )
    print(f"  token_statuses={dict(token_counts)}")
    print(f"  followup_statuses={dict(followups)}")

    token = wa_service.token_for(branch)
    if token and branch.wa_waba_id:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                graph_url(f"{branch.wa_waba_id}/subscribed_apps"),
                headers={"Authorization": f"Bearer {token}"},
            )
        apps = response.json().get("data", []) if response.is_success else []
        app_ids = [
            app.get("id") or (app.get("whatsapp_business_api_data") or {}).get("id")
            for app in apps
        ]
        print(
            "  subscribed_apps="
            + (", ".join(str(app_id) for app_id in app_ids if app_id) or "NONE")
        )

    print("\nApproved Meta templates")
    try:
        templates = await wa_template_admin.list_templates(branch)
    except Exception as exc:  # read-only diagnostic; keep Graph detail terse
        print(f"  ERROR {type(exc).__name__}: {str(exc)[:200]}")
        templates = []
    for item in sorted(templates, key=lambda row: row.get("name", "")):
        body = next(
            (
                component.get("text", "")
                for component in item.get("components") or []
                if component.get("type", "").upper() == "BODY"
            ),
            "",
        )
        buttons = next(
            (
                component.get("buttons", [])
                for component in item.get("components") or []
                if component.get("type", "").upper() == "BUTTONS"
            ),
            [],
        )
        print(
            f"  {item.get('name')} language={item.get('language')} "
            f"status={item.get('status')} body={body!r} buttons={buttons!r}"
        )
    mapping = wa_template_registry.build_map(templates)
    for purpose in wa_template_registry.PURPOSES:
        spec = mapping.get(purpose)
        print(
            f"  purpose:{purpose}="
            + (f"{spec['name']} params={spec['params']} buttons={spec['buttons']}" if spec else "MISSING")
        )

    print("\nDurable delivery outbox")
    if not deliveries:
        print("  empty")
    for purpose, status, count, updated_at in deliveries:
        print(f"  {purpose}/{status}: {count} last={updated_at}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("clinic")
    return asyncio.run(audit(parser.parse_args().clinic))


if __name__ == "__main__":
    raise SystemExit(main())
