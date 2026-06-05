"""One-shot idempotent Vobiz + LiveKit SIP trunk provisioning.

Run ONCE after filling .env with all Vobiz values. Safe to re-run —
every step checks for an existing resource before creating a new one.

Usage:
    python scripts/provision_vobiz_trunk.py

Required .env vars (7 Vobiz + 3 LiveKit):
    VOBIZ_SIP_DOMAIN        e.g. abc123.sip.vobiz.ai
    VOBIZ_SIP_USERNAME      SIP trunk auth username from Vobiz console
    VOBIZ_SIP_PASSWORD      SIP trunk auth password from Vobiz console
    VOBIZ_DID_NUMBER        E.164 DID, e.g. +914066XXXXXX
    VOBIZ_PARTNER_AUTH_ID   Your Vobiz master partner account ID (format: MA_XXXXXX)
    VOBIZ_PARTNER_AUTH_TOKEN Your Vobiz master partner token
    VOBIZ_TRUNK_ID          Vobiz internal trunk UUID from Step 1 of Vobiz
                            console setup (Telephony -> SIP Trunks -> your
                            trunk -> copy the UUID from the URL or trunk detail
                            page, e.g. bfab10fb-cb97-488b-9c63-989c32980b0f)

    LIVEKIT_URL             e.g. wss://vachanam-agent.fly.dev
    LIVEKIT_API_KEY         from LiveKit server setup
    LIVEKIT_API_SECRET      from LiveKit server setup

What this script does (in order):
    Step 1: Create LiveKit outbound SIP trunk (Vachanam-Vobiz)
    Step 2: Create LiveKit inbound SIP trunk (Vachanam-Vobiz-Inbound)
    Step 3: Create LiveKit dispatch rule (room_prefix=call-, agent=voice-assistant)
    Step 4: PUT Vobiz trunk inbound_destination to LiveKit SIP URI
    Step 5: Print verification summary + first-call test command

What is idempotent (safe to re-run):
    - Steps 1-3: if the resource already exists by name/trunk_id, it is skipped
    - Step 4: if Vobiz inbound_destination already matches, PUT is skipped

What is NOT idempotent (one-time manual actions in Vobiz console):
    - Creating the SIP trunk in Vobiz console (Part 1 in the Vobiz doc)
    - Purchasing the DID number in Vobiz console

Teardown:
    Delete resources manually in the LiveKit dashboard or via the lk CLI:
        lk sip outbound delete <trunk_id>
        lk sip inbound delete <trunk_id>
        lk sip dispatch delete <rule_id>
    Then re-run this script to re-provision.

Ref: https://docs.vobiz.ai/integrations/livekit
     https://docs.vobiz.ai/trunks/update-trunk
     https://docs.vobiz.ai/trunks/retrieve-trunk
"""
import re
import sys
from pathlib import Path

# Ensure project root is on path so backend.config resolves in agent venv.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import asyncio
import os

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

logger = structlog.get_logger()

# ── Required env vars ───────────────────────────────────────────────────────

_REQUIRED_VARS = [
    "VOBIZ_SIP_DOMAIN",
    "VOBIZ_SIP_USERNAME",
    "VOBIZ_SIP_PASSWORD",
    "VOBIZ_DID_NUMBER",
    "VOBIZ_PARTNER_AUTH_ID",
    "VOBIZ_PARTNER_AUTH_TOKEN",
    "VOBIZ_TRUNK_ID",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
]

_OUTBOUND_TRUNK_NAME = "Vachanam-Vobiz"
_INBOUND_TRUNK_NAME = "Vachanam-Vobiz-Inbound"

# ── Secret masking helpers ──────────────────────────────────────────────────


def _mask_password(value: str) -> str:
    """Completely mask sensitive credentials."""
    return "***"


def _mask_id(value: str) -> str:
    """Show only last 4 characters of an ID/token."""
    if len(value) <= 4:
        return "****"
    return f"...{value[-4:]}"


# ── Env validation ──────────────────────────────────────────────────────────


def _validate_env() -> dict[str, str]:
    """Read and validate all required env vars.

    Exits with sys.exit(1) and a per-var error message on any missing var.
    Returns a dict of all required var values.
    """
    missing: list[str] = []
    values: dict[str, str] = {}

    for var in _REQUIRED_VARS:
        val = os.environ.get(var, "").strip()
        if not val:
            missing.append(var)
        else:
            values[var] = val

    if missing:
        for var in missing:
            print(f"[ERROR] Missing required env var: {var}", file=sys.stderr)
        print(
            "\nFill these in .env before running this script.\n"
            "See .env.example for descriptions of each var.",
            file=sys.stderr,
        )
        sys.exit(1)

    return values


