# Vachanam — Senior Developer Quality Bar

Every specialist on this project writes at senior level. No junior code, no junior docs, no junior decisions. This file is the standard. `manager` enforces it. `tester` rejects work that fails it. Every specialist reads it before starting work.

---

## Why this exists

You are senior engineers writing software for medical clinics. A bug isn't a failed test — it's a missed appointment, a lost patient, a DPDP violation. The standard is not "it works on my machine"; the standard is "I would defend this in a court of law if someone's data leaked."

---

## Code: every line must meet ALL of these

### Python (backend, agent)

- [ ] Type hints on every function signature (parameters AND return)
- [ ] Pydantic model on every request/response (no untyped dicts crossing API boundary)
- [ ] No `print()` — `structlog` only
- [ ] No bare `except:` — `except SpecificException as e:` always
- [ ] `branch_id` filter on every multi-tenant query
- [ ] `redis.incr` for tokens; `redis.decr` only as rollback (never primary)
- [ ] External calls wrapped in `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`
- [ ] `asyncio.to_thread` for any sync I/O call inside async context (Gemini SDK, Google APIs)
- [ ] Capture SQLAlchemy attrs into local vars BEFORE exiting `async with`
- [ ] Each `asyncio.gather` coroutine opens its own `async with AsyncSessionLocal()`
- [ ] **No module-level Redis/DB/HTTP client singletons.** Module-level `redis_client = aioredis.from_url(...)` or similar binds to whatever event loop runs at import. Breaks on worker restart, fork-after-import, test loops. Use per-call factory + `async with`. (See TD-016, TD-017 in CHANGELOG 2026-05-29.)
- [ ] `hmac.compare_digest` for signature comparison (never `==`)
- [ ] Phone numbers logged as `phone[-4:]` only
- [ ] No hardcoded URLs, phone numbers, keys, secrets — all from `settings`
- [ ] No commented-out code (delete it; git has history)
- [ ] No TODO/FIXME without an issue tracker reference or TECH_DEBT row
- [ ] Docstring on every public function (one line explaining WHY, not WHAT)
- [ ] No function over 50 lines (refactor before then)
- [ ] No file over 400 lines (split before then)
- [ ] No nested ternaries, no clever one-liners that need a comment to read
- [ ] Constants named in UPPER_SNAKE_CASE at module top, not magic numbers in functions

### TypeScript / JavaScript (frontend)

- [ ] `const` by default; `let` only when reassigned; no `var`
- [ ] No `any` type unless wrapping an external lib's untyped surface (then comment why)
- [ ] All event handlers in `useCallback` if passed as props
- [ ] No inline object literals as props (`<X data={{a:1}} />`) — extract or memoize
- [ ] No `dangerouslySetInnerHTML` without `DOMPurify`
- [ ] No raw `fetch` — use the axios client at `src/api/client.js`
- [ ] No `useState` for server data — TanStack Query owns server state
- [ ] No `localStorage.setItem` for anything except JWT (and that has a security trade-off noted)
- [ ] No PII in URL query strings
- [ ] No phone numbers shown beyond last-4 suffix
- [ ] Touch targets ≥ 56px on mobile
- [ ] Lighthouse PWA score ≥ 90 on key pages
- [ ] Bundle for any page ≤ 200kB initial JS (code-split heavy pages via `React.lazy`)
- [ ] No analytics SDK without `privacy-legal` approval
- [ ] No third-party origin in production without CSP entry

### SQL / Schema (database)

- [ ] PK is `UUID(as_uuid=True)` with `default=uuid.uuid4`
- [ ] Multi-tenant tables have `branch_id` FK + index
- [ ] Compound indexes for common `(branch_id, date)` queries
- [ ] `String(N)` with explicit length, not bare `String`
- [ ] `Text` only for unbounded content (notes, prompts)
- [ ] `Integer` paise for currency, never `Float`
- [ ] `JSONB` not `JSON`
- [ ] `server_default=func.now()` for timestamps, not Python-side
- [ ] Enum types named in migration metadata
- [ ] FK has `ondelete=` explicit (CASCADE or RESTRICT)
- [ ] DPDP classification in docstring (PII / sensitive / pseudonymous / aggregate)
- [ ] Migration reviewed line-by-line after `--autogenerate`
- [ ] Zero-downtime pattern for any production schema change

### Tests

- [ ] Written FIRST, fails FIRST, then implementation passes
- [ ] One assertion idea per test
- [ ] Real DB + Real Redis for integration; no SQLite-pretending; no fakeredis
- [ ] Concurrency tests run N ≥ 100
- [ ] Data isolation tested with 2+ orgs
- [ ] Negative tests for every endpoint (401/403/404/409/422/429 as applicable)
- [ ] No `time.sleep` — use `await` or `freezegun`
- [ ] No `@pytest.mark.skip` without explicit reason + revisit date
- [ ] No mock-everything tests pretending to be integration tests
- [ ] Fixture-driven setup; no inline DB seeding in test bodies

