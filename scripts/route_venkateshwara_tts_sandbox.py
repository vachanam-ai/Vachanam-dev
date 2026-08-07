"""Point the Venkateshwara test number at the Cartesia TTS sandbox — and back.

    python scripts/route_venkateshwara_tts_sandbox.py status
    python scripts/route_venkateshwara_tts_sandbox.py apply
    python scripts/route_venkateshwara_tts_sandbox.py revert

WHY THIS IS A SCRIPT AND NOT A ONE-LINER. There is ONE dispatch rule on the
Vobiz trunk and it has no number filter, so it matches BOTH clinics:

    sri skincare        +918071387303   <- a REAL clinic
    Sri Venkateshwara   +918046733493   <- Vinay's test number

Simply repointing that rule would send sri skincare's patients to the sandbox
too. So `apply` does two things: it pins the existing rule to the real clinic's
number, then adds a second rule for the test number only. Two explicit rules,
no ambiguity about which one wins.

`revert` puts it back exactly: the original rule returns to a catch-all
(inbound_numbers=[]) and the sandbox rule is deleted.

Safe to re-run: both directions check the current state first.
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(".env")

PROD_RULE_ID = "SDR_qbmQVnbrbMUv"
TRUNK_ID = "ST_kcZDagvoGXMZ"
SKINCARE = "+918071387303"   # real clinic  -> production agent
VENKAT = "+918046733493"     # test number  -> Cartesia sandbox
PROD_AGENT = "vachanam-agent"
SANDBOX_AGENT = "vachanam-sandbox"
SANDBOX_RULE_NAME = "tts-sandbox-venkateshwara"


def _api():
    from livekit import api

    return api.LiveKitAPI(
        os.environ["LIVEKIT_URL"],
        os.environ["LIVEKIT_API_KEY"],
        os.environ["LIVEKIT_API_SECRET"],
    )


async def _rules(lk):
    from livekit import api

    res = await lk.sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
    return list(res.items)


def _show(rules) -> None:
    for r in rules:
        agents = [a.agent_name for a in (r.room_config.agents if r.room_config else [])]
        print(
            f"  {r.sip_dispatch_rule_id}  name={r.name or '-':28s} "
            f"numbers={list(r.inbound_numbers) or 'ALL'}  agents={agents}"
        )


async def status() -> None:
    lk = _api()
    try:
        print("Current dispatch rules:")
        _show(await _rules(lk))
    finally:
        await lk.aclose()


async def apply() -> None:
    from livekit import api

    lk = _api()
    try:
        before = await _rules(lk)
        if any(r.name == SANDBOX_RULE_NAME for r in before):
            print("Sandbox rule already exists — nothing to do.")
            _show(before)
            return

        # 1. Pin the live rule to the REAL clinic so it can never match the
        #    test number once a second rule exists.
        upd = await lk.sip.update_sip_dispatch_rule(
            api.UpdateSIPDispatchRuleRequest(
                sip_dispatch_rule_id=PROD_RULE_ID, inbound_numbers=[SKINCARE],
            )
        )
        print(f"pinned {upd.sip_dispatch_rule_id} -> {list(upd.inbound_numbers)}")

        # 2. Test number -> sandbox worker.
        created = await lk.sip.create_sip_dispatch_rule(
            api.CreateSIPDispatchRuleRequest(
                name=SANDBOX_RULE_NAME,
                trunk_ids=[TRUNK_ID],
                inbound_numbers=[VENKAT],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix="call",
                    )
                ),
                room_config=api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=SANDBOX_AGENT)]
                ),
            )
        )
        print(f"created {created.sip_dispatch_rule_id} -> {SANDBOX_AGENT}")
        print("\nNow:")
        _show(await _rules(lk))
        print(
            f"\n{VENKAT} now answers with CARTESIA. {SKINCARE} is unchanged.\n"
            "Revert with: python scripts/route_venkateshwara_tts_sandbox.py revert"
        )
    finally:
        await lk.aclose()


async def revert() -> None:
    from livekit import api

    lk = _api()
    try:
        for r in await _rules(lk):
            if r.name == SANDBOX_RULE_NAME:
                await lk.sip.delete_sip_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=r.sip_dispatch_rule_id)
                )
                print(f"deleted sandbox rule {r.sip_dispatch_rule_id}")

        upd = await lk.sip.update_sip_dispatch_rule(
            api.UpdateSIPDispatchRuleRequest(
                sip_dispatch_rule_id=PROD_RULE_ID, inbound_numbers=[],
            )
        )
        print(f"restored {upd.sip_dispatch_rule_id} -> catch-all ({PROD_AGENT})")
        print("\nNow:")
        _show(await _rules(lk))
    finally:
        await lk.aclose()


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd not in ("status", "apply", "revert"):
        print(__doc__)
        raise SystemExit(2)
    asyncio.run({"status": status, "apply": apply, "revert": revert}[cmd]())
