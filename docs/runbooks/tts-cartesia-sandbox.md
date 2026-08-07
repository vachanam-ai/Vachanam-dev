# TTS sandbox — Cartesia instead of Soniox

Vinay 2026-08-07: *"create a sandbox and replace TTS with Cartesia instead of
soniox and integrate it with Venkateshwara clinic number. just a test sandbox
without disturbing existing things."*

## What it is

The **same agent code** as production with two environment variables flipped:

| | production | sandbox |
|---|---|---|
| Fly app | `vachanam-agent` | `vachanam-agent-sandbox` |
| `TTS_PROVIDER` | unset (→ soniox) | `cartesia` |
| `LIVEKIT_AGENT_NAME` | unset (→ `vachanam-agent`) | `vachanam-sandbox` |

Everything else — STT, LLM, prompts, booking, the database — is identical, so
what you hear differs **only** because of the voice engine.

## Why the separate agent name matters

LiveKit dispatches a call to any worker registered under the name the dispatch
rule asks for. If the sandbox registered as `vachanam-agent`, **both** workers
would be eligible for every real call and roughly half your patients would get
the sandbox. The distinct name is what makes this safe.

## Deploy

```bash
flyctl apps create vachanam-agent-sandbox            # first time only

# Same secrets as prod, plus Cartesia. Copy the values from the prod app.
flyctl secrets set -a vachanam-agent-sandbox \
  CARTESIA_API_KEY=... LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... \
  DATABASE_URL=... REDIS_URL=... GEMINI_API_KEY=... SONIOX_JP_API_KEY=...

flyctl deploy --config infra/fly.agent-sandbox.toml --remote-only
```

Confirm it came up as the sandbox, not as prod:

```bash
flyctl logs -a vachanam-agent-sandbox | grep -E "registered worker|tts_provider_cartesia"
```

You want `agent_name: vachanam-sandbox`. If it says `vachanam-agent`, **stop**
— `LIVEKIT_AGENT_NAME` did not apply and the sandbox is competing for real
calls.

## Pointing the Venkateshwara number at it

This is the one step that touches live routing, so it is deliberate and
reversible. The clinic's DID dispatch rule names an agent; switching it sends
**every** call on that number to the sandbox, including a real patient's.

```bash
# Look at the current rule first, and SAVE the output — it is your rollback.
lk sip dispatch-rule list

# Repoint that rule's room_config agent name to: vachanam-sandbox
# (edit + re-create the rule; note the rule id you replaced)
```

**Do it when the clinic is closed**, make your test calls, then put it back:

```bash
# Restore the saved rule so the number points at vachanam-agent again.
lk sip dispatch-rule list   # verify it reads vachanam-agent
```

Safer alternative if you have a spare DID: point the **test** number at
`vachanam-sandbox` and leave the clinic's number alone entirely. Then nothing
about the live line changes at any point.

## What to listen for

Cartesia and Soniox differ most where our calls actually live:

- **Telugu pronunciation** of doctor names and clinic words
- **Time to first audio** — compare `lat_tts` / `lat_*` in both apps' logs
- **Numbers**: "10:30", ages, token numbers (the `padi am` class of bug)
- Whether it handles the sentence tokenizer's short first sentence naturally

Both engines use the **same** sentence tokenizer (`min_sentence_len=8`), so you
are comparing engines, not two chunking strategies.

## Turning it off

Stop the sandbox machine — it costs money and does nothing when idle:

```bash
flyctl scale count 0 -a vachanam-agent-sandbox
```

Production never referenced it, so there is nothing else to undo. If you want
Cartesia in production later, that is a separate decision: flip `TTS_PROVIDER`
on the real app after a real-call comparison, with the same kill switch.
