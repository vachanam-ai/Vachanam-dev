# Agent deploy ritual (Fly)

Every `flyctl deploy --config infra/fly.agent.toml --remote-only` MUST end
with a registration check — the deploy succeeding is NOT the line being up.

## Why (LK checklist, 2026-07-20)

livekit-agents 1.6.5 intermittently hangs worker registration after a deploy:
the process boots, plugins load, prewarm runs — and the worker↔LiveKit Cloud
WebSocket never completes, with no error logged. Two prod incidents
(2026-07-19 12:06Z → 4 h dead line; 2026-07-19 19:01Z → 9 h) lost three
treatment follow-up calls before the safety net existed.

## The check (do this after EVERY agent deploy)

```
flyctl logs -a vachanam-agent --no-tail | grep "registered worker" | tail -1
```

Fresh timestamp (within ~2 min of the deploy) = line up. No fresh line within
3 minutes → `flyctl machine restart <id> -a vachanam-agent` (a restart has
fixed registration every time), then re-check. Fly's log stream is LOSSY —
when in doubt, trust the Redis truth-mirror instead:
`watchdog:lk:agent_state` = `registered:<epoch>` refreshed every 60 s
(surfaced on the admin health board as `lk_registration`).

## Safety net layers (if the ritual is forgotten)

1. #411 — heartbeat beacon is gated on registration; unregistered worker →
   beacon stops → watchdog auto-restarts the machine in ~3 min
   (needs FLY_API_TOKEN in Render env).
2. LK-5 — a silently dropped WebSocket (SDK "failed to connect to livekit"
   reconnect warning) also clears the beacon gate.
3. #423 — every outbound dispatch (follow-up / reminder / rebook) is verified
   JOINED; unclaimed → room deleted, task retries next tick, and the
   watchdog restart is triggered immediately (LK-3) — an unclaimed dispatch
   is the definitive dead-line probe.

## Open item (LK-7)

Watch the next 3 deploys. If a registration hang recurs, `watchdog:lk:agent_state`
now gives lossless evidence (log-loss vs gate-leak is settled). Next step then:
upgrade livekit-agents past 1.6.5 after checking its changelog for worker
registration fixes.
