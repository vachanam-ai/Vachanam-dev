"""Flip inbound routing between prod and the raw-latency sandbox.

    python sandbox/raw-latency/route.py            # show trunks + rules
    python sandbox/raw-latency/route.py --speed    # ALL DIDs -> vachanam-speed (sandbox)
    python sandbox/raw-latency/route.py --prod     # ALL DIDs -> vachanam-agent

ONE inbound trunk carries all three DIDs and ONE catch-all dispatch rule.
`inbound_numbers` filters by CALLER not dialed number, and a rule's agent can't
be updated in place — so we DELETE the catch-all rule and RECREATE it pointing
at the chosen agent. Same trunk, no auth copying, no trunk mutation.

TRADE-OFF (short test window): --speed routes ALL three DIDs to the sandbox.
The other two are low-traffic test lines. Flip back with --prod when done.
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parents[2] / ".env"))

TRUNK = "ST_kcZDagvoGXMZ"
RULE_NAME = "vobiz-inbound-dispatch"
PROD_AGENT = "vachanam-agent"
SANDBOX_AGENT = "vachanam-speed"


async def main() -> None:
    from livekit import api
    from livekit.protocol.agent_dispatch import RoomAgentDispatch
    from livekit.protocol.room import RoomConfiguration
    from livekit.protocol.sip import (
        CreateSIPDispatchRuleRequest,
        DeleteSIPDispatchRuleRequest,
        ListSIPDispatchRuleRequest,
        SIPDispatchRule,
        SIPDispatchRuleIndividual,
    )

    lk = api.LiveKitAPI()

    async def show() -> None:
        for r in (await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())).items:
            agents = (
                [a.agent_name for a in r.room_config.agents]
                if r.HasField("room_config")
                else []
            )
            print(f"RULE {r.sip_dispatch_rule_id} name={r.name!r} agents={agents}")

    async def repoint(agent: str, prefix: str) -> None:
        for r in (await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())).items:
            if TRUNK in r.trunk_ids:
                await lk.sip.delete_sip_dispatch_rule(
                    DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=r.sip_dispatch_rule_id)
                )
        await lk.sip.create_sip_dispatch_rule(CreateSIPDispatchRuleRequest(
            name=RULE_NAME,
            trunk_ids=[TRUNK],
            rule=SIPDispatchRule(
                dispatch_rule_individual=SIPDispatchRuleIndividual(room_prefix=prefix)
            ),
            room_config=RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=agent)]
            ),
        ))

    try:
        if "--speed" in sys.argv:
            await repoint(SANDBOX_AGENT, "raw-")
            print(f"SANDBOX ON: all DIDs -> {SANDBOX_AGENT}")
        elif "--prod" in sys.argv:
            await repoint(PROD_AGENT, "call-")
            print(f"PROD RESTORED: all DIDs -> {PROD_AGENT}")
        await show()
    finally:
        await lk.aclose()


asyncio.run(main())
