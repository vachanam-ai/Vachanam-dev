# TTS sandbox — Cartesia instead of Soniox

Vinay 2026-08-07: *"create a sandbox and replace TTS with Cartesia instead of
soniox and integrate it with Venkateshwara clinic number. just a test sandbox
without disturbing existing things."*

## What it is

The **same agent code** as production with explicit sandbox-only providers:

| | production | sandbox |
|---|---|---|
| Fly app | `vachanam-agent` | `vachanam-agent-sandbox` |
| `STT_PROVIDER` | `soniox` | `soniox` |
| `LLM_PROVIDER` | `gemini` | `livekit` |
| LLM | cached Gemini 2.5 Flash | LiveKit Gemini 3.5 Flash-Lite |
| Fly region | Mumbai | Mumbai |
| `TTS_PROVIDER` | unset (→ soniox) | `cartesia` |
| `LIVEKIT_AGENT_NAME` | unset (→ `vachanam-agent`) | `vachanam-sandbox` |

Prompts, booking tools, and the database are shared. The sandbox intentionally
changes LLM and TTS while its app, worker name, and DID dispatch isolate it.

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

The routing script also refuses to move a DID unless `flyctl machine list`
proves at least one sandbox machine is started. This prevents the old
"nobody answers" failure where routing changed before a worker existed.

## Pointing a clinic number at it

This is the one step that touches live routing, so it is deliberate and
reversible. The clinic's DID dispatch rule names an agent; switching it sends
**every** call on that number to the sandbox, including a real patient's.

```bash
# Look at the current rule first, and SAVE the output — it is your rollback.
python scripts/route_venkateshwara_tts_sandbox.py status

python scripts/route_venkateshwara_tts_sandbox.py apply venkateshwara

# Investor demo DID
python scripts/route_venkateshwara_tts_sandbox.py apply skincare
```

**Do it when the clinic is closed**, make your test calls, then put it back:

```bash
python scripts/route_venkateshwara_tts_sandbox.py revert venkateshwara
python scripts/route_venkateshwara_tts_sandbox.py revert skincare
python scripts/route_venkateshwara_tts_sandbox.py status
```

Allowed clinic keys are intentionally hard-coded in `CLINICS`; an arbitrary
number can never be moved by a typo. `skincare` is also available. Each clinic
gets its own trunk/rule pair and can be reverted independently.

Safer alternative if you have a spare DID: point the **test** number at
`vachanam-sandbox` and leave the clinic's number alone entirely. Then nothing
about the live line changes at any point.

## What to listen for

Cartesia and Soniox differ most where our calls actually live:

- **Telugu pronunciation** of doctor names and clinic words
- **Time to first audio** — compare `lat_tts` / `lat_*` in both apps' logs
- **Numbers**: "10:30", ages, token numbers (the `padi am` class of bug)
- Whether it handles the sentence tokenizer's short first sentence naturally
- Switch every supported language using short natural phrases: "English
  please", "Hindi mein", "Telugu lo", "Tamil la", "Kannada dalli",
  "Malayalam il", "Marathi madhe", and "Bangla te"
- Book, reschedule, then cancel from the same caller number; verify every
  success against the database/transcript, never only by what the model says

The investor sandbox uses `CARTESIA_MIN_SENTENCE_LEN=4` so short acknowledgments
reach TTS earlier. Production Soniox remains at `min_sentence_len=8`.

## Turning it off

Stop the sandbox machine — it costs money and does nothing when idle:

```bash
flyctl scale count 0 -a vachanam-agent-sandbox
```

Production never referenced it, so there is nothing else to undo. If you want
Cartesia in production later, that is a separate decision: flip `TTS_PROVIDER`
on the real app after a real-call comparison, with the same kill switch.
