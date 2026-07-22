"""Flip the Sri Venkateshwara DID between prod and the speed-test agent.

    python sandbox/speed-test/route.py            # show current rules
    python sandbox/speed-test/route.py --speed    # +918046733493 -> vachanam-speed
    python sandbox/speed-test/route.py --prod     # remove the override (back to prod)

Mechanism: the shared catch-all rule (SDR_3fmWZSGdsGeo, all 3 numbers ->
vachanam-agent) is NEVER touched. --speed creates a SECOND, number-specific
rule for the Venkateshwara DID dispatching vachanam-speed; --prod deletes it.
If LiveKit rejects the overlapping rule, this prints the error and changes
nothing — fall back is a manual decision, never automatic.
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parents[2] / ".env"))

TRUNK = "ST_kcZDagvoGXMZ"
NUMBER = "+918046733493"  # Sri Venkateshwara
RULE_NAME = "speed-test-venkateshwara"
SPEED_AGENT = "vachanam-speed"


async def main() -> None:
    from livekit import api
    from livekit.protocol.sip import (
        CreateSIPDispatchRuleRequest,
        DeleteSIPDispatchRuleRequest,
        ListSIPDispatchRuleRequest,
        SIPDispatchRule,
        SIPDispatchRuleIndividual,
    )
    from livekit.protocol.room import RoomAgentDispatch, RoomConfiguration

    lk = api.LiveKitAPI()
    try:
        rules = (await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())).items
        override = next((r for r in rules if r.name == RULE_NAME), None)

        if "--speed" in sys.argv:
            if override:
                print(f"override already active: {override.sip_dispatch_rule_id}")
                return
            req = CreateSIPDispatchRuleRequest(
                name=RULE_NAME,
                trunk_ids=[TRUNK],
                inbound_numbers=[NUMBER],
                rule=SIPDispatchRule(
                    dispatch_rule_individual=SIPDispatchRuleIndividual(
                        room_prefix="speed-"
                    )
                ),
                room_config=RoomConfiguration(
                    agents=[RoomAgentDispatch(agent_name=SPEED_AGENT)]
                ),
            )
            r = await lk.sip.create_sip_dispatch_rule(req)
            print(f"SPEED ON: {NUMBER} -> {SPEED_AGENT} (rule {r.sip_dispatch_rule_id})")
            print("Revert with: python sandbox/speed-test/route.py --prod")
        elif "--prod" in sys.argv:
            if not override:
                print("no override active — prod routing already in effect")
                return
            await lk.sip.delete_sip_dispatch_rule(
                DeleteSIPDispatchRuleRequest(
                    sip_dispatch_rule_id=override.sip_dispatch_rule_id
                )
            )
            print(f"PROD RESTORED: override {override.sip_dispatch_rule_id} deleted")
        else:
            for r in rules:
                agents = (
                    [a.agent_name for a in r.room_config.agents]
                    if r.HasField("room_config")
                    else []
                )
                print(
                    f"rule {r.sip_dispatch_rule_id} name={r.name!r} "
                    f"trunks={list(r.trunk_ids)} numbers={list(r.inbound_numbers)} "
                    f"agents={agents}"
                )
    finally:
        await lk.aclose()


asyncio.run(main())
