"""Delete ALL existing LiveKit SIP trunks + dispatch rules for a clean slate.

Run before setup_sip.py when rebuilding the SIP configuration.
Official API reference: https://docs.livekit.io/sip/api/
"""
import asyncio

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")


async def main() -> None:
    lkapi = api.LiveKitAPI()
    sip = lkapi.sip

    rules = await sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
    for rule in rules.items:
        print(f"Deleting dispatch rule {rule.sip_dispatch_rule_id} ({rule.name})")
        await sip.delete_sip_dispatch_rule(
            api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule.sip_dispatch_rule_id)
        )

    inbound = await sip.list_sip_inbound_trunk(api.ListSIPInboundTrunkRequest())
    for trunk in inbound.items:
        print(f"Deleting inbound trunk {trunk.sip_trunk_id} ({trunk.name})")
        await sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk.sip_trunk_id))

    outbound = await sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
    for trunk in outbound.items:
        print(f"Deleting outbound trunk {trunk.sip_trunk_id} ({trunk.name})")
        await sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk.sip_trunk_id))

    await lkapi.aclose()
    print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
