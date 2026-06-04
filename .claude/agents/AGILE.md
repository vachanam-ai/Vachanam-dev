# Vachanam — Agile Workflow

How sprints, dispatches, reviews, and retros run. Managed by `manager`. Followed by every specialist.

---

## Sprint definition for Vachanam

A **sprint = one phase from `docs/ROADMAP.md`**, typically 1-4 days of work. Each phase doc (e.g. `docs/phases/04-backend-core/CLAUDE.md`) IS the sprint backlog. The sprint goal = the phase's exit criteria.

We do NOT do fixed-length 2-week sprints. We do scope-fixed sprints — a phase is done when all acceptance criteria check, however long that takes. If it takes longer than the phase doc estimate, the manager escalates to the client with a revised estimate and reasoning.

---

## The four ceremonies

### 1. Sprint planning (start of a phase)

Owner: `manager`

Steps:
1. Read `docs/STATUS.md`, `docs/ROADMAP.md`, active phase doc, last 3 CHANGELOG entries
2. Dispatch `brainstormer` to validate the planned approach against alternatives (especially "could we cut/defer scope?")
3. If brainstormer surfaces a plan deviation, **escalate to client** before continuing
4. Decompose the phase into specialist-scoped tasks
5. Sequence tasks by dependency (database before backend, backend before frontend, etc.)
6. Estimate each task (cost in specialist hours + recurring vendor cost if any)
7. Name the reviewer specialist for each task
8. Publish the sprint plan as the standup output

### 2. Standup (start of every session)

Owner: `manager`

Format:
```
SPRINT GOAL: <restate the phase goal>
YESTERDAY (last session): <what shipped, what's pending>
TODAY: <next dispatch>
BLOCKERS: <decisions needed from client>
SHORTCUTS REJECTED: <if any>
```

Standup is < 1 minute of model time. Its purpose is sync, not deep planning.

### 3. Sprint review (end of session OR end of phase)

Owner: `manager`

Steps:
1. `git log --oneline <since>..HEAD` — what shipped
2. `pytest tests/ -v --tb=line` — what's green
3. Verify each completed task against its acceptance criterion (READ the criterion, RUN the verification command, CONFIRM the proof)
4. Demo if user available (curl output, screenshot, before/after diff)
5. If anything failed to meet criterion → does NOT count as done

### 4. Retrospective (end of session OR end of phase)

Owner: `manager`

Appended to `docs/CHANGELOG.md` at the bottom of the session entry:

```
RETRO:
  Worked:
    - <thing that went well; keep doing>
  Didn't work:
    - <thing that didn't; root cause>
  Change next sprint:
    - <specific action>
```

The retro is non-negotiable. Skipping it means we make the same mistake next sprint.

---

## Roles in the Vachanam team

| Agile role | Vachanam specialist |
|---|---|
| Product Owner / Client | Vinay (the user) |
| Scrum Master / PM | `manager` |
| Tech Lead / Architect | `brainstormer` |
| Engineers | `backend-engineer`, `frontend-engineer`, `voice-agent-engineer`, `database-engineer`, `devops-engineer`, `security-engineer` |
| QA | `tester` |
| Compliance/Legal | `privacy-legal` |

Pair-programming pattern: every implementer is paired with a different specialist as reviewer (security-engineer reviews backend auth code; database-engineer reviews any backend query; tester reviews everything).

---

## Definition of Ready (DoR) — before a task is dispatched

A task is ready for dispatch only if ALL true:

- [ ] Scope is one specialist's domain (or task is split per-domain)
- [ ] Acceptance criteria are testable (specific pytest output, curl response, file presence)
- [ ] Inputs identified (which files, which existing patterns to follow)
- [ ] Reviewer specialist named
- [ ] Brainstormer has weighed in if non-trivial
- [ ] No spec contradictions blocking work
- [ ] No client decision pending

If ANY box unchecked, manager does NOT dispatch — resolves first.

---

## Definition of Done (DoD) — before a task is marked done

A task is done only if ALL true:

- [ ] Code passes acceptance test(s)
- [ ] All `tests/<category>/` for affected area pass
- [ ] No skipped tests without explicit reason + revisit date
- [ ] Reviewer specialist signed off
- [ ] Structlog covers significant events
- [ ] `branch_id` filter present on every new query (if applicable)
- [ ] Pydantic models on every new request (if applicable)
- [ ] Audit decorator on every new sensitive route (if applicable)
- [ ] No new secret in repo
- [ ] No new vendor without `privacy-legal` update
- [ ] Phase doc still accurate (or updated)
- [ ] CHANGELOG entry drafted
- [ ] TECH_DEBT updated if shortcut taken
- [ ] `docs/PROJECT_STRUCTURE.md` updated to reflect new/changed components