---

## Documentation: every doc must meet ALL of these

- [ ] No "TBD" / "TODO" / "fill in later" — finished or excluded
- [ ] Every claim either implemented OR labeled with implementation specialist + target phase
- [ ] Plain English first; jargon defined inline
- [ ] Code examples are runnable as-is (no `...` ellipses where literal code is required)
- [ ] File paths are clickable markdown links: `[file.py](path/to/file.py)`
- [ ] Tables for any structured comparison (not paragraphs of "first... second... third...")
- [ ] No fluff sentences ("As we all know..." / "Obviously..." / "Simply...")
- [ ] No marketing voice (this is internal engineering doc, not a sales deck)
- [ ] Every external reference has a link
- [ ] Every spec has a self-review at end (placeholders / contradictions / scope / ambiguity)
- [ ] Every runbook is rehearsable (a different engineer could execute it without asking)
- [ ] Every CHANGELOG entry has: topic, decisions with reasoning, files, commits, follow-ups, retro
- [ ] Every privacy/legal doc has a plain-English version alongside any legal language

---

## Decisions: every decision must meet ALL of these

- [ ] Recorded in `docs/CHANGELOG.md` with reasoning (the WHY, not just the WHAT)
- [ ] Trade-off explicitly named ("we chose X over Y because Z; we give up W")
- [ ] If brainstormer was involved, options + recommendation captured
- [ ] If client decision, escalation thread referenced
- [ ] If reverses an earlier decision, the old CHANGELOG entry referenced + reason for change
- [ ] If introduces tech debt, TECH_DEBT row added with severity + payback plan
- [ ] If introduces vendor / cost, captured in CHANGELOG + processor list updated by privacy-legal

---

## Commits

- [ ] Subject line ≤ 70 chars, imperative voice ("feat(auth): add JWT revocation")
- [ ] Conventional commit prefix: `feat:` / `fix:` / `chore:` / `docs:` / `test:` / `refactor:` / `perf:`
- [ ] Scope optional but encouraged: `feat(payments): ...`, `fix(agent): ...`
- [ ] Body explains WHY, not just WHAT (the diff shows what)
- [ ] No "WIP" / "checkpoint" / "fixes" without specifics
- [ ] No commit bundles unrelated changes (each commit is one logical change)
- [ ] No commit broken (tests pass at every commit, even if it slows down velocity)
- [ ] `Co-Authored-By:` line if AI-assisted (transparency)

---

## Pull request / branch

- [ ] Branch name describes the change: `feat/jwt-middleware`, `fix/token-rollback`
- [ ] PR description references the phase + acceptance criteria addressed
- [ ] PR description has a "How to test" section
- [ ] Reviewer named (the right specialist for the domain)
- [ ] CI green before merge
- [ ] No merge of `main` into the feature branch (rebase or squash)
- [ ] No force-push to a shared branch without notice

---

## Production deploys

- [ ] Devops-engineer checklist run
- [ ] Migration tested against staging-shaped data
- [ ] Backup verified < 30 days old
- [ ] Rollback procedure rehearsed mentally
- [ ] Health check passes post-deploy
- [ ] Manager briefed (client briefed if user-facing)

---

## Anti-patterns that get rejected on sight

- "It works on my machine"
- "I'll add the test after"
- "It's just a small change"
- "We'll fix it in the next sprint"
- "Mostly done"
- "Good enough for now"
- "Trust me"
- "Let me just push this real quick"
- "The user won't notice"
- "We don't need a code review for this one"
- "I'll document it later"
- "The exception is rare so we don't handle it"
- "Performance can be fixed later"
- "Security can be added later" (NO — see Phase 4.5)

If you find yourself thinking any of these — STOP. Re-read this file. Do it right.

---

## How specialists self-check

Before reporting `DONE`, every specialist runs this mental checklist on their work:

1. Did I follow the relevant rules from this file?
2. Did I leave the codebase better than I found it (or at least no worse)?
3. Would I be proud to show this code/doc to another senior engineer?
4. Did I write the tests that prove this is correct?
5. Did I update the docs that explain WHY?
6. If this breaks in production at 2 AM, can someone else fix it from the code + docs alone?

If any answer is "no" — fix it before reporting DONE.

---

## How `manager` enforces this

The manager runs the Definition of Done checklist (see `AGILE.md`) on every task. The DoD includes "specialist self-check passed". If the specialist returned `DONE` and the manager spots a quality bar violation in their review, the task gets sent back as `REJECTED`.

The manager is stubborn. Reject early, reject often. Senior teams don't get fast by skipping quality — they get fast by never producing rework.
