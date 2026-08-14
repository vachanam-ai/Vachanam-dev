"""Idempotent bootstrap of the GLOBAL LiveKit inbound telephony for Vachanam.

Ensures the two LiveKit resources that make "paste a DID in Settings → it just
works" true for EVERY clinic, present and future:

  1. ONE inbound SIP trunk ("vobiz-inbound") — the entry point for all inbound
     calls. Per-clinic DIDs are added to its `numbers` automatically when an
     owner saves a DID in Settings (backend.services.livekit_sip), so this
     script creates it with an EMPTY number list and never touches numbers.
  2. ONE dispatch rule ("vobiz-inbound-dispatch") — routes every inbound call on
     that trunk to the agent worker (agent_name=vachanam-agent) in its own
     `call-` room, passing the SIP attributes the agent uses to resolve the
     branch from the dialed DID (RULE 5).

Run once per LiveKit project (or after recreating one / spinning up a new
region). Idempotent: re-running finds the existing resources by name and reuses
them — it never creates duplicates. Prints the two IDs to set as env:

    INBOUND_TRUNK_ID   (backend reads this to auto-wire saved DIDs)
    DISPATCH_RULE_ID   (informational; the rule routes by trunk, not by env)

The Vobiz side stays manual (the code has no Vobiz inbound-routing API): point
each purchased DID's inbound destination at this project's LiveKit SIP URI. That
is the only per-DID external step — everything inside our stack is automatic.

Secrets come from the ENVIRONMENT only (never hardcode). Set:
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

Run:
    python -m scripts.setup_livekit_telephony
"""
import asyncio
import os
import sys

AGENT_NAME = "vachanam-agent"
TRUNK_NAME = "vobiz-inbound"
RULE_NAME = "vobiz-inbound-dispatch"
ROOM_PREFIX = "call-"


async def _ensure_inbound_trunk(lkapi, api) -> str:
    """Return the inbound trunk id, creating it (empty numbers) if absent."""
    existing = await lkapi.sip.list_sip_inbound_trunk(
        api.ListSIPInboundTrunkRequest()
    )
    for t in existing.items:
        if t.name == TRUNK_NAME:
            print(f"  reuse inbound trunk  {t.sip_trunk_id}  numbers={list(t.numbers)}")
            return t.sip_trunk_id

    # Numbers start EMPTY on purpose — per-clinic DIDs are wired in on save by
    # sync_did_to_inbound_trunk. The trunk accepts a call when the dialed number
    # is present in `numbers`, so wiring the number IS the per-tenant gate.
    res = await lkapi.sip.create_sip_inbound_trunk(
        api.CreateSIPInboundTrunkRequest(
            trunk=api.SIPInboundTrunkInfo(name=TRUNK_NAME, numbers=[])
        )
    )
    print(f"  CREATED inbound trunk {res.sip_trunk_id}")
    return res.sip_trunk_id


async def _ensure_dispatch_rule(lkapi, api, trunk_id: str) -> str:
    """Return the dispatch-rule id routing `trunk_id` → the agent, creating it
    if no rule already targets this trunk + agent."""
    existing = await lkapi.sip.list_sip_dispatch_rule(
        api.ListSIPDispatchRuleRequest()
    )
    for r in existing.items:
        targets_trunk = (not r.trunk_ids) or (trunk_id in r.trunk_ids)
        agents = list(getattr(r.room_config, "agents", []) or [])
        hits_agent = any(a.agent_name == AGENT_NAME for a in agents)
        if r.name == RULE_NAME or (targets_trunk and hits_agent):
            print(f"  reuse dispatch rule  {r.sip_dispatch_rule_id}")
            return r.sip_dispatch_rule_id

    res = await lkapi.sip.create_sip_dispatch_rule(
        api.CreateSIPDispatchRuleRequest(
            name=RULE_NAME,
            trunk_ids=[trunk_id],
            # Each call gets its own room (no caller mixing) — matches prod.
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                    room_prefix=ROOM_PREFIX
                )
            ),
            # The room auto-dispatches the agent worker; agent reads the SIP
            # attributes (sip.trunkPhoneNumber) to resolve the branch (RULE 5).
            room_config=api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]
            ),
        )
    )
    print(f"  CREATED dispatch rule {res.sip_dispatch_rule_id} -> agent {AGENT_NAME}")
    return res.sip_dispatch_rule_id


async def main() -> int:
    missing = [
        k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        if not os.getenv(k)
    ]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    from livekit import api

    lkapi = api.LiveKitAPI()
    try:
        print("Ensuring LiveKit inbound telephony (idempotent)...")
        trunk_id = await _ensure_inbound_trunk(lkapi, api)
        rule_id = await _ensure_dispatch_rule(lkapi, api, trunk_id)
    finally:
        await lkapi.aclose()

    print("\nDone. Set these in the backend env (Render) + agent env (Fly):")
    print(f"  INBOUND_TRUNK_ID={trunk_id}")
    print(f"  DISPATCH_RULE_ID={rule_id}")
    print(
        "\nVobiz (one-time per DID): point the DID's inbound destination at this "
        "project's LiveKit SIP URI. Then pasting the DID in Settings wires the "
        "rest automatically for that clinic."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