Manager runs this checklist. Specialist does NOT mark themselves done.

---

## Ultra-caveman mode for inter-agent communication

DEFAULT: full prose. Specialists write reports in clear English so manager + orchestrator + reviewers can act without re-asking.

ULTRA-CAVEMAN MODE PERMITTED ONLY FOR these structured fields in returns:
- RESULT: DONE | DONE_WITH_CONCERNS | BLOCKED | REJECTED | NEEDS_CONTEXT
- FILES MODIFIED / CREATED / DELETED (lists)
- TESTS: <pass/fail counts>
- COMMIT: <hash>
- NEXT: <specialist + task>

EXAMPLES of caveman-OK headers:
  RESULT: DONE
  FILES MOD: backend/middleware/security_headers.py, backend/main.py
  TESTS: 77/77 pass
  COMMIT: 6b00686
  NEXT: tester Task 4

ALWAYS full prose (caveman FORBIDDEN):
- Dispatch prompts to specialists (new scope description)
- Reviewer rejection reasoning
- Trade-off explanations
- Spec-deviation notes
- Audit-trail findings in DISPATCHES.md
- Client escalations
- Any commit message / code / test file

Rationale: token savings from caveman are small; cost of one wrong dispatch (rework cycle) is hundreds of times the tokens saved.

---

## Definition of Done for a phase (when all sprint tasks complete)

- [ ] All sprint tasks meet DoD
- [ ] Every acceptance criterion in the phase doc checked
- [ ] `tests/_phase_<N>_acceptance.md` maps each criterion to a passing test
- [ ] STATUS.md reflects phase done
- [ ] ROADMAP.md flipped from active to done
- [ ] CHANGELOG sprint entry written with decisions + retro
- [ ] Client briefed (manager dispatches a one-paragraph "phase N shipped" summary)
- [ ] No un-escalated plan deviations

---

## Dispatch templates

### Manager → engineering specialist

```
TASK: <one sentence>
SCOPE:
  - Touches: <files/components>
  - Does NOT touch: <out-of-scope>
ACCEPTANCE:
  - <specific test command + expected output>
  - <specific curl + expected response>
INPUTS:
  - Read: <files / spec sections>
  - Pattern to follow: <existing code reference>
REVIEWER: <named specialist>
EST. EFFORT: <low/med/high>
CHANGE FROM PLAN?: <no, OR yes — escalated to client and approved>
```

### Manager → tester

```
TASK: write failing tests for <feature>
SCOPE: tests/<category>/
ACCEPTANCE CRITERIA TO COVER:
  1. <criterion>
  2. <criterion>
NEGATIVE TESTS REQUIRED: <list>
CONCURRENCY TESTS REQUIRED: <yes/no, with N>
DATA ISOLATION TESTS REQUIRED: <yes/no>
HAND-OFF: when failing tests written, manager dispatches implementer with the tests as spec
```

### Manager → reviewer

```
TASK: review <implementer>'s work in commits <A>..<B>
FOCUS:
  - <specific concerns from reviewer's domain>
USE THE CHECKLIST IN: .claude/agents/<reviewer>.md
APPROVE OR REJECT — no maybe
```

---

## Escalation paths

| Situation | Who handles |
|---|---|
| Plan deviation | manager → client |
| Vendor cost increase | manager → client |
| Spec contradiction | manager → client (with proposed resolution) |
| Specialist BLOCKED on context | manager provides context, re-dispatch |
| Specialist BLOCKED on decision | manager → client |
| Implementer disputes reviewer | manager arbitrates; if unresolved → client |
| Security or DPDP rule conflict with feature | manager → client (security-engineer + privacy-legal both consulted) |
| Bug discovered in prod | privacy-legal (breach check) + security-engineer (root cause) + devops-engineer (rollback) → manager coordinates |

---

## Velocity tracking (lightweight)

After each phase:
- Estimated effort vs actual effort (in CHANGELOG retro)
- # of escalations
- # of shortcuts taken (TECH_DEBT rows added)
- # of test rejections by tester

Track over time. If a pattern emerges (estimates always 50% low, frequent rejections, etc.), retro it and adjust.

---

## What we do NOT do

