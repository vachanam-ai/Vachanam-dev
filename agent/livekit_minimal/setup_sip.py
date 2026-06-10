"""Create LiveKit SIP resources for Vobiz integration (official patterns).

Creates:
  1. Outbound trunk — LiveKit dials out through Vobiz SIP trunk
     https://docs.livekit.io/sip/trunk-outbound/
  2. Inbound trunk — accepts PSTN calls Vobiz forwards to our LiveKit SIP URI
     https://docs.livekit.io/sip/trunk-inbound/
  3. Dispatch rule — routes each inbound call to its own room AND auto-dispatches
     the named agent via room_config (THE piece that makes the agent pick up)
     https://docs.livekit.io/sip/dispatch-rule/

Prints IDs to paste into .env.
"""
import asyncio
import os

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")

AGENT_NAME = "vachanam-agent"


async def main() -> None:
    lkapi = api.LiveKitAPI()
    sip = lkapi.sip

    address = os.getenv("VOBIZ_SIP_DOMAIN")
    username = os.getenv("VOBIZ_USERNAME")
    password = os.getenv("VOBIZ_PASSWORD")
    number = os.getenv("VOBIZ_OUTBOUND_NUMBER")
    assert address and username and password and number, "Missing VOBIZ_* env vars"

    # 1. Outbound trunk
    out_trunk = await sip.create_sip_outbound_trunk(
        api.CreateSIPOutboundTrunkRequest(
            trunk=api.SIPOutboundTrunkInfo(
                name="vobiz-outbound",
                address=address,
                transport=api.SIPTransport.SIP_TRANSPORT_AUTO,
                numbers=[number],
                auth_username=username,
                auth_password=password,
            )
        )
    )
    print(f"OUTBOUND_TRUNK_ID={out_trunk.sip_trunk_id}")

    # 2. Inbound trunk — open (no auth / no source filter): Vobiz signaling IPs
    #    differ from the SIP domain, so filtering by address rejects the INVITE.
    in_trunk = await sip.create_sip_inbound_trunk(
        api.CreateSIPInboundTrunkRequest(
            trunk=api.SIPInboundTrunkInfo(
                name="vobiz-inbound",
                numbers=[number],
            )
        )
    )
    print(f"INBOUND_TRUNK_ID={in_trunk.sip_trunk_id}")

    # 3. Dispatch rule with explicit agent dispatch. Without room_config naming
    #    the agent, a worker registered with agent_name is NEVER auto-dispatched
    #    and inbound calls ring forever.
    dispatch = await sip.create_sip_dispatch_rule(
        api.CreateSIPDispatchRuleRequest(
            dispatch_rule=api.SIPDispatchRuleInfo(
                name="vobiz-inbound-dispatch",
                trunk_ids=[in_trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix="call-",
                    )
                ),
                room_config=api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]
                ),
            )
        )
    )
    print(f"DISPATCH_RULE_ID={dispatch.sip_dispatch_rule_id}")

    await lkapi.aclose()

    print("\nPaste the three IDs above into .env")


if __name__ == "__main__":
    asyncio.run(main())
