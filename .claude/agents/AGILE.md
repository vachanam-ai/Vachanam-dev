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

Manager runs this checklist. Specialist does NOT mark themselves done.

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
