"""Flip inbound routing between prod and the speed-test agent.

    python sandbox/speed-test/route.py            # show trunks + rules
    python sandbox/speed-test/route.py --speed    # ALL DIDs -> vachanam-speed
    python sandbox/speed-test/route.py --prod     # ALL DIDs -> vachanam-agent

Simplest thing that actually works (after v2/v3/v4 all failed on
precedence/field-support/auth-copy): there is ONE inbound trunk carrying all
three DIDs and ONE catch-all dispatch rule. `inbound_numbers` on a rule filters
by CALLER, not dialed number, and a rule's agent can't be updated in place —
so we just DELETE the catch-all rule and RECREATE it pointing at the chosen
agent. Same trunk, no auth copying, no trunk mutation.

TRADE-OFF (accepted for a short active test window): --speed routes ALL three
DIDs to the sandbox, not just Venkateshwara. The other two are the test line
+918000009999 and +918071387303 — low traffic. Flip back with --prod the
moment the test call is done.
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parents[2] / ".env"))

TRUNK = "ST_kcZDagvoGXMZ"
RULE_NAME = "vobiz-inbound-dispatch"
PROD_AGENT = "vachanam-agent"
SPEED_AGENT = "vachanam-speed"


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
        # delete every existing rule on this trunk, then create one catch-all
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
            await repoint(SPEED_AGENT, "speed-")
            print(f"SPEED ON: all DIDs -> {SPEED_AGENT}")
        elif "--prod" in sys.argv:
            await repoint(PROD_AGENT, "call-")
            print(f"PROD RESTORED: all DIDs -> {PROD_AGENT}")
        await show()
    finally:
        await lk.aclose()


asyncio.run(main())
