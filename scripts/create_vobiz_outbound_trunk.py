"""Idempotently create the ONE shared Vobiz outbound trunk.

Every clinic DID belongs in this trunk's ``numbers`` list. Calls still present
the correct clinic number because the worker supplies that branch's database
DID as ``sip_number`` on every dial. Re-running merges ``DID_NUMBERS`` into the
existing named trunk; it never creates one trunk per clinic.

Secrets come from environment variables only:
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
  VOBIZ_SIP_DOMAIN, VOBIZ_SIP_USERNAME, VOBIZ_SIP_PASSWORD
  DID_NUMBERS   optional comma-separated DIDs in E.164
  DID_NUMBER    one optional DID (backward-compatible alternative)

Run: python -m scripts.create_vobiz_outbound_trunk
"""
import asyncio
import os
import sys

TRUNK_NAME = "vobiz-outbound"


async def main() -> int:
    from livekit import api

    required = [
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "VOBIZ_SIP_DOMAIN", "VOBIZ_SIP_USERNAME", "VOBIZ_SIP_PASSWORD",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    raw_numbers = os.getenv("DID_NUMBERS") or os.getenv("DID_NUMBER") or ""
    numbers = sorted({item.strip() for item in raw_numbers.split(",") if item.strip()})
    lkapi = api.LiveKitAPI()
    try:
        existing = await lkapi.sip.list_outbound_trunk(
            api.ListSIPOutboundTrunkRequest()
        )
        for trunk in existing.items:
            if trunk.name != TRUNK_NAME:
                continue
            merged = sorted(set(trunk.numbers) | set(numbers))
            if merged != sorted(trunk.numbers):
                await lkapi.sip.update_outbound_trunk_fields(
                    trunk_id=trunk.sip_trunk_id, numbers=merged
                )
            print(
                f"OK OUTBOUND_TRUNK_ID={trunk.sip_trunk_id} "
                f"numbers={len(merged)} reused=true"
            )
            return 0

        trunk = api.SIPOutboundTrunkInfo(
            name=TRUNK_NAME,
            address=os.environ["VOBIZ_SIP_DOMAIN"].strip(),
            numbers=numbers,
            auth_username=os.environ["VOBIZ_SIP_USERNAME"].strip(),
            auth_password=os.environ["VOBIZ_SIP_PASSWORD"],
        )
        result = await lkapi.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(trunk=trunk)
        )
        print(
            f"OK OUTBOUND_TRUNK_ID={result.sip_trunk_id} "
            f"numbers={len(numbers)} reused=false"
        )
        return 0
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
