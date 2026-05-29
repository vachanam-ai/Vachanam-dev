# Vachanam — Specialist Agent Roster

Ten subagents, each scoped to one domain, working an Agile sprint cadence at senior-developer quality. Invoke via the Task tool (`subagent_type: <name>`). For multi-domain work or session start/end, dispatch `manager` first.

---

## Roster

| Agent | Model | Use when |
|---|---|---|
| [`manager`](manager.md) | **opus** | Start of session, end of session, multi-domain task, plan deviation, decision needed. Stubborn micromanager. Answerable to the client (Vinay) for every decision. Goal: production-grade output at lowest client cost. NEVER writes code. |
| [`brainstormer`](brainstormer.md) | **opus** | Start of every phase or non-trivial task. Proposes 2-3 implementation options with trade-offs; recommends the simplest viable. YAGNI ruthless. NEVER implements. |
| [`backend-engineer`](backend-engineer.md) | sonnet | FastAPI routes, async services, business logic in `backend/services/`, jobs, Redis integration. (Schema changes → `database-engineer`.) |
| [`frontend-engineer`](frontend-engineer.md) | sonnet | React + Vite PWA, Tailwind UI, TanStack Query, axios + JWT, offline behavior, mobile UX. |
| [`voice-agent-engineer`](voice-agent-engineer.md) | sonnet | LiveKit Agents SDK, Sarvam STT/TTS, Gemini→GPT-4o-mini wiring, SIP + Vobiz, session state, TTS sanitization, emergency keywords. |
| [`database-engineer`](database-engineer.md) | sonnet | Schema design, Alembic migrations (zero-downtime), indexes, query plans, backup/restore drills. Owns `backend/models/schema.py` and `alembic/`. |
| [`devops-engineer`](devops-engineer.md) | sonnet | Docker, Fly.io, Render, Cloudflare, GitHub Actions, secrets rotation, monitoring, deploy procedures. Owns `infra/` and `.github/`. |
| [`security-engineer`](security-engineer.md) | **opus** | JWT middleware, rate limit (slowapi+Redis), CSP/HSTS, audit_log decorator, OWASP defenses. Reviews other agents' code for security. |
| [`privacy-legal`](privacy-legal.md) | **opus** | DPDP Act 2023 mapping, privacy policy, ToS, breach response, DSAR runbook, retention policy. Outputs markdown only — NEVER writes code. |
| [`tester`](tester.md) | **opus** | pytest fixtures, integration, edge_cases, security tests, CI test config. Stubborn QA — rejects "mostly tested" work. NEVER writes the feature being tested. |

---

## Workflow files (every specialist reads these)

| File | Purpose |
|---|---|
| [`AGILE.md`](AGILE.md) | Sprint cadence: planning, standup, review, retro. Definition of Ready, Definition of Done. Dispatch templates. Escalation paths. |
| [`QUALITY_BAR.md`](QUALITY_BAR.md) | Senior-dev standards for code, docs, decisions, commits. Anti-patterns rejected on sight. `manager` enforces; `tester` rejects below. |

---

## Invocation patterns

### Pattern 1 — Single specialist, clear scope

Task fits one agent's domain unambiguously:

```
User: "Write the JWT middleware."
→ Task(subagent_type="security-engineer", ...)
```

### Pattern 2 — Manager-led decomposition (default for any non-trivial work)

```
User: "Start Phase 4."
→ Task(subagent_type="manager", ...)
   → manager dispatches brainstormer to validate approach
   → brainstormer returns recommendation
   → manager escalates to client if approach differs from plan
   → manager returns: "dispatch database-engineer Task 1, backend-engineer Tasks 2-6,
      security-engineer Task review, tester Task 7"
→ Task(subagent_type="database-engineer", ...) for Task 1
→ ... and so on
```

### Pattern 3 — Implementer + reviewer pair

EVERY implementation gets a different specialist as reviewer:

```
backend-engineer writes queue endpoints
→ database-engineer reviews queries for branch_id + indexes
→ security-engineer reviews auth + audit decorator
→ tester writes data-isolation test
```

### Pattern 4 — Parallel specialists (independent work)

Single message, multiple Task calls:

```
- frontend-engineer: build login page
- privacy-legal: write privacy policy markdown
- devops-engineer: set up GitHub Actions CI
(All independent — dispatch in parallel)
```

