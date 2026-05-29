# Legacy docs — historical reference only

The files in this folder were once authoritative but have been superseded by the new canonical structure introduced on 2026-05-22 and consolidated on 2026-05-29.

**Do not read these to understand the project today.** They reflect the project as planned at earlier dates, and many of their decisions, file paths, schema details, and acceptance criteria have changed.

For the current truth, read in this order:

1. [`CLAUDE.md`](../../CLAUDE.md) (root) — the law
2. [`docs/STATUS.md`](../STATUS.md) — what's done, what's broken, what's next
3. [`docs/ROADMAP.md`](../ROADMAP.md) — the 10 phases and their dependencies
4. [`docs/CHANGELOG.md`](../CHANGELOG.md) — session-by-session decision history
5. [`docs/TECH_DEBT.md`](../TECH_DEBT.md) — open shortcuts and their payback plans
6. [`docs/phases/<NN-name>/CLAUDE.md`](../phases/) — task list for each phase
7. [`docs/superpowers/specs/`](../superpowers/specs/) — design specs (security spec is current; the 2026-05-15 design spec is partially superseded — read with caution)
8. [`.claude/agents/`](../../.claude/agents/) — specialist roster + AGILE + QUALITY_BAR

## What's archived here and why

| File | Why archived | Replaced by |
|---|---|---|
| `PHASE_0_ENVIRONMENT.md` | Old phase doc at repo root | `docs/phases/01-foundation/CLAUDE.md` |
| `PHASE_1_VOICE_AGENT.md` | Old phase doc at repo root | `docs/phases/02-voice-agent/CLAUDE.md` |
| `PHASE_2_BACKEND.md` | Old phase doc at repo root | `docs/phases/04-backend-core/CLAUDE.md` |
| `PHASE_3_FRONTEND.md` | Old phase doc at repo root | `docs/phases/07-frontend-receptionist/` + `08-frontend-dashboards/` |
| `PHASE_4_ONBOARDING.md` | Old phase doc at repo root | `docs/phases/09-subscriptions-onboarding/CLAUDE.md` |
| `PHASE_5_PRODUCTION.md` | Old phase doc at repo root | `docs/phases/10-deployment/CLAUDE.md` |
| `vachanam-progress.md` | Old progress tracker | `docs/STATUS.md` + `docs/ROADMAP.md` |
| `2026-05-18-phase-2-backend.md` | Old Phase 2 implementation plan | `docs/phases/04-backend-core/CLAUDE.md` |

These files are kept (not deleted) for archaeology — to trace why decisions changed. If something here contradicts current docs, **current docs win**.
