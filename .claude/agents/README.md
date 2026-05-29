# Vachanam — Specialist Agent Roster

Eight subagents, each scoped to one domain. Invoke via the Task tool (`subagent_type: <name>`) when work falls clearly inside one specialist's domain. For multi-domain work, dispatch `manager` first — it plans the breakdown and chooses which specialists to call.

---

## Roster

| Agent | Use when |
|---|---|
| [`manager`](manager.md) | Start of session, end of session, multi-domain task, unclear scope. Reads STATUS, picks the right specialist(s), updates docs after. |
| [`backend-engineer`](backend-engineer.md) | FastAPI routes, SQLAlchemy models, Alembic migrations, Python services, REST/webhook endpoints, async DB code. |
| [`frontend-engineer`](frontend-engineer.md) | React components, Vite config, PWA setup, Tailwind, axios + TanStack Query, offline behavior, mobile UX. |
| [`voice-agent-engineer`](voice-agent-engineer.md) | LiveKit Agents SDK, Sarvam STT/TTS, Gemini/GPT-4o-mini wiring, SIP trunk + Vobiz, session state, TTS sanitization, emergency keywords. |
| [`devops-engineer`](devops-engineer.md) | Docker, fly.toml, render.yaml, Cloudflare, GitHub Actions, env var management, secret rotation, monitoring. |
| [`security-engineer`](security-engineer.md) | JWT middleware, rate limiting, CSP/HSTS headers, audit log, OWASP defenses, secret scanning, vulnerability response. |
| [`privacy-legal`](privacy-legal.md) | Privacy policy text, DPDP Act compliance, data subject requests, breach notifications, ToS, retention policy enforcement. |
| [`tester`](tester.md) | pytest fixtures, integration tests, edge-case tests, concurrency tests, CI test config, security test suite. |

---

## Invocation patterns

### Pattern 1 — Single specialist, clear scope

Task fits one agent's domain unambiguously:

```
User: "Write the JWT middleware."
→ Task(subagent_type="security-engineer", ...)
```

### Pattern 2 — Manager-led decomposition

Task spans multiple domains OR scope unclear:

```
User: "Start Phase 4."
→ Task(subagent_type="manager", ...)
   → manager reads STATUS, opens phase doc, returns plan: "dispatch backend-engineer
      for Tasks 1-6, then tester for Task 7, then devops-engineer to delete the
      standalone test app"
→ Task(subagent_type="backend-engineer", ...) for each backend task
→ Task(subagent_type="tester", ...) for test task
→ etc.
```

### Pattern 3 — Specialist + reviewer

Always pair an implementer with a different reviewer for substantial work:

```
backend-engineer writes the queue endpoints
→ security-engineer reviews the auth + branch_guard usage
→ tester writes the data-isolation test
```

### Pattern 4 — Parallel specialists

Independent tasks can be dispatched in parallel (single message, multiple Task calls):

```
Frontend page work + backend endpoint work + privacy policy text — all in one
message, three parallel Task calls.
```

---

## Boundaries (what specialists DO NOT do)

| Specialist | Will NOT |
|---|---|
| `backend-engineer` | Touch frontend code or LiveKit agent internals. Won't write deployment configs. |
| `frontend-engineer` | Touch backend code. Won't change DB schema. |
| `voice-agent-engineer` | Touch FastAPI routes or React. |
| `devops-engineer` | Write business logic. |
| `security-engineer` | Implement features unrelated to security. Won't write the actual privacy policy text (that's `privacy-legal`). |
| `privacy-legal` | Write code. Outputs are markdown documents, runbooks, decision memos. |
| `tester` | Write the feature being tested. Implements only test code. |
| `manager` | Implement anything. Coordination only — reads, plans, dispatches, updates docs. |

When a specialist hits work outside its scope, it must return BLOCKED and recommend which specialist to dispatch next.

---

## Documents every specialist must read first

1. `CLAUDE.md` (root) — the law
2. `docs/STATUS.md` — current truth
3. `docs/ROADMAP.md` — phase order
4. The active phase doc: `docs/phases/NN-name/CLAUDE.md`
5. Their own agent file in this folder for domain-specific rules

For decision history, `docs/CHANGELOG.md` records what was decided when and why.

---

## After work — every specialist updates docs

Before returning DONE:
1. Update `docs/STATUS.md` if anything changed status (broken→fixed, planned→built)
2. Append entry to `docs/CHANGELOG.md` under the current date with decisions made and files touched
3. List exact files created/modified/deleted in the return message
4. Suggest the next specialist if work continues

The `manager` agent handles cross-doc consistency at the end of multi-specialist sessions.

---

## Conventions baked into every agent

- Read CLAUDE.md's 10 Absolute Rules before any code
- Filter every DB query by `branch_id`
- Use Redis INCR for tokens (DECR only as rollback)
- Sanitize every TTS string via `sanitize_for_tts()`
- Log via structlog, never `print()`
- Phone numbers logged as last-4 only
- No commits unless user asked
- Follow caveman mode if active (concise responses; code/commits stay normal)