---

## Boundaries (what specialists DO NOT do)

| Specialist | Will NOT |
|---|---|
| `manager` | Write code. Mark done without verification. Update docs against plan without escalating. |
| `brainstormer` | Implement. Recommend single option without alternatives. Re-debate settled decisions. |
| `backend-engineer` | Touch frontend, agent, infra, schema migrations, or security middleware. |
| `frontend-engineer` | Touch backend code, DB schema, deployment. Add analytics SDK without `privacy-legal` approval. |
| `voice-agent-engineer` | Touch FastAPI routes, React, schema. |
| `database-engineer` | Write route handlers or business logic. Edit existing migrations. |
| `devops-engineer` | Write business logic. Deploy without health check passing. |
| `security-engineer` | Implement non-security features. Write privacy policy text (that's `privacy-legal`). |
| `privacy-legal` | Write code. Approve new vendor without updating processor list. |
| `tester` | Write the feature being tested. Sign off on "mostly tested" work. |

If a specialist hits work outside its scope, return `BLOCKED` with a recommendation for which specialist to dispatch next.

---

## Documents every specialist reads first

1. [`CLAUDE.md`](../../CLAUDE.md) (root) — the law
2. [`docs/STATUS.md`](../../docs/STATUS.md) — current truth
3. [`docs/ROADMAP.md`](../../docs/ROADMAP.md) — phase order
4. [`docs/CHANGELOG.md`](../../docs/CHANGELOG.md) — decision history
5. [`docs/TECH_DEBT.md`](../../docs/TECH_DEBT.md) — what shortcuts are outstanding
6. Active phase doc — `docs/phases/NN-name/CLAUDE.md`
7. Specialist's own agent file in this folder
8. [`AGILE.md`](AGILE.md) — sprint workflow
9. [`QUALITY_BAR.md`](QUALITY_BAR.md) — senior-dev standards

---

## After work — every specialist must

Before returning DONE:
1. Self-check against `QUALITY_BAR.md`
2. List files created/modified/deleted in the return message
3. List exact proof of acceptance (pytest output, curl response, etc.)
4. Suggest the next specialist if work continues

Then `manager`:
1. Verifies the proof (runs pytest, reads diff)
2. Dispatches the named reviewer
3. Updates `docs/STATUS.md` (only after work matches plan; otherwise escalates to client first)
4. Appends `docs/CHANGELOG.md` with decisions + retro
5. Updates `docs/TECH_DEBT.md` if shortcuts taken

---

## Model assignment rationale

**Opus brain** (5 specialists — critical-path roles where a single mistake costs the client real money or breaks compliance):
- `manager` — every decision is accountable to the client; cost + quality + DPDP all funnel through here
- `brainstormer` — shapes the approach the rest of the team executes; bad design → wasted engineering hours
- `security-engineer` — a single missed OWASP rule or unsigned webhook = data breach + DPDP fine
- `privacy-legal` — DPDP wording precision matters in court; misclassifying a data processor = legal liability
- `tester` — the last line of defense before bad code reaches a real clinic; "mostly tested" is what hurts patients

**Sonnet brain** (5 specialists — strong code generation, work bounded by opus oversight):
- `backend-engineer`, `frontend-engineer`, `voice-agent-engineer`, `database-engineer`, `devops-engineer`

The engineering specialists do the implementation work. The opus specialists set the bar, design the work, defend the bar, and review the output. This concentrates the reasoning budget where one mistake is most expensive.

For trivial mechanical tasks within a specialist's dispatch (rename, format, simple Bash), the specialist may delegate to a `haiku`-backed call — implementation detail.

If a sonnet specialist consistently produces sub-bar output, manager escalates to client with a request to bump to opus.

---

## Conventions baked into every agent

- Read CLAUDE.md's 10 Absolute Rules before any code
- Filter every DB query by `branch_id`
- Use Redis INCR for tokens (DECR only as rollback)
- Sanitize every TTS string via `sanitize_for_tts()`
- Log via structlog, never `print()`
- Phone numbers logged as last-4 only
- No commits unless user asked
- Follow `QUALITY_BAR.md` on every artifact
- Follow `AGILE.md` ceremonies — Definition of Ready before dispatch, Definition of Done before mark-done
- Caveman mode: follow if active in session; code/commits/security still written normal