# ── LiveKit SIP URI derivation ──────────────────────────────────────────────


def derive_livekit_sip_uri(livekit_url: str) -> str:
    """Derive the plain hostname from LIVEKIT_URL for Vobiz inbound_destination.

    Vobiz expects a bare hostname with no scheme prefix.
    Per Vobiz LiveKit doc: 'NO sip: prefix — just the hostname.'

    Examples:
        wss://vachanam-agent.fly.dev   -> vachanam-agent.fly.dev
        wss://vachanam-agent.fly.dev/  -> vachanam-agent.fly.dev
        https://vachanam-agent.fly.dev -> vachanam-agent.fly.dev
    """
    # Strip any scheme (wss://, ws://, https://, http://)
    host = livekit_url
    for prefix in ("wss://", "ws://", "https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    # Strip trailing path components (shouldn't exist but be safe)
    host = host.split("/")[0]
    return host


# ── Step 1: LiveKit outbound trunk ──────────────────────────────────────────


async def provision_outbound_trunk(
    lk: object,
    sip_domain: str,
    sip_username: str,
    sip_password: str,
    did_number: str,
) -> str:
    """Create LiveKit outbound SIP trunk (idempotent by name).

    Returns the trunk ID (existing or newly created).
    Raises RuntimeError on any API failure.
    """
    from livekit.protocol.sip import (  # type: ignore[import]
        SIPOutboundTrunkInfo,
        CreateSIPOutboundTrunkRequest,
        ListSIPOutboundTrunkRequest,
    )

    # Idempotency check: list existing outbound trunks
    try:
        list_resp = await lk.sip.list_outbound_trunk(ListSIPOutboundTrunkRequest())
        for trunk in list_resp.items:
            if trunk.name == _OUTBOUND_TRUNK_NAME:
                # Check if config matches what we'd create
                addr_match = trunk.address == sip_domain
                user_match = trunk.auth_username == sip_username
                if addr_match and user_match:
                    logger.info(
                        "outbound_trunk_already_provisioned_skipping",
                        sip_trunk_id=trunk.sip_trunk_id,
                        name=trunk.name,
                    )
                    print(
                        f"[SKIP] Outbound trunk '{_OUTBOUND_TRUNK_NAME}' already exists "
                        f"(id={trunk.sip_trunk_id})"
                    )
                else:
                    logger.warning(
                        "outbound_trunk_exists_but_config_differs_skipping",
                        sip_trunk_id=trunk.sip_trunk_id,
                        existing_address=trunk.address,
                        requested_address=sip_domain,
                    )
                    print(
                        f"[WARN] Outbound trunk '{_OUTBOUND_TRUNK_NAME}' exists but address "
                        f"or credentials differ. Delete it manually then re-run.\n"
                        f"  Existing address : {trunk.address}\n"
                        f"  Requested address: {sip_domain}"
                    )
                return trunk.sip_trunk_id
    except Exception as e:
        # If list fails we can't safely dedupe — abort
        raise RuntimeError(f"Failed to list outbound trunks: {e}") from e

    # Create new outbound trunk
    try:
        trunk_info = SIPOutboundTrunkInfo(
            name=_OUTBOUND_TRUNK_NAME,
            address=sip_domain,
            auth_username=sip_username,
            auth_password=sip_password,
            numbers=[did_number],
        )
        resp = await lk.sip.create_outbound_trunk(
            CreateSIPOutboundTrunkRequest(trunk=trunk_info)
        )
        trunk_id = resp.sip_trunk_id
        logger.info(
            "outbound_trunk_created",
            sip_trunk_id=trunk_id,
            address=sip_domain,
            username=_mask_id(sip_username),
        )
        print(f"[OK]   Outbound trunk created: id={trunk_id}")
        return trunk_id
    except Exception as e:
        raise RuntimeError(f"Failed to create outbound trunk: {e}") from e


# ── Step 2: LiveKit inbound trunk ───────────────────────────────────────────


async def provision_inbound_trunk(lk: object, did_number: str) -> str:
    """Create LiveKit inbound SIP trunk (idempotent by name).

    Returns the trunk ID (existing or newly created).
    Raises RuntimeError on any API failure.
    """
    from livekit.protocol.sip import (  # type: ignore[import]
        SIPInboundTrunkInfo,
        CreateSIPInboundTrunkRequest,
        ListSIPInboundTrunkRequest,
    )

    # Idempotency check
    try:
        list_resp = await lk.sip.list_inbound_trunk(ListSIPInboundTrunkRequest())
        for trunk in list_resp.items:
            if trunk.name == _INBOUND_TRUNK_NAME:
                logger.info(
                    "inbound_trunk_already_provisioned_skipping",
                    sip_trunk_id=trunk.sip_trunk_id,
                    name=trunk.name,
                )
                print(
                    f"[SKIP] Inbound trunk '{_INBOUND_TRUNK_NAME}' already exists "
                    f"(id={trunk.sip_trunk_id})"
                )
                return trunk.sip_trunk_id
    except Exception as e:
        raise RuntimeError(f"Failed to list inbound trunks: {e}") from e

    # Create new inbound trunk
    try:
        trunk_info = SIPInboundTrunkInfo(
            name=_INBOUND_TRUNK_NAME,
            numbers=[did_number],
            allowed_addresses=["0.0.0.0/0"],
        )
        resp = await lk.sip.create_inbound_trunk(
            CreateSIPInboundTrunkRequest(trunk=trunk_info)
        )
        trunk_id = resp.sip_trunk_id
        logger.info("inbound_trunk_created", sip_trunk_id=trunk_id, did=did_number[-4:])
        print(f"[OK]   Inbound trunk created:  id={trunk_id}")
        return trunk_id
    except Exception as e:
        raise RuntimeError(f"Failed to create inbound trunk: {e}") from e


# ── Step 3: LiveKit dispatch rule ───────────────────────────────────────────


async def provision_dispatch_rule(lk: object, inbound_trunk_id: str) -> str:
    """Create LiveKit SIP dispatch rule (idempotent: skip if one already targets our inbound trunk).

    Returns the dispatch rule ID (existing or newly created).
    Raises RuntimeError on any API failure.
    """
    from livekit.protocol.sip import (  # type: ignore[import]
        CreateSIPDispatchRuleRequest,
        ListSIPDispatchRuleRequest,
        SIPDispatchRule,
        SIPDispatchRuleIndividual,
    )
    from livekit.protocol.room import RoomConfiguration  # type: ignore[import]
    from livekit.protocol.agent_dispatch import RoomAgentDispatch  # type: ignore[import]

    # Idempotency check: skip if any dispatch rule already targets our inbound trunk
    try:
        list_resp = await lk.sip.list_dispatch_rule(ListSIPDispatchRuleRequest())
        for rule in list_resp.items:
            if inbound_trunk_id in list(rule.trunk_ids):
                logger.info(
                    "dispatch_rule_already_exists_for_inbound_trunk_skipping",
                    dispatch_rule_id=rule.sip_dispatch_rule_id,
                    inbound_trunk_id=inbound_trunk_id,
                )
                print(
                    f"[SKIP] Dispatch rule already targets inbound trunk "
                    f"(rule_id={rule.sip_dispatch_rule_id})"
                )
                return rule.sip_dispatch_rule_id
    except Exception as e:
        raise RuntimeError(f"Failed to list dispatch rules: {e}") from e

    # Create dispatch rule: individual rooms with prefix "call-", agent "voice-assistant"
    try:
        rule = SIPDispatchRule(
            dispatch_rule_individual=SIPDispatchRuleIndividual(room_prefix="call-")
        )
        room_config = RoomConfiguration(
            agents=[RoomAgentDispatch(agent_name="voice-assistant")]
        )
        req = CreateSIPDispatchRuleRequest(
            rule=rule,
            trunk_ids=[inbound_trunk_id],
            room_config=room_config,
        )
        resp = await lk.sip.create_dispatch_rule(req)
        rule_id = resp.sip_dispatch_rule_id
        logger.info(
            "dispatch_rule_created",
            dispatch_rule_id=rule_id,
            inbound_trunk_id=inbound_trunk_id,
            agent_name="voice-assistant",
        )
        print(f"[OK]   Dispatch rule created:  id={rule_id}")
        return rule_id
    except Exception as e:
        raise RuntimeError(f"Failed to create dispatch rule: {e}") from e


# ── Step 4: Vobiz inbound_destination PUT ───────────────────────────────────

# Vobiz trunk IDs are UUIDs per API docs.
# Ref: https://docs.vobiz.ai/trunks/update-trunk (bfab10fb-cb97-488b-9c63-989c32980b0f)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def patch_vobiz_inbound_destination(
    auth_id: str,
    auth_token: str,
    vobiz_trunk_id: str,
    livekit_sip_uri: str,
) -> None:
    """PUT Vobiz trunk to point inbound calls at the LiveKit SIP URI (idempotent).

    Idempotency: GETs the trunk first; if inbound_destination already matches,
    skips the PUT.
    Raises RuntimeError on HTTP error or unexpected response.

    Per https://docs.vobiz.ai/trunks/update-trunk — Vobiz uses PUT (not PATCH)
    and the URL must have NO trailing slash.
    """
    # No trailing slash — Vobiz router returns 400 "account ID required in path" otherwise.
    base_url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{vobiz_trunk_id}"
    headers = {
        "X-Auth-ID": auth_id,
        "X-Auth-Token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Soft UUID format warning — Vobiz trunk IDs are UUIDs; non-UUID IDs may 404.
    if not _UUID_RE.match(vobiz_trunk_id):
        print(
            f"[WARN] VOBIZ_TRUNK_ID does not look like a UUID "
            f"(got: '...{vobiz_trunk_id[-4:]}'). "
            f"Vobiz trunk IDs are UUIDs like 'bfab10fb-cb97-488b-9c63-989c32980b0f'. "
            f"If Vobiz returns 404 on Step 4, check the trunk ID in Vobiz console."
        )

    async with httpx.AsyncClient(timeout=30) as client:
        # Idempotency GET
        try:
            get_resp = await client.get(base_url, headers=headers)
            get_resp.raise_for_status()
            trunk_data = get_resp.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Vobiz GET trunk failed (HTTP {e.response.status_code}): {e.response.text}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Vobiz GET trunk failed: {e}") from e

        current_destination = trunk_data.get("inbound_destination", "")
        if current_destination == livekit_sip_uri:
            logger.info(
                "vobiz_inbound_destination_already_set_skipping",
                inbound_destination=livekit_sip_uri,
            )
            print(f"[SKIP] Vobiz inbound_destination already set to: {livekit_sip_uri}")
            return

        # PUT with new destination (Vobiz uses PUT, not PATCH)
        try:
            put_resp = await client.put(
                base_url,
                headers=headers,
                json={"inbound_destination": livekit_sip_uri},
            )
            put_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Vobiz PUT trunk failed (HTTP {e.response.status_code}): {e.response.text}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Vobiz PUT trunk failed: {e}") from e

        logger.info(
            "vobiz_inbound_destination_updated",
            inbound_destination=livekit_sip_uri,
            previous=current_destination or "(empty)",
        )
        print(f"[OK]   Vobiz inbound_destination set to: {livekit_sip_uri}")


# ── Step 5: Verification summary ────────────────────────────────────────────


def print_summary(
    outbound_trunk_id: str,
    inbound_trunk_id: str,
    dispatch_rule_id: str,
    livekit_sip_uri: str,
) -> None:
    """Print a verification summary table + the first-call test command."""
    print("\n" + "=" * 64)
    print("  VACHANAM VOBIZ PROVISIONING SUMMARY")
    print("=" * 64)
    print(f"  Outbound trunk LiveKit ID  : {outbound_trunk_id}")
    print(f"  Inbound trunk LiveKit ID   : {inbound_trunk_id}")
    print(f"  Dispatch rule ID           : {dispatch_rule_id}")
    print(f"  Vobiz inbound_destination  : {livekit_sip_uri}")
    print(f"  Agent name (expected)      : voice-assistant")
    print("=" * 64)
    print("\nFirst-call test command (replace phone with a real test number):")
    print(
        f"  lk sip make-call \\\n"
        f"    --trunk-id={outbound_trunk_id} \\\n"
        f"    --to=+91XXXXXXXXXX \\\n"
        f"    --room=call-test01"
    )
    print(
        "\nNote: LiveKit must be reachable from Vobiz SIP servers. "
        "Ensure port 5060/TCP+UDP (SIP) and 10000-20000/UDP (RTP/SRTP) "
        "are open in Fly.io firewall rules before making a real call.\n"
    )


# ── Main ────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("Vachanam Vobiz + LiveKit SIP trunk provisioning")
    print("-" * 48)

    env = _validate_env()

    sip_domain = env["VOBIZ_SIP_DOMAIN"]
    sip_username = env["VOBIZ_SIP_USERNAME"]
    sip_password = env["VOBIZ_SIP_PASSWORD"]
    did_number = env["VOBIZ_DID_NUMBER"]
    partner_auth_id = env["VOBIZ_PARTNER_AUTH_ID"]
    partner_auth_token = env["VOBIZ_PARTNER_AUTH_TOKEN"]
    vobiz_trunk_id = env["VOBIZ_TRUNK_ID"]
    livekit_url = env["LIVEKIT_URL"]
    livekit_api_key = env["LIVEKIT_API_KEY"]
    livekit_api_secret = env["LIVEKIT_API_SECRET"]

    # MA_ prefix guard — fail fast before any network call.
    # Vobiz Partner auth IDs always start with "MA_" (format: MA_XXXXXX).
    # If the wrong field was pasted from the Vobiz console, reject immediately.
    if not partner_auth_id.startswith("MA_"):
        logger.error(
            "invalid_vobiz_auth_id_format",
            first_three_chars=partner_auth_id[:3] if partner_auth_id else "",
        )
        print(
            f"[FATAL] VOBIZ_PARTNER_AUTH_ID must start with 'MA_' "
            f"(format: MA_XXXXXX from Vobiz console credentials page).\n"
            f"Got value starting with: '{partner_auth_id[:3] if partner_auth_id else '<empty>'}...'\n"
            f"Check .env — likely you pasted the wrong field from Vobiz console.\n"
            f"See https://docs.vobiz.ai/quick-start for credentials location."
        )
        sys.exit(1)

    # Soft UUID format warning for VOBIZ_TRUNK_ID — warn here too (before any
    # network call) so the operator sees it prominently alongside other config.
    if not _UUID_RE.match(vobiz_trunk_id):
        print(
            f"[WARN] VOBIZ_TRUNK_ID does not look like a UUID "
            f"(got: '...{vobiz_trunk_id[-4:]}'). "
            f"Vobiz trunk IDs are UUIDs like 'bfab10fb-cb97-488b-9c63-989c32980b0f'. "
            f"If Vobiz returns 404 on Step 4, check the trunk ID in Vobiz console."
        )

    # Derive LiveKit SIP hostname (no scheme, no sip: prefix) for Vobiz
    livekit_sip_uri = derive_livekit_sip_uri(livekit_url)

    print(f"  SIP domain       : {sip_domain}")
    print(f"  SIP username     : {_mask_id(sip_username)}")
    print(f"  SIP password     : {_mask_password(sip_password)}")
    print(f"  DID number       : ...{did_number[-4:]}")
    print(f"  Partner auth ID  : {_mask_id(partner_auth_id)}")
    print(f"  Partner token    : {_mask_password(partner_auth_token)}")
    print(f"  Vobiz trunk ID   : {_mask_id(vobiz_trunk_id)}")
    print(f"  LiveKit URL      : {livekit_url}")
    print(f"  LiveKit SIP URI  : {livekit_sip_uri}")
    print()

    # Import LiveKitAPI here — allows the module to be imported (for tests) without
    # livekit installed at import time; fails fast at runtime if missing.
    try:
        from livekit.api import LiveKitAPI  # type: ignore[import]
    except ImportError as exc:
        print(
            "[ERROR] livekit-api package not found. "
            "Install via: pip install livekit-api>=0.7",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    lk = LiveKitAPI(url=livekit_url, api_key=livekit_api_key, api_secret=livekit_api_secret)

    try:
        # ── Step 1: Outbound trunk ──────────────────────────────────────────
        print("Step 1: Provisioning LiveKit outbound trunk...")
        outbound_trunk_id = await provision_outbound_trunk(
            lk=lk,
            sip_domain=sip_domain,
            sip_username=sip_username,
            sip_password=sip_password,
            did_number=did_number,
        )

        # ── Step 2: Inbound trunk ───────────────────────────────────────────
        print("Step 2: Provisioning LiveKit inbound trunk...")
        inbound_trunk_id = await provision_inbound_trunk(lk=lk, did_number=did_number)

        # ── Step 3: Dispatch rule ───────────────────────────────────────────
        print("Step 3: Provisioning LiveKit dispatch rule...")
        dispatch_rule_id = await provision_dispatch_rule(
            lk=lk, inbound_trunk_id=inbound_trunk_id
        )

        # ── Step 4: Vobiz inbound_destination PUT ──────────────────────────
        print("Step 4: Updating Vobiz trunk inbound_destination (PUT)...")
        await patch_vobiz_inbound_destination(
            auth_id=partner_auth_id,
            auth_token=partner_auth_token,
            vobiz_trunk_id=vobiz_trunk_id,
            livekit_sip_uri=livekit_sip_uri,
        )

        # ── Step 5: Summary ─────────────────────────────────────────────────
        print_summary(
            outbound_trunk_id=outbound_trunk_id,
            inbound_trunk_id=inbound_trunk_id,
            dispatch_rule_id=dispatch_rule_id,
            livekit_sip_uri=livekit_sip_uri,
        )

    except RuntimeError as e:
        logger.error("provisioning_failed", error=str(e))
        print(f"\n[FATAL] {e}", file=sys.stderr)
        raise SystemExit(1) from e
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
