# scripts/

Offline utility scripts for Vachanam. Run from the project root with the
agent virtual environment active unless noted otherwise.

---

## generate_clinic_greeting.py

Generates a per-branch pre-cached greeting WAV via Sarvam Bulbul TTS.
Called during clinic onboarding to pre-warm the <100ms first-word latency
on SIP pickup (Component 4 of the voice call flow spec).

Pre-reqs: `SARVAM_API_KEY` set in `.env`.

```bash
python scripts/generate_clinic_greeting.py \
    --branch-id <uuid> --clinic-name "ABC Hospital"
```

Output: `backend/static/greetings/<branch_id>.wav`

---

## provision_vobiz_trunk.py

One-shot idempotent Vobiz + LiveKit SIP trunk wiring. Run once after
completing Step 1 in the Vobiz console (creating the SIP trunk manually).

### Pre-requisites

All 10 env vars below must be set in `.env` before running:

| Var | Description |
|---|---|
| `VOBIZ_SIP_DOMAIN` | SIP domain, e.g. `abc123.sip.vobiz.ai` |
| `VOBIZ_SIP_USERNAME` | SIP trunk auth username from Vobiz console |
| `VOBIZ_SIP_PASSWORD` | SIP trunk auth password from Vobiz console |
| `VOBIZ_DID_NUMBER` | E.164 DID, e.g. `+914066XXXXXX` |
| `VOBIZ_PARTNER_AUTH_ID` | Vobiz master partner account ID |
| `VOBIZ_PARTNER_AUTH_TOKEN` | Vobiz master partner token |
| `VOBIZ_TRUNK_ID` | Vobiz internal trunk ID — find it in Vobiz console under Telephony -> SIP Trunks -> your trunk detail page URL or info panel |
| `LIVEKIT_URL` | e.g. `wss://vachanam-agent.fly.dev` |
| `LIVEKIT_API_KEY` | from LiveKit server setup |
| `LIVEKIT_API_SECRET` | from LiveKit server setup |

### How to run

```bash
python scripts/provision_vobiz_trunk.py
```

No flags needed. The script reads from `.env` automatically.

### What it does

1. Creates a LiveKit **outbound** SIP trunk (`Vachanam-Vobiz`) pointing at Vobiz
2. Creates a LiveKit **inbound** SIP trunk (`Vachanam-Vobiz-Inbound`) for your DID
3. Creates a LiveKit **dispatch rule** — rooms prefixed `call-`, agent `voice-assistant`
4. PATCHes the Vobiz trunk `inbound_destination` to the LiveKit SIP hostname
5. Prints a verification summary and the first-call test command

### What is idempotent (safe to re-run)

- Steps 1-3: if a resource with the same name (or same inbound trunk ID) already
  exists, it is skipped with a `[SKIP]` message — no duplicate is created.
- Step 4: if Vobiz `inbound_destination` already matches, PATCH is skipped.

### What is NOT idempotent (one-time manual actions in Vobiz console)

- Creating the SIP trunk in Vobiz console (Telephony -> Outbound Trunks -> Create Trunk)
- Purchasing the DID number in Vobiz console

### How to teardown and re-provision

```bash
# Delete LiveKit resources via lk CLI
lk sip outbound delete <outbound_trunk_id>
lk sip inbound delete <inbound_trunk_id>
lk sip dispatch delete <dispatch_rule_id>

# Then re-run the script to recreate
python scripts/provision_vobiz_trunk.py
```

### Firewall requirements (Vinay must action before first real call)

LiveKit (Fly.io bom) must accept inbound connections from Vobiz SIP servers:

| Port range | Protocol | Purpose |
|---|---|---|
| 5060 | TCP + UDP | SIP signalling |
| 10000-20000 | UDP | RTP / SRTP media streams |

Add these in the Fly.io dashboard under your app's networking settings, or via
`fly ips` + firewall rule additions. Vobiz SIP server IPs are listed in the
Vobiz console under Account -> SIP Infrastructure.

### Example output (credentials masked)

```
Vachanam Vobiz + LiveKit SIP trunk provisioning
------------------------------------------------
  SIP domain       : abc123.sip.vobiz.ai
  SIP username     : ...X123
  SIP password     : ***
  DID number       : ...0042
  Partner auth ID  : ...AB12
  Partner token    : ***
  Vobiz trunk ID   : ...7890
  LiveKit URL      : wss://vachanam-agent.fly.dev
  LiveKit SIP URI  : vachanam-agent.fly.dev

Step 1: Provisioning LiveKit outbound trunk...
[OK]   Outbound trunk created:  id=TR_xxxxxxxxxxxxxxxx
Step 2: Provisioning LiveKit inbound trunk...
[OK]   Inbound trunk created:   id=TR_yyyyyyyyyyyyyy
Step 3: Provisioning LiveKit dispatch rule...
[OK]   Dispatch rule created:   id=DR_zzzzzzzzzzzzzz
Step 4: Patching Vobiz trunk inbound_destination...
[OK]   Vobiz inbound_destination set to: vachanam-agent.fly.dev

================================================================
  VACHANAM VOBIZ PROVISIONING SUMMARY
================================================================
  Outbound trunk LiveKit ID  : TR_xxxxxxxxxxxxxxxx
  Inbound trunk LiveKit ID   : TR_yyyyyyyyyyyyyy
  Dispatch rule ID           : DR_zzzzzzzzzzzzzz
  Vobiz inbound_destination  : vachanam-agent.fly.dev
  Agent name (expected)      : voice-assistant
================================================================

First-call test command (replace phone with a real test number):
  lk sip make-call \
    --trunk-id=TR_xxxxxxxxxxxxxxxx \
    --to=+91XXXXXXXXXX \
    --room=call-test01
```