- Story points (effort in "low/med/high" or hours is enough)
- Daily standups (we do per-session standups instead)
- Burndown charts (CHANGELOG retro is enough)
- Refinement / grooming as separate ceremony (rolled into planning)
- Sprint demo as separate ceremony (rolled into review)
- Velocity targets (we measure but don't target)
- Multi-team sprint planning (one team, one client)
- SAFe, LeSS, or any scaled framework (overkill for one-team MVP)

---

## MANDATORY DISPATCH RULE (standing rule per CHANGELOG 2026-06-01)

Every unit of work — no matter how small — is dispatched to a specialist via `Task(subagent_type=...)`. The orchestrator (main thread) never embodies a specialist. No inline writing of code, tests, or non-`docs/` files. No "I'll quickly do this one line."

Even a one-character typo fix in `backend/routers/auth.py` is dispatched to `backend-engineer`. A typo in `tests/unit/test_auth.py` goes to `tester`. A doc-only change in `docs/STATUS.md` goes to `manager`.

**Why:**
- Traceability — every change has a Task entry in `docs/DISPATCHES.md` linking specialist → file → reviewer → commit
- Persona enforcement — each specialist applies its domain's QUALITY_BAR sections
- Reviewer mandate — implementer ≠ reviewer; gates enforced
- Audit defense — if a clinic asks "who changed X?", the dispatch log answers

**Why not exceptions for tiny fixes:** because tiny fixes are where regressions hide. The first inline shortcut creates the precedent that becomes "we always do inline for small things" which becomes "we did everything inline." Stop the slide at zero exceptions.

**Allowed for orchestrator (main thread) only:**
- Reading files via `Read`, `Grep`, `Glob`
- Running `git status`, `git log`, `git diff` for status checks
- Running `pytest` to verify a specialist's reported test result (verification, not implementation)
- Dispatching via `Task`
- Asking the user clarifying questions via `AskUserQuestion`

**Forbidden for orchestrator:**
- `Edit` or `Write` on any file in `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`
- Writing commit messages with code changes (that's a specialist + reviewer's job)
- Editing files in `docs/` EXCEPT to record a dispatch in `docs/DISPATCHES.md` after a specialist completes

**Dispatch log entry:** every dispatch appended to `docs/DISPATCHES.md` per the format in `manager.md`. Never edit older entries.

---

## DISPATCH PROMPT EFFICIENCY (per CHANGELOG 2026-06-04)

To reduce per-dispatch token cost without compromising quality, every dispatch prompt MUST:

### Rule 1 — Curated context block

Include at the top of the prompt:
- `BASELINE:` commit hash + test count (e.g., "commit fcc1507, 90/90 pass")
- `WHAT'S DONE:` 1-2 sentences relevant to this task only
- `WHAT'S OPEN:` 1-2 sentences on the immediate scope
- `RELEVANT FILES:` only the 3-5 files this specialist actually edits/reads
- `SPEC SECTION:` exact section + line number (e.g., "spec §8.5 lines 412-440")

Specialist skips reading STATUS / ROADMAP / CHANGELOG / TECH_DEBT unless specifically needed for the decision (rare).

### Rule 2 — Skip brainstormer when no real fork

Brainstormer dispatches ONLY when:
- ≥2 architecturally-different approaches exist (e.g., custom vs library)
- New vendor / cost decision (any new SaaS subscription)
- Library choice not in spec
- Performance / scale trade-off with measurable cost

Routine implementation that follows spec verbatim = NO brainstormer gate. Manager dispatches implementer directly.

### Rule 3 — Bundle related small tasks

Multiple test files in same domain → ONE tester dispatch (e.g., test_headers + test_cors + test_admin + test_jwt = one tester dispatch).

Multiple related implementation sub-tasks → ONE implementer dispatch (e.g., require_admin + close 2 reviewer follow-ups in same router = one backend-engineer dispatch).

DO NOT bundle across domains (still one dispatch per specialist domain).

### Rule 4 — Reviewer follow-ups bundled into next dispatch

If a reviewer flags small follow-ups (P3 nits, minor coverage gaps, missing test edge cases):
- DO NOT dispatch a separate "fix small thing" task
- DO fold the follow-ups into the next planned implementer dispatch in the same area
- Reference the reviewer's commit hash + the specific findings in the prompt

### Dispatch prompt template (use for every dispatch)

```
[TITLE — what specialist is doing]

BASELINE: commit <hash>, <N>/<M> pass
WHAT'S DONE: <1-2 sentences>
WHAT'S OPEN: <1-2 sentences on this task scope>
RELEVANT FILES: <list of 3-5 file paths>
SPEC SECTION: <spec path + section + line range>
[OPTIONAL] PRIOR REVIEWER FOLLOWUPS TO BUNDLE: <list>

YOUR JOB
1. ...
2. ...

CONSTRAINTS
- ...

REPORT BACK (narrow caveman)
```
RESULT: ...
FILES: Created/Modified
TESTS: ...
COMMIT: <hash>
NEXT: ...
```
```

---
