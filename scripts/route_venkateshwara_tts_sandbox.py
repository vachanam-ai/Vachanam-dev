"""Route only Venkateshwara to the latency sandbox, and safely revert.

LiveKit inbound_numbers filters the CALLER (ANI), not the clinic number
that was dialed. It must never be used for DID routing. LiveKit's supported
multi-number pattern is one inbound trunk per destination, with each dispatch
rule bound to its trunk.

    python scripts/route_venkateshwara_tts_sandbox.py status
    python scripts/route_venkateshwara_tts_sandbox.py apply
    python scripts/route_venkateshwara_tts_sandbox.py revert

Apply creates a number-specific sandbox trunk and rule, then moves only the
Venkateshwara DID from the production trunk. Revert moves it back before
deleting the sandbox resources. Both operations roll back the DID move if an
API call fails.
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(".env")

PROD_RULE_ID = "SDR_qbmQVnbrbMUv"
PROD_TRUNK_ID = "ST_kcZDagvoGXMZ"
VENKAT = "+918046733493"
PROD_AGENT = "vachanam-agent"
SANDBOX_AGENT = "vachanam-sandbox"
SANDBOX_TRUNK_NAME = "vobiz-inbound-venkateshwara-sandbox"
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

    return list(
        (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
    )


async def _trunks(lk):
    from livekit import api

    return list(
        (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
    )


def _agents(rule) -> list[str]:
    return [
        agent.agent_name
        for agent in (rule.room_config.agents if rule.room_config else [])
    ]


def _show(trunks, rules) -> None:
    print("Inbound trunks:")
    for trunk in trunks:
        print(f"  {trunk.sip_trunk_id}  name={trunk.name} numbers={list(trunk.numbers)}")
    print("Dispatch rules:")
    for rule in rules:
        print(
            f"  {rule.sip_dispatch_rule_id}  name={rule.name or '-'} "
            f"trunks={list(rule.trunk_ids) or 'ALL'} "
            f"caller_filter={list(rule.inbound_numbers) or 'NONE'} "
            f"agents={_agents(rule)}"
        )


def _one(items, predicate, label):
    matches = [item for item in items if predicate(item)]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {label}, found {len(matches)}")
    return matches[0]


def _validate_prod(trunks, rules):
    trunk = _one(
        trunks, lambda item: item.sip_trunk_id == PROD_TRUNK_ID, "production trunk"
    )
    rule = _one(
        rules, lambda item: item.sip_dispatch_rule_id == PROD_RULE_ID, "production rule"
    )
    if list(rule.trunk_ids) != [PROD_TRUNK_ID]:
        raise RuntimeError("production rule is not bound only to the production trunk")
    if list(rule.inbound_numbers):
        raise RuntimeError(
            "production rule has a caller-number filter; run revert before continuing"
        )
    if _agents(rule) != [PROD_AGENT]:
        raise RuntimeError("production rule does not target the production agent")
    return trunk


async def _set_numbers(lk, trunk, numbers: list[str]):
    return await lk.sip.update_inbound_trunk_fields(
        trunk_id=trunk.sip_trunk_id,
        numbers=list(dict.fromkeys(numbers)),
    )


async def status() -> None:
    lk = _api()
    try:
        _show(await _trunks(lk), await _rules(lk))
    finally:
        await lk.aclose()


async def apply() -> None:
    from livekit import api

    lk = _api()
    sandbox_trunk = None
    sandbox_rule = None
    try:
        trunks = await _trunks(lk)
        rules = await _rules(lk)
        prod_trunk = _validate_prod(trunks, rules)
        existing_trunks = [t for t in trunks if t.name == SANDBOX_TRUNK_NAME]
        existing_rules = [r for r in rules if r.name == SANDBOX_RULE_NAME]

        if existing_trunks or existing_rules:
            if len(existing_trunks) == len(existing_rules) == 1:
                sandbox_trunk = existing_trunks[0]
                sandbox_rule = existing_rules[0]
                active = (
                    VENKAT in sandbox_trunk.numbers
                    and VENKAT not in prod_trunk.numbers
                    and list(sandbox_rule.trunk_ids)
                    == [sandbox_trunk.sip_trunk_id]
                    and not list(sandbox_rule.inbound_numbers)
                    and _agents(sandbox_rule) == [SANDBOX_AGENT]
                )
                if active:
                    print("Sandbox trunk routing is already active.")
                    _show(trunks, rules)
                    return
            raise RuntimeError(
                "partial or inconsistent sandbox resources found; run revert first"
            )

        if VENKAT not in prod_trunk.numbers:
            raise RuntimeError("Venkateshwara DID is absent from the production trunk")

        # LiveKit requires a number and forbids the same DID on two unauthenticated
        # trunks. Move it transactionally; the exception path restores prod.
        await _set_numbers(
            lk, prod_trunk, [number for number in prod_trunk.numbers if number != VENKAT]
        )
        sandbox_trunk = await lk.sip.create_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name=SANDBOX_TRUNK_NAME,
                    numbers=[VENKAT],
                )
            )
        )
        sandbox_rule = await lk.sip.create_dispatch_rule(
            api.CreateSIPDispatchRuleRequest(
                name=SANDBOX_RULE_NAME,
                trunk_ids=[sandbox_trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix="call-"
                    )
                ),
                room_config=api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=SANDBOX_AGENT)]
                ),
            )
        )

        print("Venkateshwara now routes by its own inbound trunk to the sandbox.")
        _show(await _trunks(lk), await _rules(lk))
    except Exception:
        # The number cannot exist on two trunks, so remove partial sandbox
        # resources first, then restore the production trunk.
        try:
            if sandbox_rule is not None:
                await lk.sip.delete_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(
                        sip_dispatch_rule_id=sandbox_rule.sip_dispatch_rule_id
                    )
                )
            if sandbox_trunk is not None:
                await lk.sip.delete_trunk(
                    api.DeleteSIPTrunkRequest(
                        sip_trunk_id=sandbox_trunk.sip_trunk_id
                    )
                )
            trunks = await _trunks(lk)
            prod = next((t for t in trunks if t.sip_trunk_id == PROD_TRUNK_ID), None)
            if prod and VENKAT not in prod.numbers:
                await _set_numbers(lk, prod, [*prod.numbers, VENKAT])
        except Exception as rollback_error:
            print(f"ROLLBACK ERROR: {rollback_error}", file=sys.stderr)
        raise
    finally:
        await lk.aclose()


async def revert() -> None:
    from livekit import api

    lk = _api()
    try:
        trunks = await _trunks(lk)
        rules = await _rules(lk)
        prod_trunk = _validate_prod(trunks, rules)
        sandbox_trunks = [t for t in trunks if t.name == SANDBOX_TRUNK_NAME]
        sandbox_rules = [r for r in rules if r.name == SANDBOX_RULE_NAME]

        for rule in sandbox_rules:
            await lk.sip.delete_dispatch_rule(
                api.DeleteSIPDispatchRuleRequest(
                    sip_dispatch_rule_id=rule.sip_dispatch_rule_id
                )
            )
        for trunk in sandbox_trunks:
            await lk.sip.delete_trunk(
                api.DeleteSIPTrunkRequest(sip_trunk_id=trunk.sip_trunk_id)
            )
        if VENKAT not in prod_trunk.numbers:
            await _set_numbers(lk, prod_trunk, [*prod_trunk.numbers, VENKAT])
        print("Venkateshwara restored to the production trunk and agent.")
        _show(await _trunks(lk), await _rules(lk))
    finally:
        await lk.aclose()


if __name__ == "__main__":
    command = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if command not in ("status", "apply", "revert"):
        print(__doc__)
        raise SystemExit(2)
    asyncio.run({"status": status, "apply": apply, "revert": revert}[command]())
