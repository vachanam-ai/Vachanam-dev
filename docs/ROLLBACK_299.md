# Rollback runbook — #299 "let Postgres sleep"

**Decision (Vinay, 2026-07-09):** ship #299, test it live. If the cold-wake pause
on the first call after an idle stretch is unacceptable, roll back and pay Neon
~$19/mo for an always-on compute. Cost is the cheaper problem.

## What #299 changed

| | Before (`rollback/pre-299`) | After (`deploy/299`) |
|---|---|---|
| Agent `db_keepalive` | pings Neon every 180s → compute **on 24/7** | **deleted** |
| `calendar_writer` | 30s Postgres query | 60s **Redis** read, Postgres only when due |
| `pre_appt_reminders` | 60s Postgres query | 60s **Redis** read, Postgres only when due |
| `cascade_rebook` | 60s Postgres query | 60s **Redis** read, Postgres only when due |
| `next_visit_followups` | 5 min Postgres query | **Redis** read, Postgres only when due |
| `requeue_stale`, `finalize_stale`, `call_scoring`, `vobiz_cdr_sync` (3 min!) | 4 staggered wakes ≈ 20 min compute/hr | **one hourly wake** ≈ 5 min |
| Dead DB during a call | endless ringing (entrypoint crashed) | answers, speaks "call the clinic directly", hangs up (#298) |

Neon keeps compute alive **5 minutes after any query**, and that timeout cannot be
shortened. So cost is driven by the NUMBER of distinct wakes, not their frequency.

## The symptom that justifies rolling back

**First call after >5 min of silence takes ~2.1s longer to answer** (Neon cold
wake, measured). A clinic with steady calls never sees it — any call within 5
minutes of the last query lands on warm compute.

Check it, don't guess:

```bash
flyctl logs -a vachanam-agent --no-tail | grep lat_pre_session_build
```

`lat_pre_session_build` is answer→build. Cold ≈ 2–4.5s; warm ≈ 0.3s.

## Roll back (keeps every other fix — #279…#297 stay)

`rollback/pre-299` is the commit immediately before #298/#299. Reverting the one
commit is safer than resetting the branch.

```bash
# 1) API (Render) — this is where the schedulers live, and the cost.
git checkout master
git revert --no-edit cf06895      # the #298+#299 commit
git push origin master            # Render auto-deploys

# 2) Agent (Fly) — restores db_keepalive. MUST deploy from a master tree.
git branch --show-current         # ← MUST print "master" before deploying.
                                  #   flyctl builds the WORKING TREE, not the ref.
flyctl deploy -c infra/fly.agent.toml -a vachanam-agent --strategy immediate
```

Alternative for the agent only (no code change): roll the Fly release back.
`v95` is the last pre-#299 agent.

```bash
flyctl releases -a vachanam-agent
flyctl deploy -c infra/fly.agent.toml -a vachanam-agent --image <v95 image ref>
```

Reverting also restores the pre-#298 behaviour, where a dead DB leaves callers
ringing. If you want the cost rollback but KEEP the graceful-outage fix, revert
only the #299 hunks (wake_gate, maintenance.py, main.py schedule, keepalive) and
leave `_end_call_with_notice` in place.

## Nothing to undo outside git

- **No migrations.** #298/#299 changed zero schema.
- **Redis keys** (`wake:next_at:*`) are self-expiring state; harmless if left.
- **Neon settings** (min 0.25 / max 2 CU / scale-to-zero 5 min) stay valid either
  way. Rolling back only means the keepalive stops it ever suspending.

## What to watch for 24h

1. **Reminders still fire.** The one thing that must not regress.
   `flyctl logs -a vachanam-agent --no-tail | grep -i reminder`
2. **Neon compute-hours** in the Neon console — expect a sharp drop toward
   ~1 wake/hour. Projected idle cost ≈ $1.60/mo.
3. **Cold-wake latency** on the first call of the morning (`lat_pre_session_build`).

If reminders miss, that is NOT a "wait and see" — roll back immediately. The gate
fails open by design, so a miss means a real bug, not a tuning problem.
