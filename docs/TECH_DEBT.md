# Vachanam — Technical Debt Ledger

Every shortcut taken in this project is logged here with severity and a payback plan. Manager updates this on every sprint. If a row sits with no payback for too long, it gets escalated to the client.

A debt row stays until paid down. When paid down, move it to the "Paid down" section at the bottom with the date and the commit hash.

---

## Severity guide

| Level | What it means | Payback window |
|---|---|---|
| **P0 Critical** | Data leak risk, payment correctness risk, compliance risk | Same sprint, no exceptions |
| **P1 High** | Production-affecting if not addressed before scale | Within 2 sprints |
| **P2 Medium** | Affects developer velocity / maintenance cost | Within the current phase |
| **P3 Low** | Cosmetic / convenience | When touching the code anyway |

---

## Open debt

| ID | Severity | Date added | Owner specialist | Description | Why it was taken | Payback plan | Target sprint |
|---|---|---|---|---|---|---|---|
| TD-001 | P1 | 2026-05-22 | database-engineer | Alembic migration `2fe8f201bc31_initial_schema.py` (2026-05-15) predates the User table + 7 schema field additions on 2026-05-22 | Schema changed mid-stream; no migration was regenerated | Generate follow-up migration during Phase 4 Task 1; never edit the original | Phase 4 |
| TD-002 | P2 | 2026-05-22 | backend-engineer | `backend/payments_test_app.py` standalone FastAPI exists only because `backend/main.py` doesn't yet | Razorpay integration shipped before backend core | Delete during Phase 4 Task 7 when main.py is built and includes payments router | Phase 4 |
| TD-003 | P2 | 2026-05-22 | backend-engineer | Starter price on landing page mirror is ₹99 instead of canonical pricing (₹1,999 or ₹6,999 depending on the pricing decision) | Self-test convenience | Restore canonical price during Phase 9 onboarding work | Phase 9 |
| TD-004 | P1 | 2026-05-22 | manager | Pricing decision unresolved: CLAUDE.md says Solo/Clinic/Multi ₹1,999/₹7,999/₹16,999 ; vachanam.in live shows Starter/Growth/Unlimited ₹6,999/₹9,999/₹14,999 | Two parallel marketing experiments before MVP scope locked | Client decision required before Phase 9; manager to escalate | Before Phase 9 |
| TD-005 | P3 | 2026-05-22 | voice-agent-engineer | Emergency keyword `padipōyāḍu` (romanized Telugu) may not match Sarvam STT output (could need Telugu script `పడిపోయాడు`) | Easier to read in code; STT output not yet verified with real call | Verify on first real call in Phase 10; add Telugu script alongside if needed | Phase 10 |
| TD-006 | P2 | 2026-05-22 | tester | Integration + edge-case tests committed but not executed in last session (Docker not started) | Session ended before verification | Manager dispatches `tester` to spin up docker-compose + run full suite as first Phase 4 task | Phase 4 |
| TD-007 | **P0** | 2026-05-29 | voice-agent-engineer | `agent/agent.py` defines `_llm_with_fallback` (Gemini → GPT-4o-mini) but the actual session LLM is raw `google.LLM` — fallback never fires. Violates CLAUDE.md Rule 9. | Discovered in full project audit | Implement custom LLM adapter for livekit.agents OR wrap session LLM with try/except + reset. Requires reading LiveKit Agents 1.4 custom LLM provider API. | Fix sprint (before Phase 5) |
| TD-008 | **P0** | 2026-05-29 | voice-agent-engineer | `agent/agent.py` calls `session.disconnect()` — method may not exist in LiveKit Agents 1.4 (likely `aclose()`). Will crash on first real call. | Discovered in full project audit | Verify against livekit-agents>=1.4.0 docs; replace with correct method | Fix sprint (before Phase 5) |
| TD-009 | P1 | 2026-05-29 | voice-agent-engineer | SOLO 4-min cap only fires inside `on_user_turn_completed`. If patient goes silent at 3:55, cap never enforced → billing-correctness risk. | Discovered in full project audit | Add background asyncio polling task in `entrypoint` that checks `elapsed_seconds` every 5s independent of user activity | Fix sprint (before Phase 5) |
| TD-010 | P2 | 2026-05-29 | tester | `tests/edge_cases/test_concurrent_tokens.py` runs N=5; tester.md rule requires N≥100 for concurrency tests. Current passes only because Redis INCR is atomic; not exposing real contention. | Initial test was MVP; rule introduced after | Bump to N=100; add limit-boundary variant pre-filling 99 then 10 concurrent → exactly 1 success | Fix sprint |
| TD-011 | P3 | 2026-05-29 | tester | `tests/conftest.py:27` hardcodes `redis://localhost:6379` instead of `settings.redis_url`. Violates "no hardcoded URLs" rule. | Initial conftest was MVP | Replace with `settings.redis_url`, matching the existing db fixture pattern | Fix sprint |
| TD-012 | P2 | 2026-05-29 | tester | `tests/conftest.py` redis fixture flushes AFTER test only. Silent test pollution if previous test leaked. | Initial conftest was MVP | Flush BEFORE the yield as well | Fix sprint |
| TD-013 | P2 | 2026-05-29 | manager | 5 obsolete root-level PHASE_*.md files + `docs/vachanam-progress.md` + old `docs/superpowers/plans/2026-05-18-phase-2-backend.md` coexist with new canonical structure. Anyone reading the repo cold cannot tell which is authoritative. | Refactor on 2026-05-22 created new structure but did not archive the old | Move all to `docs/_legacy/` with a README explaining "kept for archaeology — canonical truth is docs/STATUS.md" | Fix sprint |
| TD-014 | P2 | 2026-05-29 | devops-engineer | `infra/Dockerfile.agent` and `infra/Dockerfile.backend` do NOT use a non-root user. `QUALITY_BAR.md` requires `USER app` after install. | Initial Dockerfiles were MVP; rule introduced after | Add `RUN groupadd -r app && useradd -r -g app ...` + `COPY --chown=app:app` + `USER app` to both Dockerfiles | Before Phase 10 |
| TD-015 | P1 | 2026-05-29 | devops-engineer | No GitHub Actions CI workflow yet — no automated test on PR, no secret-scan job. Secrets could land in repo undetected. | Not yet built | Add `.github/workflows/ci.yml` with pytest + secret-scan job | Phase 4.5 |

---

## Paid down

(Empty — first sprint after introducing TECH_DEBT.md)

When closing a row, move it here with this format:
```
| TD-XXX | severity | date paid | commit hash | how it was resolved |
```

---

## Rules

- Every shortcut creates a row here — no silent shortcuts
- Every row has an owner specialist and target sprint
- Manager reviews open debt every sprint planning
- P0 debt that misses its sprint = escalation to client
- P1 debt overdue twice = escalation
- Paid-down rows are NEVER deleted — they're moved to the bottom for historical record
- When a row blocks a feature, link the feature task to this row
