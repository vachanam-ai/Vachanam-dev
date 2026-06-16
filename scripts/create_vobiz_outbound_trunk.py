"""Create a LiveKit OUTBOUND SIP trunk that authenticates to a Vobiz
sub-account, so this clinic dials patients through its OWN Vobiz channel pool.

Prints the new trunk id — paste it into the branch's `outbound_trunk_id`
(Settings → telephony, or PATCH /branches/{id}/telephony).

Secrets come from the ENVIRONMENT only (never hardcode, never commit). Set:
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET   (LiveKit project)
  VOBIZ_SIP_DOMAIN     Vobiz termination/SIP domain for the sub-account
  VOBIZ_SIP_USERNAME   sub-account SIP/Auth ID (e.g. SA_LZ7BN59D)
  VOBIZ_SIP_PASSWORD   sub-account SIP password / Auth Token
  DID_NUMBER           the purchased DID in E.164 (e.g. +918012345678)

Run:
  python -m scripts.create_vobiz_outbound_trunk
"""
import asyncio
import os
import sys


async def main() -> int:
    from livekit import api

    required = [
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "VOBIZ_SIP_DOMAIN", "VOBIZ_SIP_USERNAME", "VOBIZ_SIP_PASSWORD",
        "DID_NUMBER",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    did = os.environ["DID_NUMBER"].strip()
    lkapi = api.LiveKitAPI()
    try:
        trunk = api.SIPOutboundTrunkInfo(
            name=f"vobiz-{os.getenv('VOBIZ_SIP_USERNAME')}",
            address=os.environ["VOBIZ_SIP_DOMAIN"].strip(),
            numbers=[did],
            auth_username=os.environ["VOBIZ_SIP_USERNAME"].strip(),
            auth_password=os.environ["VOBIZ_SIP_PASSWORD"],
        )
        res = await lkapi.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(trunk=trunk)
        )
        # last-4 only in logs (Rule 9); full id is the non-secret output we want.
        print(f"OK outbound_trunk_id={res.sip_trunk_id} did=...{did[-4:]}")
        return 0
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
