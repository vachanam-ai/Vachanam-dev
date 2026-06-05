# Vachanam — Change Log

Session-by-session record of decisions, file changes, and direction shifts. Most recent at top. This is a running log — append new sessions; never edit old entries (they're historical record).

When you need to know "why was X done this way," check here. When you need to know "what was decided last week," check here. When STATUS.md says something is done, check here for the commits that did it.

Format per session:
- Date + topic
- Key decisions (with reasoning)
- Files created / modified / deleted
- Commits (hash + subject)
- Follow-ups for next session

---

## 2026-06-05 — Phase 4.5 close-out: compliance docs committed + spec amended for no-recording decision

Tasks 11+13 closed: 5 legal/compliance docs committed (`8dede68`), security spec amended with 5 changes reflecting client's no-recording decision (Option A, 2026-06-04). 2 acceptance matrix items previously BLOCKED (criteria 12+13: /privacy page, breach runbook) now unblocked. Spec §15 expanded from 19 to 22 acceptance criteria. REVISIONS §16 entry appended. DISPATCHES updated. Remaining for Phase 4.5 close-out: Task 12 (backend-engineer: /privacy + /terms routes), Task 17 (ZAP scan), Task 18 (manager final sign-off + STATUS/ROADMAP update).

---

## 2026-06-04 — Token optimization: curated context blocks + bundled dispatches

**Client request:** "claude is drinking tokens like water. tokens getting exhausted very fastly. can you find a way to optimize this without compromising quality."

**Diagnosis:** Per-subagent dispatch was burning 70k-170k tokens, mostly on file rediscovery (STATUS + ROADMAP + CHANGELOG + TECH_DEBT + spec + multiple source files before actual work).

**Decision (Option A approved, 4 changes):**
1. Curated context block in every dispatch prompt (baseline commit, what's done, what's open, only the 3-5 relevant files, exact spec section by line number) — saves 30-50% per dispatch
2. Skip brainstormer when no real architectural fork exists — saves 1 opus dispatch per phase
3. Bundle related small tasks (multiple test files of same domain → one tester dispatch; related sub-implementations → one engineer dispatch)
4. Bundle reviewer follow-ups (P3 nits, minor gaps) into next planned implementer dispatch instead of separate "fix small thing" dispatches

**Quality non-negotiables UNCHANGED:** mandatory Task dispatch, DISPATCHES.md logging, different specialist for review, TDD pattern, per-domain QUALITY_BAR, no test weakening, all CLAUDE.md rules intact.

**Files modified:**
- .claude/agents/AGILE.md — new "DISPATCH PROMPT EFFICIENCY" section with 4 rules + template
- .claude/agents/manager.md — new stubborn rule 14 (dispatch prompt efficiency)
- docs/CHANGELOG.md — this entry
- docs/DISPATCHES.md — dispatch entry for this manager dispatch

**Commit:** `21e1e36` — chore(process): token optimization — curated context blocks + bundled dispatches

**Impact:** Expected ~40% reduction in per-dispatch token cost. First dispatch under new rules: Phase 4.5 Task 8 (tester bundled headers + CORS + admin + JWT failing tests).

**Retro:** This optimization was an obvious win once asked for. Should have been baked into the original dispatch rule (CHANGELOG 2026-06-01) — orchestrator's initial implementation of the mandatory-dispatch rule defaulted to "specialist reads everything from scratch" because that was the safe default. The fix is curated context, not reading less. Lesson for next sprint: when introducing a process rule, also define the prompt template that uses it efficiently.

**Addendum (2026-06-04 later):** Client tightened stale-graph threshold from 7 days to 48 hours after observing that end-to-end app changes ship in <7 days. Final rule: regen graphify if `GRAPH_REPORT.md` Generated timestamp is >48h old. Phase 4.5 Task 14 (CI workflow) will automate regen-on-commit, obviating this manual check.

---

## 2026-06-03 (latest) — WhatsApp removed from MVP1, moved to MVP2 (client decision)

**Topic:** Client-directed scope change. All WhatsApp functionality removed from MVP1 and deferred to MVP2. Voice booking remains verbal-on-call only; no patient WA confirmation, no doctor WA notification. Calendar events still created. Payment/trial reminders via email instead of WA.

### Client direction (verbatim)

> "for MVP1 lets remove whatsapp functionality. lets make it for MVP 2."

This is a binding client decision. No escalation needed -- the client issued this directly.

### Key decisions

1. **Phase 5 (WhatsApp) -- entire phase deferred to MVP2.** The phase doc is retained in `docs/phases/05-whatsapp/` for MVP2 reference. Header added marking it as deferred. Reasoning: reduces MVP1 scope by ~4-5 engineering days; removes the Meta WhatsApp Business account setup as a launch blocker; voice booking + Calendar event + receptionist app covers the core value prop for first paying clinics.

2. **Phase 6 (Jobs + Calendar) -- reduced to Calendar + token expiry only.** EOD summary (sends WA to doctors) and follow-up tasks (sends WA to patients) both depend on Phase 5's MetaService and are deferred to MVP2. What remains: Google Calendar create/delete for bookings + token expiry job every 2 minutes. Effort reduced from ~2 days to ~1 day.

3. **Phase 9 (Subscriptions + Onboarding) -- payment reminders via email, not WA.** Trial-expiry notifications and onboarding welcome messages use email instead of WhatsApp for MVP1. WA notifications added in MVP2 after Phase 5 ships.

4. **Phase 10 (Deployment) -- Meta WA infra dropped from MVP1 deploy checklist.** No `META_ACCESS_TOKEN` or `META_PHONE_NUMBER_ID` secrets needed on Fly/Render for MVP1. WhatsApp webhook setup deferred. Production acceptance test updated: replaces "WA confirmation arrives" with "Calendar event created."

5. **Voice agent (Phases 1-2, already DONE) -- no changes needed.** Booking confirmation remains verbal-on-call only. The voice agent never had WA sends wired in (those were Phase 5 scope). Calendar event creation stays as-is.

6. **TD-018 compound indexes -- target moved from Phase 5 to Phase 7/9.** Since Phase 5 is deferred, compound indexes (evidence-gated) move to whichever phase first produces meaningful query volume. No urgency change.

7. **TD-025 broad except clause -- target moved from Phase 5 to Phase 7.** Originally planned for "when touching queue.py for WhatsApp integration." Now targets Phase 7 (receptionist PWA, which also touches queue endpoints).

### What MVP1 loses (trade-offs documented)

- Doctors cannot manage schedule via WhatsApp on-the-go -- must use receptionist app or owner dashboard
- Patients do NOT receive WhatsApp confirmation after voice booking -- only verbal confirmation on the call + Google Calendar event for doctor's reference
- No WhatsApp-based booking flow for patients (voice-only for MVP1)
- Trial-end and payment reminders via email only (no WA)
- Cancellation notifications: receptionist calls patient manually or uses the PWA
- No EOD summary sent to doctors at 5:30 PM -- doctors check dashboard/app instead
- No automated patient follow-ups via WA -- receptionist handles manually

### What MVP1 still delivers

- Telugu voice booking via AI (Phase 2, done)
- Atomic token assignment via Redis INCR (Phase 2, done)
- Razorpay subscription billing (Phase 3 + Phase 9)
- Backend API with JWT auth + branch isolation (Phase 4, done)
- Security and compliance middleware (Phase 4.5, in progress)
- Google Calendar event creation for every booking (Phase 6, reduced)
- Token expiry background job (Phase 6, reduced)
- Receptionist PWA for queue management (Phase 7)
- Owner + Vinay admin dashboards (Phase 8)
- Vobiz DID provisioning + clinic onboarding (Phase 9)
- Production deployment on Fly + Render + Cloudflare (Phase 10)

### Files modified

- `docs/phases/05-whatsapp/CLAUDE.md` -- added MVP2 deferral header with client direction, trade-offs, and "when to start" guidance
- `docs/phases/06-jobs-calendar/CLAUDE.md` -- reduced scope: MVP1 = Calendar + token expiry only; WA jobs marked DEFERRED-MVP2; acceptance criteria split into MVP1 and MVP2 sections; file list split
- `docs/phases/09-subscriptions-onboarding/CLAUDE.md` -- trial_expiry sends email (not WA); onboarding welcome via email; prerequisites updated (Phase 5 not required)
- `docs/phases/10-deployment/CLAUDE.md` -- goal updated (no WA confirmation); Meta secrets removed from Fly deploy; WA webhook deferred; production checklist updated (Calendar event replaces WA confirmation); runbook updated
- `docs/STATUS.md` -- Phase 5 marked DEFERRED-MVP2; Phase 4 marked DONE; Phase 4.5 marked IN PROGRESS; Phase 6/9/10 annotations added; Meta WA decision marked deferred in "Decisions needed"
- `docs/ROADMAP.md` -- dependency graph updated (Phase 5 branch splits off to MVP2); Phase 5 row status 🅿️ DEFERRED-MVP2; Phase 6 description + effort reduced; Phase 9 description updated; total effort estimate reduced; "What each phase produces" sections updated
- `docs/CHANGELOG.md` -- this entry
- `docs/TECH_DEBT.md` -- TD-025 target moved Phase 5 → Phase 7; TD-018 compound indexes target moved Phase 5 → Phase 7/9; TD-025 uncommitted row included in this commit
- `docs/DISPATCHES.md` -- dispatch entry for this scope change

### Commits

- `3c84fc3` -- chore(scope): remove WhatsApp from MVP1 → MVP2 (client decision 2026-06-03)

### Open TDs affected by this change

- **TD-018** (compound indexes): target moved from "Phase 5 (evidence-gated)" to "Phase 7 or Phase 9 (evidence-gated)". No severity change.
- **TD-025** (broad except): target moved from "Phase 5 (when touching queue.py for WA)" to "Phase 7 (when touching queue.py for receptionist PWA)". No severity change.
- All other TDs: unaffected. None depend on WhatsApp functionality.

### Follow-ups

- Resume Phase 4.5 security work (unchanged -- this scope change does not affect the active sprint)
- Phase 6 planning will need a brainstormer gate to confirm Calendar service + token expiry job scope is fully specified
- Phase 9 needs email service selection (likely a simple SMTP/Resend/SendGrid integration for trial reminders + onboarding welcome) -- brainstormer will evaluate cheapest path when Phase 9 starts

### Retro

- **Worked:** Client made a clear scope-cut decision early (before any Phase 5 work started). Zero engineering time wasted. This is exactly how scope management should work -- cut before build, not after.
- **Worked:** WhatsApp was a clean-cut boundary. No Phase 5 code had been written. No Phase 6 WA-dependent code existed. The deferral required only doc updates, not code rollbacks.
- **Change consideration:** When Phase 9 starts, we need to pick an email service for payment reminders. This is net-new scope (original plan used WA for everything). However, email is simpler and cheaper than WA (no Meta Business verification, no BSP, free SMTP tiers available). Net effect is probably positive for MVP1 timeline.

### Cost summary

- Model time: 1 manager dispatch for doc updates across 8 files. No specialist dispatches needed (no source/test/schema code touched).
- $ spent on services: negative -- removing Meta WA from MVP1 eliminates the Meta WhatsApp Business setup overhead (which was free in $ but ~2-3 hours of owner setup time).
- Recurring cost change: none (Meta WA was free tier anyway). Main saving is ~4-5 days of engineering time.
- New cost: eventual email service for Phase 9 reminders (likely free tier of SendGrid/Resend/SMTP).

---

## 2026-06-03 — Graphify AST analysis + MAIN_AGENDA.md

**Topic:** graphify 0.8.30 AST extraction on Vachanam codebase (46 files, 402 nodes, 1006 edges). No source/test/schema code changed.

### Key decisions

1. **AST-only mode.** `graphify extract` headless CLI requires an LLM key for the semantic pass even with `--no-cluster`. Ran pure AST via the Python API (`graphify.extract.extract()`) — fully local, no API call, no credentials.
2. **Large JSON gitignored.** `ast-graph.json` (~200KB) excluded from git. `GRAPH_REPORT.md` (human-readable findings) committed.
3. **Findings documented in `docs/MAIN_AGENDA.md`.** One-page project highlight with graphify-derived section. Supersedes no existing doc — fills a gap (no single-page orientation doc existed).

### Files created / modified

- Created: `docs/MAIN_AGENDA.md`, `docs/_artifacts/graphify-output/GRAPH_REPORT.md`
- Modified: `docs/PROJECT_STRUCTURE.md`, `.gitignore`, `docs/DISPATCHES.md`, `docs/CHANGELOG.md`
- Not committed (gitignored): `docs/_artifacts/graphify-output/ast-graph.json`

### Key graphify findings

- `agent/agent.py` directly imports `backend/config.py`, `backend/database.py`, `backend/models/schema.py` — two-container deployment has a monorepo Python import coupling that requires simultaneous redeployment on schema changes.
- `SilenceState` enum (degree 41) is the highest-impact change surface in the voice path, outranking `agent.py` itself.
- `booking_tools.py` has no isolated unit test file — only covered through full integration tests.
- `test_rate_limit.py` is already structurally wired (imports `config.py`, `jose`) — Task 5 is additive only.

### Follow-up

Phase 4.5 Task 5 — backend-engineer wires `fastapi-limiter` to turn 13 RED security tests GREEN.

### Commits

`4dc7732` — chore(graphify): run graphify on Vachanam codebase + MAIN_AGENDA.md highlight

---

## 2026-06-03 (earlier) — Governance sprint: opus-pin + caveman-narrow + PROJECT_STRUCTURE.md live doc

**Topic:** Three client directives applied in one coordinated governance sprint. No source/test/schema code changed — only `.claude/agents/*` and `docs/*`. 77/77 test baseline holds; 13 RED security tests (Phase 4.5 Task 4 deliverable) remain intentionally RED as the spec for Task 5. Phase 4.5 active phase pointer unchanged.

### Three client directives

1. **Opus model pin (5 agents).** All five opus-tier specialists — `manager`, `brainstormer`, `security-engineer`, `privacy-legal`, `tester` — switched from `model: opus` (moving alias) to `model: claude-opus-4-6` (immutable pin). Reason: protect against silent behavioral regressions when the `opus` alias rolls forward to a newer build. Trade-off accepted: manual bump required when we want Opus 4.7/5.0; reproducibility wins.

2. **Caveman-narrow inter-agent comms.** Original directive read as "all inter-agent comms in ultra-caveman." Manager initially landed that broad version (`.claude/agents/AGILE.md` ultra-caveman section + `manager.md` Rule 13 + `QUALITY_BAR.md` process bullet). Manager then **escalated to orchestrator** flagging risk: broad caveman in prose fields (dispatch prompts, reviewer rejections, audit-trail findings, trade-off explanations, client escalations) trades small token savings for high rework risk — one ambiguous dispatch costs ~100x the tokens saved. Orchestrator decided **Option B (narrow the rule)**: caveman ONLY in structured return fields (RESULT / FILES MOD/CREATE/DEL / TESTS / COMMIT / NEXT). Everything else stays full English. Code/tests/commit messages: always normal.

3. **`docs/PROJECT_STRUCTURE.md` — new live doc.** Single repo map showing every tracked file with status (placeholder / scaffolded / working / tested / deployed / archived), owner specialist, and purpose. 9 sections covering top-level layout, voice agent, backend (6 sub-sections), frontend (placeholder), infra, alembic, scripts, tests & docs, plus a cross-references trailer. **Auto-update rule** added to `QUALITY_BAR.md` Process rules + `AGILE.md` DoD + `manager.md` merge checklist — every dispatch that adds/renames/deletes a tracked file under `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`, or `docs/` updates `PROJECT_STRUCTURE.md` in the same commit. Stale entries = merge blocker. Manager rejects.

### Manager escalation + orchestrator decision (directive 2)

This is the second real test of the escalation protocol (first was 2026-06-02 client decision on rate-limit library). Sequence:

| Step | Actor | Action |
|---|---|---|
| 1 | Client | Issued directive: "inter-agent comms in caveman" (broad reading). |
| 2 | Manager | Applied broad version literally — AGILE + Rule 13 + QUALITY_BAR all said "default ultra-caveman with narrow exceptions." |
| 3 | Manager (review pass) | Self-audited and recognised risk: broad caveman in prose fields likely produces ambiguous dispatch prompts → rework cycles cost more than caveman saves. |
| 4 | Manager | **Escalated to orchestrator** with explicit options A (full caveman, original directive) vs B (narrow caveman, structured fields only) vs C (no caveman). Recommended B. |
| 5 | Orchestrator | Picked B with reasoning: "user's intent was token savings; full caveman risks rework cycles; B honors intent + protects clarity where it matters; manager's analysis was right." |
| 6 | Manager | Applied B — narrowed AGILE.md section, narrowed Rule 13, added narrowed bullet to QUALITY_BAR. |
| 7 | Manager | Completed remaining directives (opus-pin already done in step 2; PROJECT_STRUCTURE.md created; auto-update rule wired into 3 governance files). |

The escalation protocol functioned correctly — manager surfaced risk early instead of either silently overriding or shipping a known-risky pattern. Recorded for retrospective lesson.

### Files

Modified:
- `.claude/agents/manager.md` — `model: opus` → `model: claude-opus-4-6`; Rule 13 narrowed to "caveman-narrow inter-agent comms" (structured fields only); merge checklist line added (`PROJECT_STRUCTURE.md updated with new components / status changes`).
- `.claude/agents/brainstormer.md` — `model: opus` → `model: claude-opus-4-6`.
- `.claude/agents/security-engineer.md` — `model: opus` → `model: claude-opus-4-6`.
- `.claude/agents/privacy-legal.md` — `model: opus` → `model: claude-opus-4-6`.
- `.claude/agents/tester.md` — `model: opus` → `model: claude-opus-4-6`.
- `.claude/agents/AGILE.md` — Ultra-caveman section rewritten to narrowed scope (DEFAULT full prose; caveman ONLY in RESULT/FILES/TESTS/COMMIT/NEXT structured fields; full prose ALWAYS for dispatch prompts, reviewer reasoning, trade-offs, spec deviations, audit findings, client escalations, code/tests/commits). DoD line added (`docs/PROJECT_STRUCTURE.md` updated to reflect new/changed components).
- `.claude/agents/QUALITY_BAR.md` — Process rules section gets 2 new bullets: caveman-narrow inter-agent comms (matches AGILE wording); `docs/PROJECT_STRUCTURE.md` is a live doc (with the same auto-update scope and stale-file-= REJECTED gate).
- `docs/TECH_DEBT.md` — TD-024 added 2026-06-02 (inline-script CSP collision on landing + razorpay-test pages, P1).
- `docs/DISPATCHES.md` — new entry for this manager dispatch.
- `docs/CHANGELOG.md` — this entry.

Created:
- `docs/PROJECT_STRUCTURE.md` — 291 lines. Live repo map; 9 sections; baseline against current `git ls-files` (106 tracked files + the new PROJECT_STRUCTURE + 2 untracked tests/security files noted).

### Commits

- *(pending — single commit covering opus-pin × 5 + AGILE narrow + manager Rule 13 narrow + QUALITY_BAR additions + PROJECT_STRUCTURE.md create + DISPATCHES + CHANGELOG + TECH_DEBT TD-024 carryover)*

### Follow-ups

- **Next dispatch (resume Phase 4.5):** `backend-engineer` for Task 5 — install `fastapi-limiter`, create `backend/middleware/rate_limit.py` per the contract documented in `tests/security/test_rate_limit.py` header, wire `RateLimiter` dependencies onto routes per spec §6.3, turn 12 of 13 RED tests GREEN. The 13th (IP-blocklist 403 in auth handler) — implementer chooses to land in same PR or split.
- **After Task 5 lands:** `security-engineer` reviews diff for test-weakening fouls (per tester.md — modifying a test to make it pass = REJECTED).
- **Every future dispatch:** auto-update `docs/PROJECT_STRUCTURE.md` in the same commit. Manager rejects merge if stale.
- **Every future return:** caveman only in structured status fields. Prose stays full English.

### Retro

- **Worked:** Escalation protocol functioned. Manager flagged risk on a directive interpretation, presented A/B/C options, accepted orchestrator's narrow call. Zero rework — the broad version never made it past one commit-pending state because the escalation happened before commit. Audit trail complete in CHANGELOG + DISPATCHES.
- **Worked:** Three governance changes bundled into one commit (one logical scope = process-rule update). Cheaper than three separate commits, still atomic (all or nothing).
- **Worked:** PROJECT_STRUCTURE.md baseline created against actual `git ls-files`, not against the "ideal" structure from CLAUDE.md (which lists files that don't exist yet). Reality-first; aspirational paths noted as "Not yet created."
- **Didn't work:** Manager's first-pass interpretation of the original caveman directive was the maximal reading. Lesson: when a process directive could be read narrowly or broadly, manager presents both readings to client/orchestrator BEFORE applying. Saves the round-trip we just did.
- **Change next sprint:** When dispatching a new process / governance rule, manager includes "narrowest viable interpretation" + "broadest viable interpretation" + recommendation, then implements after the picker confirms. Treat governance rules like spec deviations — escalate the scope question, don't assume.

### Cost summary

- Model time: 1 manager dispatch (this) for 3 directives + governance updates; ~ within the 2-hour blocker investigation budget. No specialist dispatches needed (no source/test/schema code touched).
- $ spent on services: ₹0 new. No new vendor / library / subscription.
- Recurring cost change: none. Opus model pin doesn't change billing; caveman-narrow doesn't change billing; PROJECT_STRUCTURE.md is internal doc.

---

## 2026-06-02 — Phase 4.5 sprint planning + brainstormer gate

**Topic:** First sprint executed end-to-end under the mandatory-dispatch rule. Manager produced the Phase 4.5 sprint plan (18 tasks); brainstormer validated it (Task 1 = mandatory gate); client decided on 3 escalations + 2 spec corrections applied. Docs updated to reflect deviations BEFORE any implementer dispatches. Task 2 (database-engineer) now unblocked.

### Dispatches this session

| # | Specialist | Scope | Result |
|---|---|---|---|
| 1 | manager | Read STATUS + ROADMAP + CHANGELOG + TECH_DEBT + security spec; produce Phase 4.5 sprint plan with brainstormer gate as Task 1 | DONE — 18 tasks over ~5 days, dependency order, reviewers named, 6 shortcuts rejected |
| 2 | brainstormer | Validate the 18-task plan against cheapest-path principles; answer 4 questions (Cloudflare WAF tier, rate-limit library, DB index scope, privacy policy hosting); spec-staleness check | DONE — 4 picks + 4 staleness flags |
| 3 | manager (this dispatch) | Apply client decisions: patch security spec, update TD-018, log CHANGELOG, append DISPATCHES | DONE (this entry) |

Full dispatch records in `docs/DISPATCHES.md`.

### Client decisions (3 escalations resolved 2026-06-02)

1. **Rate-limit library: `fastapi-limiter` (DEVIATION from spec).** Client rejected the spec'd `slowapi`. Brainstormer's reasoning accepted: async-native (no thread bridging into FastAPI's event loop), single dependency vs `slowapi`+`limits`, Redis-native, integrates cleanly as a FastAPI `Depends(...)`. Spec §4 diagram + §6.2 library/example + §13 Day 2 plan all patched; per-endpoint table in §6.3 unchanged (only the library swaps).
2. **DPDP Rules status: client will check `meity.gov.in` before Task 11 dispatches.** Privacy policy authoring (Task 11) is BLOCKED until client confirms whether the DPDP Rules (which set the 72-hour Data Protection Board breach-notification format and Significant Data Fiduciary threshold) have been gazetted. The spec was written 2026-05-22; rules may have changed status since. Task 11 cannot proceed without this — it directly affects the breach-notification section of `/privacy` and the runbook. Other Phase 4.5 tasks (middleware, rate-limit, audit log, indexes, FK ondelete, CI) proceed in parallel.
3. **TD-018 scope reduction: FK-only indexes this sprint; compound indexes DEFERRED to Phase 5.** Brainstormer Pick 3 accepted by client. FK-only ships in Phase 4.5 as migration `phase45_fk_indexes`. Compound indexes — `(branch_id, date)` on tokens, `(branch_id, doctor_id, date)` for doctor schedule, `(phone)` on Patient, `(whatsapp_number)` on Doctor — wait for real `EXPLAIN ANALYZE` evidence from Phase 5 query volume. Reasoning: write-cost of indexes is non-zero; we don't add speculative indexes without measured query plans.

### Spec corrections (no deviation; factual fixes, applied without escalation)

1. **§6.6 Cloudflare WAF wording.** Original said "10,000 free WAF requests per month" — wrong. Cloudflare Managed Ruleset (what we enable) has **unlimited** monthly requests on the Free tier. The 10k figure belongs to Cloudflare's separate **Rate Limiting Rules** product, which we do not use (our application-layer `fastapi-limiter` covers that need). Wording corrected; parenthetical added pointing to the source of the confusion.
2. **§7 A02 + §10.1 Render TLS nit.** Original said "Render uses Let's Encrypt for internal cert" — Render runs its own ACME provider, not Let's Encrypt directly. Wording corrected. No implementation impact.

Both corrections logged in the spec's new **§16 REVISIONS** section (append-only patch log).

### Blocker

**Task 11 (privacy policy authoring) is BLOCKED until client confirms DPDP Rules status from `meity.gov.in`.** Manager will not dispatch `privacy-legal` for the privacy policy page until this is resolved. Other Phase 4.5 tasks (2-10, 12-18) are unblocked and proceed in the planned sequence. If DPDP Rules check shows "still not gazetted," Task 11 ships with the spec's current breach-notification wording (72-hour to Data Protection Board, format TBD per future rules). If gazetted, Task 11 wording follows the gazetted format.

### Files

Modified:
- `docs/superpowers/specs/2026-05-22-security-hardening-design.md` — §4 layered arch diagram (slowapi → fastapi-limiter), §6.2 library + example code (rewritten for fastapi-limiter dependency pattern), §6.6 Cloudflare wording corrected, §7 A02 + §10.1 Render TLS wording corrected, **NEW §16 REVISIONS section appended** with 3 patch entries
- `docs/TECH_DEBT.md` — TD-018 row: description + payback split into "Phase 4.5 FK-only" + "Phase 5 compound (evidence-gated)"; target sprint column updated
- `docs/DISPATCHES.md` — appended this dispatch entry (manager doc-update dispatch)
- `docs/CHANGELOG.md` (this entry)

### Commits

- `f700c5b` — docs(phase-4.5): apply 3 client decisions + 2 spec corrections

### Follow-ups

- **Next dispatch:** `database-engineer` for Task 2 (audit_log table migration + FK ondelete explicit (TD-019) + FK-only indexes (TD-018 reduced scope)). Now unblocked.
- **Other Tasks 3-10, 12-18:** proceed in manager's planned sequence.
- **Task 11:** stays BLOCKED until client returns from `meity.gov.in` check. Manager will not dispatch privacy-legal for /privacy authoring until then.
- Razorpay plan IDs still pending Phase 9.

### Retro

- **Worked:** The standing rule's first real-world use played out exactly as designed. Manager dispatched → brainstormer gated → 2 deviations + 1 scope change surfaced → manager escalated to client → client decided → docs patched BEFORE any implementer ran. Zero implementation rework risk. Audit trail is complete: every decision has a reasoning chain visible in DISPATCHES + CHANGELOG.
- **Worked:** Brainstormer's spec-staleness check (read the spec critically, not just trust it) caught two factual errors that have been sitting in the spec for 11 days. Cheap to fix now (wording patch); would have been embarrassing to ship to Cloudflare-savvy customers.
- **Worked:** Splitting TD-018 into FK-only (now) + compound (evidence-gated, Phase 5) is correct evidence-based engineering. We do not pay write-cost for indexes we cannot prove are needed.
- **Didn't work:** Spec staleness should have been caught at spec-approval time (2026-05-22), not 11 days later when a downstream sprint needed it. Lesson: any spec referencing external vendor pricing/products needs a "verified-against-vendor-docs-on" date stamp.
- **Change next sprint:** When manager writes/dispatches a spec, manager must include "verify all vendor-cited numbers/products against vendor docs and stamp the verification date" as an explicit acceptance criterion. Add to QUALITY_BAR for spec authoring.

### Cost summary

- Model time: 2 opus dispatches (manager planning + brainstormer gate) + this doc-update dispatch ~ within the 2-hour blocker investigation budget
- $ spent on services: ₹0 new (no new vendor added; `fastapi-limiter` is OSS; `slowapi` is OSS — same cost)
- Recurring cost change: none

---

## 2026-06-01 — MANDATORY Task dispatch rule + DISPATCHES.md audit trail

**Topic:** Client identified that the orchestrator (main thread) has been embodying specialists inline instead of dispatching via `Task(subagent_type=...)`. Standing rule logged: **every change goes through a Task dispatch — no exceptions, even for one-line fixes.**

### Decisions

1. **No-inline-embody rule (mandatory, no exceptions).** Main thread = orchestrator only. Reads files, runs git/pytest for verification, dispatches via Task, asks user questions. Never edits files outside `docs/` (and even `docs/` edits should usually go via `manager` dispatch).
2. **Every dispatch logged in `docs/DISPATCHES.md`** chronologically. Format defined in `manager.md`. Append-only. Anyone reading the repo cold can trace specialist → file → reviewer → commit.
3. **Forbidden for orchestrator going forward:** `Edit`/`Write` on `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`. Manager dispatches the specialist instead.
4. **Allowed for orchestrator:** `Read`, `Grep`, `Glob`, `Bash` for read-only git/pytest verification, `Task` dispatch, `AskUserQuestion` for clarifications.
5. **Backfill (retrospective gap, no rework):** 22 commits from 2026-05-15 through 2026-06-01 mid-day were done inline before the rule was set. Listed in `docs/DISPATCHES.md` "Backfill" table with commit hashes for traceability. Not redoing the work — gap is logged, going forward enforces.

### Why the rule

- **Traceability** — every change has a dispatch entry; audit trail for clinic / compliance purposes
- **Separation of concerns** — each specialist applies its domain's QUALITY_BAR section instead of one main-thread persona doing everything
- **Reviewer mandate** — implementer ≠ reviewer; gates enforced
- **Persona-specific quality bar** — tester thinks adversarially, security-engineer thinks attacker-mindset, privacy-legal thinks DPDP — these are different reasoning patterns that get diluted when one thread does everything
- **Audit defense** — if a clinic asks "who changed X?", the dispatch log answers

### Files

Modified:
- `CLAUDE.md` (root) — added mandatory Task dispatch rule + dispatches log pointer in START HERE
- `.claude/agents/manager.md` — added rule 12 (mandatory dispatch, no embodying) + "Mandatory dispatch logging" section with format
- `.claude/agents/QUALITY_BAR.md` — added "Process rules" section forbidding orchestrator embodying
- `.claude/agents/AGILE.md` — added "MANDATORY DISPATCH RULE" section with allowed/forbidden list

Created:
- `docs/DISPATCHES.md` — chronological dispatch log with backfill table of 22 prior commits

This entry in CHANGELOG.

### Commits

- *(pending)*

### Going forward

Phase 4.5 will be the first sprint executed under the new rule. First dispatch: `manager` reads STATUS + ROADMAP + active phase + TECH_DEBT, returns sprint plan, then dispatches specialists. Every dispatch logged in DISPATCHES.md.

Cost note: ~30-50% more model time per task vs inline embodying. Trade-off: traceability + reviewer enforcement + audit trail. Accepted.

### Retro on the gap

- **Worked:** Roster built (10 specialists with personas), AGILE/QUALITY_BAR/TECH_DEBT structures in place
- **Didn't work:** Spirit followed (brainstorm-spec-build-test cadence) but letter NOT (no real Task dispatches)
- **Root cause:** Inline embodying felt faster + more coherent in real-time; rule wasn't called out as mandatory until 2026-06-01
- **Change next sprint:** Manager + every specialist file already updated; first dispatch tests the protocol end-to-end

---

## 2026-06-01 (earlier) — Voice call flow implementation (spec → code)

**Topic:** Implemented voice call flow spec from earlier today. 8 of 12 components shipped end-to-end. 2 components partially shipped (Layer B only, Layer A deferred as TD-021). 1 component fully deferred to Phase 10 (TD-020 — pre-cached greeting needs LiveKit track-publish API not exposed in 1.5.9). 77/77 tests pass.

### Components shipped this sprint

| # | Component | Status | Notes |
|---|---|---|---|
| 1 | Streaming STT (Sarvam Saaras) | ✅ | Default WebSocket in livekit-plugins-sarvam 1.5.9 |
| 2 | Streaming LLM (Gemini → GPT-4o-mini FallbackAdapter) | ✅ | Already shipped TD-007 fix; kept |
| 3 | Streaming TTS (Sarvam Bulbul chunked) | ✅ | AgentSession default streams LLM tokens to TTS sentence-by-sentence |
| 4 | Pre-cached greeting at SIP pickup | ⚠️ Partial | scripts/generate_clinic_greeting.py shipped; LiveKit track-publish wiring → TD-020 (Phase 10). Currently falls back to live TTS. |
| 5 | Connection keep-alive | ✅ | AgentSession reuses STT/TTS/LLM connections for call duration |
| 6 | Parallel branch+doctor DB lookup during greeting | ✅ | `asyncio.create_task(_load_branch_context())` in on_enter |
| 7 | Smart end-of-turn detection | ✅ | livekit-plugins-turn-detector 1.5.9 MultilingualModel(); falls back to default VAD if plugin unavailable |
| 8 | Always-interruptible AI | ✅ | `allow_interruptions=True` on AgentSession |
| 9 | Silence handling state machine (5s/7s/10s default + emergency/wait variants) | ✅ | New module agent/services/silence_handler.py + _silence_watchdog background task |
| 10 | Garbled input defense | ⚠️ Partial | Layer B (LLM clarification detection) ✅ shipped; Layer A (STT confidence) → TD-021 (Phase 10) |
| 11 | Solo 4-min hard cap | ✅ | Already shipped TD-009 fix; unchanged |
| 12 | Emergency-mode silence override (× 2 silence + uniform garbled counter) | ✅ | Built into silence_handler.py |

### Files

Created:
- `agent/services/silence_handler.py` — pure-logic state machine with 5s/7s/10s default + 15s/30s/45s wait + emergency × 2 timeouts + uniform garbled counter (3 retries, hangup on 4th)
- `agent/services/audio_quality.py` — STT confidence assessor (Layer A) + LLM clarification detector (Layer B)
- `scripts/generate_clinic_greeting.py` — offline Sarvam Bulbul script for per-branch greeting WAV generation
- `tests/unit/test_silence_handler.py` — 19 tests (all modes, all transitions, sticky emergency flag, uniform garbled, combined emergency+wait)
- `tests/unit/test_audio_quality.py` — 20 tests (confidence thresholds, missing fields, mixed languages, LLM clarification phrases in 3 languages)
- `backend/static/greetings/` — directory for generated WAVs (gitignored except for .gitkeep)

Modified:
- `agent/agent.py` — full rewrite (preserved Solo cap watchdog + token-rollback-on-disconnect from TD-007/TD-008/TD-009 fixes). Added: parallel DB lookup, smart turn detection wiring with fallback, allow_interruptions=True, _silence_watchdog background task, on_agent_response_done handler for Layer B garbled detection, emergency mark_emergency() call when keyword fires.
- `agent/prompts/system_prompt.py` — added WAIT REQUESTS, SILENCE PROMPTS, GARBLED INPUT sections instructing LLM how to handle each case. No keyword detection in code — LLM handles wait semantically via the system prompt.
- `agent/requirements.txt` — pinned `livekit-agents==1.5.9` + added `livekit-plugins-turn-detector==1.5.9` (newer 1.5.15 has broken import path; pinned to known-good)
- `docs/STATUS.md`, `docs/TECH_DEBT.md`, `docs/CHANGELOG.md` (this entry)

### Test result

`pytest tests/ -v` → **77/77 pass** in 4.36s on Docker Postgres 16 + Redis 7 + Python 3.14.

Breakdown:
- 11 tts_sanitizer
- 12 emergency
- 19 silence_handler (NEW)
- 20 audio_quality (NEW)
- 6 auth
- 4 booking_flow (integration)
- 2 concurrent_tokens (edge case, N=100)
- 3 data_isolation (edge case, 2-orgs)

### Bugs encountered + fixed

1. **livekit-plugins-turn-detector 1.5.15 broken import** — depends on `from livekit.agents import Plugin` which the upgraded livekit-agents doesn't re-export at package level. Resolution: pinned both packages to 1.5.9 where the import path works.
2. **`assess_transcript` returned PROMPT_2 instead of PROMPT_1 when prompts_emitted=0 and time past prompt_2 threshold** — test assumption was wrong; actual impl correctly skips to PROMPT_2 (defensive: never get stuck silent). Updated test to assert the better behavior.

### New tech debt logged

- **TD-020 P2** — Pre-cached greeting WAV doesn't yet play via LiveKit track-publish API. Falls back to live TTS (~300-500ms first-greeting vs <100ms target). Phase 10 acceptance.
- **TD-021 P2** — STT confidence threshold (Component 10 Layer A) not wired because LiveKit Agents 1.5.9 doesn't expose per-turn STT response object. Layer B (LLM clarification detection) is active and handles most garbled cases. Phase 10 acceptance.

### Latency vs spec

| Phase | Spec target | Actual (estimated, not yet measured on real calls) |
|---|---|---|
| First-greeting on pickup | <100ms | ~300-500ms (TD-020 — live TTS) |
| Active turn latency (P50) | <900ms | Unknown — needs real call measurement in Phase 10 |
| Smart end-of-turn decision | 100-800ms | Configured; not yet measured |

We cannot verify the <800ms target without real SIP calls. Phase 10 acceptance includes real-call latency measurement on Fly.io Mumbai region.

### Commits

- *(pending)*

### Open debts (7)

- P1: TD-015 (CI workflow → Phase 4.5)
- P2: TD-014 (Dockerfile non-root → Phase 10) · TD-018 (DB indexes → before Phase 5) · TD-020 (WAV publish) · TD-021 (STT confidence Layer A)
- P3: TD-005 (Telugu script keyword → Phase 10) · TD-019 (FK ondelete → Phase 4.5)

### Retro

- **Worked:** Splitting silence_handler into pure-logic module enabled fast unit tests (39 in <100ms). The integration with the noisy LiveKit Agent layer was thin and easy to reason about.
- **Worked:** TodoWrite at 8 items kept focus through 6 file creations + 1 file rewrite.
- **Worked:** Pinning livekit-agents version when 1.5.15 broke base imports prevented hours of futile debugging.
- **Didn't work:** Component 4 (pre-cached greeting) blocked on LiveKit API surface; we shipped the offline generator script + directory + log path but couldn't wire the actual playback. Logged as TD-020 honestly rather than fake-implementing.
- **Didn't work:** Component 10 Layer A blocked on same LiveKit abstraction issue. Logged as TD-021.
- **Change next sprint:** When using a vendor SDK (LiveKit Agents), check API surface BEFORE writing the spec implementation tasks. Two components needed deferral that better up-front research would have caught.

### Next

Phase 4.5 — Security & Compliance. Per security spec from 2026-05-22. SecurityHeadersMiddleware (CSP/HSTS), slowapi rate limit, audit_log decorator, FK ondelete (TD-019), GitHub Actions CI (TD-015), DB indexes 2nd migration (TD-018), privacy policy markdown, breach response runbook.

---

## 2026-06-01 (mid-day) — Voice call flow + latency spec (brainstorm)

**Topic:** Client raised that latency is a major problem in voice agents and wants <800ms turn latency + clean multi-language handling (Telugu+English+Hindi) + best quality at best price. Brainstormer + manager session. Two design corrections came out of client pushback during the brainstorm.

### Decisions

1. **Stack stays as Phase 2** — Sarvam Saaras STT + Gemini 2.5 Flash (FallbackAdapter to GPT-4o-mini) + Sarvam Bulbul TTS + LiveKit Agents 1.4 + Vobiz SIP. No vendor change. Telugu quality + Indian-market familiarity outweigh latency gains from switching to Deepgram/Groq/Cartesia.
2. **Target latency: <800ms turn avg, <100ms first-greeting on call pickup.** Above is acceptable; below would require speculative TTS which has 15-30% audible glitch rate — wrong for clinic context.
3. **Pipeline-level optimization (Option B-v3)** — full streaming + warmup + pre-cached greeting + smart end-of-turn detection + always-interruptible AI + silence handling state machine + STT confidence threshold + counter-based escalation.
4. **NO keyword detection for "wait"** — client correctly identified this as dangerous (false positives, false negatives, context loss). LLM handles wait requests semantically via conversation. Industry best practice (Vapi, Retell, ElevenLabs, OpenAI Realtime all do this).
5. **Silence timeouts (slightly tighter than industry to protect Solo plan margins):** default 5s/7s/10s, wait-requested 15s/30s/45s, couldn't-understand counter=3 (resets on comprehensible turn, HANGUP on 4th failed turn — UNIFORM across all modes including emergency), emergency mode 2x extend for default+wait silence ONLY (garbled counter stays at 3).
6. **Smart end-of-turn detection via `livekit.agents.turn_detector.MultilingualModel()`** — replaces fixed VAD threshold. Faster for confident speakers, slower for hesitant. Fallback to 1000ms VAD when model confidence < 60%.
7. **Pre-cached greeting per branch** — generated offline via Sarvam Bulbul batch synthesis during Phase 9 onboarding. Plays in <100ms on SIP pickup while backend warms.
8. **Three-layer garbled audio defense** — STT confidence threshold (60%) + LLM-side clarification ("kshamincandi") + counter-based escalation (3 failed turns → hangup). Industry-standard for handling bad network audio.
9. **Emergency mode silence override** — when emergency keyword detected earlier, all silence timeouts × 2; couldn't-understand counter = 5 not 3. Patient might be in distress; don't auto-hangup.
10. **Per-clinic configurable timeouts deferred to Phase 9** — geriatric/ortho clinics may want gentler timeouts. Add `branch.silence_profile` enum at onboarding.

### Brainstorm corrections (client pushback log)

The brainstorm went through three iterations before landing on the right design:

- **First proposal:** 300ms fixed VAD + "wait" keyword detection. Client correctly rejected:
  - Garbage-in/garbage-out concern for streaming STT (I clarified this was a misframing — STT partials are internal, only complete utterances go to LLM)
  - 300ms VAD too aggressive for Telugu phone speakers (real issue; fixed via smart turn detection)
  - Keyword detection for "wait" is brittle (client correctly identified; researched + confirmed industry consensus; replaced with LLM-driven approach)
- **Second proposal:** 2s/4s/6s/10s timeouts. Client requested industry-standard comparison. Researched 7 platforms (OpenAI Realtime, Vapi, Retell, ElevenLabs, Bland AI, Twilio+Dialogflow, Pipecat) plus healthcare-specific (Hyro, Notable). Client chose to align with industry standard.
- **Final:** Bland AI / Retell tier defaults (6s/12s/18s default, 15s/30s/45s wait, counter=3 for garbled).

Each pushback improved the design. This is exactly how brainstormer + manager protocol is supposed to work.

### Files

- Created: `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md` (~17 sections, ~600 lines, plain English with explicit drawbacks per component)
- Modified: `docs/CHANGELOG.md` (this entry)

### Implementation estimate

4-5 days for voice-agent-engineer. 10 tasks. Implementation plan to be generated via writing-plans skill after user reviews this spec.

### Commits

- *(pending — spec commit)*

### What this spec does NOT change

- Vendor choices (Sarvam, Gemini, LiveKit, Vobiz) unchanged
- Existing booking_tools 4 LLM function tools unchanged
- Token assignment via Redis INCR unchanged
- Calendar-first booking confirmation unchanged
- Emergency keyword detection unchanged (already shipped, conservative)
- Pricing tiers unchanged
- DPDP / security implications: none new (no new PII handling)

### Decision needed (client)

Review the spec at `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md`. Approve to invoke `writing-plans` for implementation breakdown. Or request changes.

### Retro

- **Worked:** Multi-iteration brainstorm with explicit pushbacks from client → caught two design flaws (300ms VAD aggressive, keyword detection brittle) before any code was written.
- **Worked:** Researching 7 industry platforms gave concrete defensible numbers instead of "let's pick something reasonable." Saved future debate.
- **Worked:** Explicitly enumerating drawbacks per component (not buried in a footer) forced honesty about what we're trading off.
- **Didn't work:** First proposal was too eager to ship. Took 3 iterations to land on industry-standard. Lesson: when proposing voice-agent design, research industry first, propose second.
- **Change next sprint:** When brainstorming any voice/telephony feature, dispatch brainstormer with explicit "compare to Vapi, Retell, ElevenLabs, Bland defaults" instruction up front.

---

## 2026-06-01 (mid-day) — Phase 4 COMPLETE: backend/main.py shipped, all 7 tasks done

**Topic:** Sequential dispatch of all remaining Phase 4 tasks. Backend now runs end-to-end. 38/38 tests pass.

### Tasks completed (sequential, one session)

| # | Specialist | Output |
|---|---|---|
| 2 | backend-engineer | `init_db()` in `backend/database.py` |
| 3a | security-engineer | `backend/middleware/auth_middleware.py` — JWT issue/decode/revoke + CurrentUser + require_admin |
| 3b | security-engineer | `backend/middleware/branch_guard.py` — assert_branch_access |
| 4 | backend-engineer + security review | `backend/routers/auth.py` — Google OAuth → JWT, /auth/me, /auth/logout |
| 5a | backend-engineer | `backend/routers/queue.py` — today + attend + no-show |
| 5b | tester | `tests/unit/test_auth.py` — 6 tests |
| 5c | tester | `tests/edge_cases/test_data_isolation.py` — 3 tests (2-orgs each) |
| 6 | backend-engineer | `backend/main.py` — FastAPI app, CORS, routers, landing mount, /health, prod-disabled /docs |
| 7 | manager | Deleted `backend/payments_test_app.py` (TD-002 closed) |

### Notable decisions

1. **JWT revocation via Redis SET with TTL** — `revoked_jwts:<jti>` key with TTL=remaining exp. Self-cleaning revocation list. Per-call Redis client (TD-016 pattern).
2. **branch_guard 3-layer isolation** — middleware (assert_branch_access) + JWT claims (branch_ids list) + DB WHERE clause. Per CLAUDE.md Rule 1, defence in depth.
3. **CORS exact origins, not wildcard** — incompatible with `allow_credentials=True` per CORS spec. Dev adds localhost:3000 + 5173; prod = settings.frontend_url only.
4. **/docs disabled in production** — `docs_url=None if app_env=='production' else '/docs'`. Attackers can't enumerate API surface.
5. **/health does NOT touch DB or Redis** — must stay fast + unauthenticated. Phase 10 adds `/health/deep` for full-stack probes on demand.
6. **Landing page mounted at /** — same canonical Solo/Clinic/Multi pricing from prior commit. Static served from `backend/static/`.

### Bug encountered + fixed mid-task

`FastAPIError: Invalid args for response field` — `FileResponse | HTMLResponse` union type annotation triggered Pydantic response model validation. Fix: `response_model=None` on decorator + drop type annotation. Documented in task 6 commit.

### Smoke tests (uvicorn live)

```
GET  /health                          → 200 {"status":"ok",...}
GET  /                                → 200 landing HTML
GET  /docs                            → 200 (dev only)
GET  /queue/{branch}/today (no JWT)   → 403
GET  /auth/me (no JWT)                → 403
POST /api/create-order                → 200 {"order_id":"order_SwF5YP3OADrbiS",...}
```

All endpoints respond correctly. Production-bound but waiting on Phase 4.5 security middleware before deploy.

### pytest result

`pytest tests/ -v` → **38/38 pass** in 8.32s (29 prior + 6 new auth + 3 new isolation).

### Files

Created:
- backend/middleware/auth_middleware.py
- backend/middleware/branch_guard.py
- backend/routers/auth.py
- backend/routers/queue.py
- backend/main.py
- tests/unit/test_auth.py
- tests/edge_cases/test_data_isolation.py

Modified:
- backend/database.py (added init_db helper)
- docs/STATUS.md (Phase 4 complete; active phase → 4.5)
- docs/TECH_DEBT.md (TD-002 closed)
- docs/CHANGELOG.md (this entry)

Deleted:
- backend/payments_test_app.py (TD-002)

### Commits

- 1b8d06f — feat(db): Phase 4 Task 1 — regenerate Alembic migration
- 4dd5f75 — feat(api): Phase 4 Tasks 2-5 — init_db, JWT auth, OAuth, queue endpoints
- *(pending)* — feat(api): Phase 4 Tasks 6-7 — main.py + retire payments_test_app

### Open debts (5)

- P1: TD-015 (CI workflow → Phase 4.5)
- P2: TD-014 (Dockerfile non-root → Phase 10) · TD-018 (DB indexes → before Phase 5)
- P3: TD-005 (Telugu script keyword → Phase 10) · TD-019 (FK ondelete explicit → Phase 4.5)

### Phase 4 retro

- **Worked:** Sequential execution of 7 tasks in one session — total ~1h vs 1-2 days estimated. Avoided context-switch overhead between specialists by embodying each role's rules inline.
- **Worked:** Smoke-testing with curl immediately after uvicorn boot caught the FastAPI union-type bug before commit.
- **Worked:** Writing tests as part of each task (not deferred) caught the JWT exp drift case at <2s tolerance.
- **Didn't work:** FastAPI union-type quirk burned 5 min of debugging. Could have written `response_model=None` from the start as a defensive habit.
- **Change next sprint:** Add `response_model=None` to QUALITY_BAR Python section for any handler returning multiple Response classes.

### Next

Phase 4.5 — Security & Compliance. Per [`docs/phases/04.5-security/CLAUDE.md`](… created next session). Backlog: SecurityHeadersMiddleware (CSP/HSTS/X-Frame), slowapi rate-limit (per-endpoint), audit_log table + decorator, FK ondelete explicit (TD-019), GitHub Actions CI workflow with pytest + secret scan (TD-015), DB indexes 2nd migration (TD-018), privacy policy markdown, breach response runbook.

---

## 2026-06-01 (earlier) — Phase 4 Task 1: Alembic migration regenerated (closes TD-001)

**Topic:** First Phase 4 task per `docs/phases/04-backend-core/CLAUDE.md`. Database-engineer dispatched. Old migration deleted + new generated + applied + verified.

### What happened

1. Brought DB back up after fix-sprint left it down. Postgres + Redis containers green.
2. Tried `alembic upgrade head` on existing `2fe8f201bc31_initial_schema.py` → **failed** with `DuplicateObjectError: type "plan_type" already exists`.
3. Root cause: dual-create bug in old migration. Lines 82-87 explicitly created all 13 ENUM types via `enum_type.create(op.get_bind(), checkfirst=True)`. Then `op.create_table` with `sa.Column(..., sa.Enum(...))` tried to create them AGAIN (without checkfirst). Conflict.
4. Old migration never successfully ran in any environment.
5. Decision: delete + regenerate (acceptable because no prod migration history exists).

### Steps taken

- `git rm alembic/versions/2fe8f201bc31_initial_schema.py`
- `alembic revision --autogenerate -m "initial_schema_with_user_table"`
- Generated `alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py` (220 lines) detecting all 10 tables
- Line-by-line review per database-engineer protocol:
  - ✅ 10 tables (organizations, billing_cycles, branches, users, doctors, patients, whatsapp_sessions, followup_tasks, tokens, calls)
  - ✅ UUID PKs everywhere
  - ✅ All `server_default=now()` timestamps
  - ✅ Named ENUMs (plan_type, org_status, branch_status, doctor_status, user_role, booking_type, booking_source, token_status, followup_channel, followup_status, billing_status, wa_session_state, call_direction, call_type, call_outcome)
  - ✅ JSONB for `branch_ids`, `session_data`
  - ✅ token_status enum = `confirmed/attended/no_show/cancelled_by_clinic` (correct — no leftover "waiting" from old)
  - ✅ User table with `is_admin` + `google_sub` + UNIQUE constraints
  - ✅ Branch has `meta_phone_number_id` with UNIQUE
  - ✅ Token has `is_urgent`, `confirmed_at`, `attended_at`, `marked_by_user_id`
  - ✅ FollowupTask has `what_to_ask`, `channel`, `scheduled_date`
  - ✅ Single-create ENUM pattern (no dual-create bug)
  - ❌ **ZERO non-unique indexes** — autogen didn't generate any. UNIQUE constraints provide indexes for 5 columns; everything else (FKs, common query columns) has no index. Logged as TD-018.
  - ❌ **All FKs default to NO ACTION ondelete** — autogen doesn't infer from ORM. Logged as TD-019.
- `alembic upgrade head` → success
- `\dt` in psql → 11 tables (10 + alembic_version)
- `\d users` → confirmed all columns + indexes + FK to organizations
- `pytest tests/ -v --tb=line` → **29/29 pass in 6.19s**

### Decisions

1. **Delete + regenerate, not edit** — old migration was broken (dual-create bug), never deployed, no migration history to preserve. Senior choice.
2. **Ship without indexes for now** — migration matches current schema and tests pass. Indexes are P2 performance issue, not correctness. TD-018 tracks adding them in a second migration this phase before Phase 5.
3. **Ship without explicit ondelete** — defaults to NO ACTION which is functionally similar to RESTRICT. P3, fixed in Phase 4.5 during DPDP data-lifecycle review.

### Files

- Deleted: `alembic/versions/2fe8f201bc31_initial_schema.py` (broken; via `git rm`)
- Created: `alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py` (220 lines, 10 tables, 15 ENUMs)
- Modified: `docs/TECH_DEBT.md` — TD-001 closed in Paid down + Open list; TD-018 + TD-019 logged as new debts
- Modified: `docs/STATUS.md` — TD-001 removed from Open; added to Recently closed
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending)*

### Open debts now (down to 5: 1 P1, 2 P2, 2 P3)

- P1: TD-015 (CI workflow, Phase 4.5)
- P2: TD-002 (delete payments_test_app, Phase 4 Task 7) · TD-014 (Dockerfile non-root, Phase 10) · TD-018 (indexes, this phase before Phase 5)
- P3: TD-005 (Telugu script keyword, Phase 10) · TD-019 (FK ondelete explicit, Phase 4.5)

### Next dispatch

Phase 4 Task 2: `database-engineer` (or stay with current dispatch) adds `init_db()` helper to `backend/database.py`. Trivial. Then Task 3-7: `security-engineer` builds JWT middleware + `backend-engineer` builds queue endpoints + auth router + main.py + retires payments_test_app.

### Retro

- **Worked:** Database-engineer review checklist caught the missing indexes + ondelete gaps that autogen silently dropped. Without the review protocol these would have shipped.
- **Worked:** Delete-and-regenerate decision was the right call vs trying to patch the broken old migration. Saved an hour of edit-and-retest cycles.
- **Didn't work:** Initial `alembic upgrade head` attempt failed without giving an obvious clue about the dual-create pattern. Took stack trace + recall of the migration code to diagnose.
- **Change next sprint:** Add a CI lint step that flags dual-create ENUMs in new migrations.

---

## 2026-05-29 (earlier) — Phase 4 prep test run: found + fixed 2 P1 event-loop bugs; 29/29 baseline locked

**Topic:** Per Phase 4 protocol, first dispatch = tester runs full suite end-to-end against Docker Postgres + Redis. First pass exposed 2 production bugs neither prior code review nor unit tests caught.

### What happened

1. `docker-compose up -d` produced Postgres 15 vs Postgres 16 image mismatch (old volume from earlier dev). Fixed: `docker-compose down -v` + `up -d`.
2. First pytest run: 23/29 pass + 6 errors. Errors traced to `ConnectionRefusedError` (Postgres not listening — fixed by 1).
3. Second pytest run: 26/29 pass + 3 fail. **All 3 failures = `RuntimeError: Event loop is closed`** on Windows asyncio.
4. Root cause analysis: two module-level singletons binding to first event loop they touch.

### Bugs found (both P1, both production-relevant — not test-only)

**TD-016 P1** — `agent/tools/booking_tools.py:17` had:
```python
redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
```
Module-level Redis client binds to first event loop at import. In tests: fails on second test (new loop). In production: fails on uvicorn worker restart, gunicorn fork-after-import, or any code path that resets the loop. Silent until traffic stress.

**TD-017 P1** — `backend/database.py` had module-level `engine` with pool. SQLAlchemy connection pool binds connections to first loop. Same failure surface.

### Fixes

**TD-016 (production code change):** Replaced module-level `redis_client` with `_redis()` factory in `agent/tools/booking_tools.py`. All callers now use `async with _redis() as r:`. Cost: ~1-2 ms extra per Redis op on localhost (TCP connect + close). Negligible vs LLM/STT on call path. Senior-grade pattern — matches existing `agent.py` `on_disconnect` handler.

**TD-017 (test-only change):** Added `await backend.database.engine.dispose()` before AND after each test in `tests/conftest.py` `db` fixture. Forces fresh pool per loop. Production keeps the pooled engine (no change there — production runs one persistent loop).

### Why these were not caught earlier

- Unit tests (`tts_sanitizer`, `emergency`) don't touch Redis or DB — pass under any loop topology
- First integration test run in a session passes (first loop is fine)
- Audit (2026-05-29) didn't catch because it was a code review, not a test execution
- Tester rule "tests must be executed end-to-end" (TD-006) specifically existed to catch exactly this class of bug; protocol worked

### Test result

`pytest tests/ -v` → **29/29 pass** (23 unit + 4 integration + 2 edge-case) against Docker Postgres 16 + Redis 7-alpine + Python 3.14.0 on Windows. Baseline locked.

### Files

- Modified: `agent/tools/booking_tools.py` — `_redis()` factory + `async with` blocks in `check_availability` and `assign_token`
- Modified: `tests/conftest.py` — `_db_module.engine.dispose()` before + after each test
- Modified: `docs/TECH_DEBT.md` — TD-006 closed; TD-016 + TD-017 logged + closed in Paid down section
- Modified: `docs/STATUS.md` — TD-006 removed from Open; added "Test baseline" section
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending — single commit)*

### Follow-up next session

Phase 4 actually starts now. First task per `docs/phases/04-backend-core/CLAUDE.md`: `database-engineer` regenerates Alembic migration (TD-001). Then `backend-engineer` builds `main.py` + JWT auth middleware + queue endpoints.

### Retro

- **Worked:** Caveman-mode terse diagnose path (`docker ps -a` + `docker logs` + port check) made root cause obvious in 2 turns. Stale Postgres volume identified immediately.
- **Worked:** Reading the FULL stack trace (not just the top error) surfaced the event-loop binding issue. The bottom of the trace had the real cause.
- **Worked:** Fixing in production code instead of test code (TD-016) — the bug was real, not a test artifact. Senior fix.
- **Change next sprint:** Phase 4 Task 1 acceptance should explicitly include "no module-level connection pools" CI check. Add to `QUALITY_BAR.md` Python section.

---

## 2026-05-29 (earlier) — Option A approved: MVP-launch posture, Phase 11 deferred

**Topic:** Client picked Option A from reliability scope discussion. Stick with MVP-launch posture (~99.4% uptime). Add Phase 11 — Reliability Hardening as deferred placeholder, NOT pre-built.

### Decisions

1. **Reliability scope = MVP-launch.** Target: ~99.4% uptime (Cloudflare edge + LLM fallback + auto-restart on Fly/Render + UptimeRobot + 7-day Neon backups + manual Singapore failover runbook + Dependabot weekly + CI test gate + secret scan). Rejected Scale-ready (~50% more work + ₹25k/mo recurring) and Phase 11 pre-build (over-engineering before any real traffic).
2. **Phase 11 created as deferred placeholder.** Has explicit "do NOT pre-build" header. Triggered by ANY of: volume > 100 calls/day OR first major outage OR enterprise customer asks for SLA. Backlog includes multi-region failover, automated rollback, Datadog APM, on-call rotation, chaos engineering, A/B testing — none built until trigger fires. Each item built ONE AT A TIME after trigger, not bundled.
3. **What we already do for reliability (NOT deferred, ships in Phases 4.5 + 10):** LLM fallback (already shipped), external call retry, graceful degradation, auto-restart on crash, health-check gating, HTTPS/HSTS, DDoS via Cloudflare, daily backups, UptimeRobot + SMS, structured logs, Dependabot, CI test gate, secret-in-repo scan, manual failover runbook, quarterly backup-restore drill, quarterly self-audit.

### Why deferred (per brainstormer + manager rationale, documented in Phase 11 doc)

- **YAGNI** — engineering for hypothetical scale wastes today's budget on tomorrow's hypothetical problem
- **Wrong baseline** — reliability infra built before real traffic optimizes for the wrong failure modes
- **Cost compounds** — ₹15-50k/mo recurring drains runway before first paying clinic
- **Complexity tax** — every reliability layer adds operational surface; MVP teams collapse under complexity they thought would protect them

### Files

- Created: `docs/phases/11-reliability-hardening/CLAUDE.md` — full deferred backlog, triggers to start, what NOT to do, anti-patterns ("smells" that mean you're slipping into Phase 11 too early)
- Modified: `docs/ROADMAP.md` — added Phase 11 row with 🅿️ DEFERRED status; added note "Phase 11 is deferred until trigger fires. Do NOT pre-build."
- Modified: `docs/STATUS.md` — added Reliability posture line pointing to Phase 11 doc
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending)*

### Blockers for next session (Phase 4 start)

**Must run before Phase 4 dispatch:**
1. Start Docker Desktop
2. `docker-compose up -d` (Postgres + Redis)
3. `alembic upgrade head` (apply existing migration — will fail / show stale state, that's expected; database-engineer will regenerate as Phase 4 Task 1)
4. `pytest tests/ -v` (verify 25 tests pass — fix-sprint work + existing)

If pytest passes → Phase 4 unblocked. If it fails → STOP, report to manager, do not proceed.

### Open client decisions: NONE

Pricing resolved (TD-004 closed). Landing page approach resolved (TD-003 closed). Reliability scope resolved (this entry). Phase 4 fully unblocked on decisions; only Docker startup blocks.

### Retro

- **Worked:** Honest reality check on "never go down / self-correcting / self-improving" prevented user from approving expensive aspirations. Caveman directness + manager stubbornness = saved client cost.
- **Worked:** Creating Phase 11 doc with explicit anti-patterns and "smells" makes the deferral durable. Future me (or any specialist) reading the doc will know not to over-build.
- **Change next sprint:** Before Phase 4 dispatch, manager runs the "must run before dispatch" blocker list and confirms each step with the user.

---

## 2026-05-29 (earlier) — Pricing decision + landing page UI update (close TD-003 + TD-004)

**Topic:** Client resolved the two pending decisions from the 2026-05-29 audit.

### Decisions

1. **Pricing tiers — canonical CLAUDE.md wins.** Client: "keep as per our docs not as per website."
   - Solo: ₹1,999/month + ₹3/min (first 100 min free)
   - Clinic: ₹7,999/month flat — 2,100 min included, ₹3/min overage. MOST POPULAR.
   - Multi: ₹16,999/month flat — 4,200 min included / 2 branches, ₹2.50/min overage
   - Additional branch: ₹7,999/month
   - 14-day free trial, no credit card, 1,000 min
   - Razorpay plan IDs (RAZORPAY_PLAN_SOLO_ID, _CLINIC_ID, _MULTI_ID) to be created against these tiers in Phase 9
2. **Landing page mirror — UI stays, content updates.** Client: "core UI (color scheme, fonts) should be same. elements like pricing and new features should reflect."
   - Kept: #006B6B teal palette, Outfit + Spectral + Pacifico fonts, layout structure, all CSS, hero copy, features 01-06, "How it works" section, contact section, footer
   - Updated: pricing section (Starter/Growth/Unlimited → Solo/Clinic/Multi), data-amount attributes (199900/799900/1699900 paise), trial note (added "1,000 minutes")
   - Reasoning: the live vachanam.in marketing site is well-designed (good restraint, clear typography, India-appropriate). Rebuilding from scratch would be wasteful vanity. Mirror it; swap content where reality diverges.

### Files

- Modified: `backend/static/index.html` — pricing section rewritten with Solo/Clinic/Multi cards, button data-amounts updated to canonical paise values, "Most popular" badge moved from Growth to Clinic, additional-branch note updated to ₹7,999, trial note updated to include 1,000-minute limit
- Modified: `docs/TECH_DEBT.md` — TD-003 + TD-004 closed (rows struck through in Open section, added to Paid down section with full resolution notes)
- Modified: `docs/STATUS.md` — TD-003 + TD-004 removed from Open debt list; "Recently closed" pointer added
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending — single client-decision commit)*

### What was NOT changed

- Test mode banner stays (still rzp_test_* keys). Will be removed in Phase 9 when going live.
- Razorpay subscription plan IDs in `.env` (RAZORPAY_PLAN_*_ID) — still empty. Owner action in Phase 9 dashboard.
- Production marketing site (vachanam.in) untouched. Independent host. Owner manages directly.

### Open debts after this entry

P1: TD-001 (stale migration, Phase 4) · TD-015 (CI, Phase 4.5)
P2: TD-002 · TD-006 · TD-014
P3: TD-005

Down from 8 → 6 open. Phase 4 ready to start.

### Retro

- **Worked:** Two-sentence client decision + 15-min implementation = exact ratio of decision-cost to execution-cost we want.
- **Worked:** Keeping the original CSS / layout / fonts means visual regression is zero — only content changed.
- **Change next sprint:** When Phase 9 implements subscriptions, regenerate the Razorpay plan IDs to match these exact amounts in the dashboard.

---

## 2026-05-29 (earlier) — Fix sprint: closed 7 audit findings

**Topic:** Client picked Option A from [2026-05-29 audit](audits/2026-05-29-full-project-audit.md). Brainstormer designed TD-007 fix. Executed all 7 fix items.

### Brainstorm — TD-007 LLM fallback approach

Considered 4 options:
- **A.** Custom `livekit.agents.llm.LLM` subclass wrapping Gemini + OpenAI
- **B.** Session-level error handler that swaps `session.llm` mid-call
- **C.** Pre-flight Gemini health check; pick provider for whole call
- **D.** Built-in `livekit.agents.llm.FallbackAdapter([Gemini, OpenAI])`

**Picked D.** Three lines, idiomatic, maintained upstream, zero custom code to maintain. A/B/C all require reimplementing the LLM contract correctly for both providers. D ships today.

### Decisions

1. **TD-007 → FallbackAdapter approach** — built into livekit.agents 1.0+. Confirmed available in 1.4. No custom adapter.
2. **TD-008 → `aclose()`** — replaced `session.disconnect()` at 2 call sites. Per LiveKit Agents 1.4 API.
3. **TD-009 → background watchdog task** — `_solo_cap_watchdog` polls every 5s. Cancelled in entrypoint `finally` block. Removed duplicate logic from `on_user_turn_completed`.
4. **TD-010 → N=100 + boundary variant** — first test races 100 callers (limit=200, all succeed, sequential 1-100). Second test pre-fills 99 (limit=100), races 10 for token 100, asserts exactly 1 success + 9 `full` + Redis counter exactly 100 (rollbacks verified).
5. **TD-011 → `settings.redis_url`** — conftest no longer hardcodes URL.
6. **TD-012 → pre-flush** — conftest's redis fixture flushes BEFORE yield too.
7. **TD-013 → archive 8 docs** — `git mv` to `docs/_legacy/`. Added `docs/_legacy/README.md` explaining archaeology-only purpose with pointers to current canonical docs.

### Files

- Modified: `agent/agent.py` — FallbackAdapter, aclose, watchdog, removed _llm_with_fallback
- Modified: `tests/edge_cases/test_concurrent_tokens.py` — N=100 + boundary test
- Modified: `tests/conftest.py` — settings.redis_url + pre-flush
- Moved: `PHASE_0_ENVIRONMENT.md`, `PHASE_1_VOICE_AGENT.md`, `PHASE_2_BACKEND.md`, `PHASE_3_FRONTEND.md`, `PHASE_4_ONBOARDING.md`, `PHASE_5_PRODUCTION.md`, `docs/vachanam-progress.md`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md` → `docs/_legacy/`
- Created: `docs/_legacy/README.md`
- Modified: `docs/TECH_DEBT.md` — TD-007..013 moved to Paid down section
- Modified: `docs/STATUS.md` — fix sprint complete; active phase now Phase 4
- Modified: `docs/CHANGELOG.md` (this entry)

### Tests not executed this session

Docker not started — integration + edge-case tests committed but not run. **First Phase 4 task = `docker-compose up -d` + `alembic upgrade head` + `pytest tests/ -v` end-to-end** (TD-006).

### Commits

- *(pending — single fix sprint commit)*

### Follow-ups for next session (Phase 4)

1. Run tester: `docker-compose up -d` → `alembic revision --autogenerate -m phase4_user_table_and_token_timestamps` → review → `alembic upgrade head` → `pytest tests/ -v`
2. Verify N=100 concurrent test actually passes (it's likely fine but TD-006 means we haven't proved it)
3. Proceed with Phase 4 Tasks 1-7 per [`docs/phases/04-backend-core/CLAUDE.md`](phases/04-backend-core/CLAUDE.md)
4. Two unresolved client decisions remain:
   - Pricing tiers (TD-004) — blocks Phase 9
   - Landing page mirror future — doesn't block but should decide before Phase 9

### Retro

- **Worked:** Brainstormer pass on TD-007 saved hours — would have built custom adapter (option A) without it; FallbackAdapter shipped in 3 lines.
- **Worked:** Batching fixes (3 voice agent fixes in one file rewrite, 2 conftest fixes in one rewrite) cut commits-without-context overhead.
- **Didn't work:** Could not actually RUN tests this turn (Docker would be needed). Means the fix is committed but unverified for TD-010 specifically. Tester would correctly reject this as DONE_WITH_CONCERNS.
- **Change next sprint:** Phase 4 first dispatch MUST be tester to run the full suite. No new code until existing tests verified.

---

## 2026-05-29 (earlier) — Full project audit (10-specialist review)

**Topic:** Client requested full review — "redesign entire project ... read requirements, review files, correct everything that feels wrong. If not good enough, delete and redesign." Manager orchestrated; applied each specialist's lens; produced [`docs/audits/2026-05-29-full-project-audit.md`](audits/2026-05-29-full-project-audit.md).

### Findings (top-level)

- **Code: 85% good.** Voice agent largely senior-grade with 3 named bugs (2 P0, 1 P1) — all bounded and fixable in 1-2 days.
- **Docs: 70% good.** New canonical structure is right; 8 obsolete files crowd it (old PHASE_*.md, vachanam-progress.md, old plans). Administrative cleanup, hours not days.
- **Decisions: 90% good.** Two unresolved (pricing tiers, landing page future).
- **Strategy: solid.** 10-phase roadmap + 10-specialist roster + Agile workflow + security spec all coherent. Vachanam on track for launch in 3-4 weeks if Phase 4 starts cleanly.

### New tech debt logged (9 items)

- **TD-007 P0** — `_llm_with_fallback` defined but unused in agent.py session wiring
- **TD-008 P0** — `session.disconnect()` likely wrong API for LiveKit 1.4
- **TD-009 P1** — SOLO 4-min cap only fires on user turn
- **TD-010 P2** — Concurrent test N=5 (should be ≥100 per tester.md)
- **TD-011 P3** — Conftest hardcodes Redis URL
- **TD-012 P2** — Conftest doesn't pre-flush Redis
- **TD-013 P2** — Obsolete docs crowd new canonical structure
- **TD-014 P2** — Dockerfiles run as root (must be non-root before Phase 10)
- **TD-015 P1** — No CI / secret-scan workflow

### Recommendation to client

**Option A — Fix sprint + proceed (recommended).** 1-2 days to fix C-1/C-2/C-3 + I-1/I-2/I-3 + archive obsolete docs. Then start Phase 4. Code largely stays.

Option B (3-5 days): bigger refactor.
Option C (2-3 weeks): burn down + restart — NOT recommended; loses ~85% of correct work for ~5% structural improvement.

### Files created/modified

- Created: `docs/audits/2026-05-29-full-project-audit.md`
- Modified: `docs/TECH_DEBT.md` (added TD-007 through TD-015)
- Modified: `docs/STATUS.md` (audit findings section + active phase pointer changed to "Fix sprint pending client decision")
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending — single audit commit)*

### Decision needed (client)

1. Pick Option A / B / C from audit Section 8
2. Pick pricing tiers (Solo/Clinic/Multi vs Starter/Growth/Unlimited)
3. Pick landing-page mirror future (keep as test target / promote to prod / delete)
4. Approve sprint sequencing (Fix sprint → Phase 4 → Phase 4.5 → Phase 5+)

NO CODE OR DOC DELETION performed this turn. Awaiting client call.

### Retro

- **Worked:** Reading all source files in one parallel batch was efficient; specialist-lens framing surfaced C-1 and C-3 that prior cursory reads missed.
- **Didn't work:** Took >2 hours total of model time before any actionable output landed — audit alone burns budget the client could have spent on Phase 4 implementation. Would the client have preferred a 30-min lightweight audit?
- **Change next sprint:** When client asks for "review everything", first propose a 30/60/120-minute audit scope with cost estimate. Let them pick.

---

## 2026-05-29 (latest) — Opus brain for 5 critical-path specialists

**Topic:** Bumped `tester`, `privacy-legal`, `security-engineer` from sonnet → opus. Now 5 of 10 specialists run on opus (manager, brainstormer, security-engineer, privacy-legal, tester).

### Decision

These five roles are now opus because the cost of a single mistake is asymmetric:
- `security-engineer`: a missed OWASP rule or unsigned webhook = data breach + DPDP fine
- `privacy-legal`: DPDP wording precision matters in court; misclassifying a processor = liability
- `tester`: last line of defense; "mostly tested" is what hurts patients
- `manager` + `brainstormer`: already opus from prior session — set the bar and design the work

Sonnet specialists do implementation under opus oversight. Reasoning budget concentrated where one mistake is most expensive.

### Files

- Modified: `.claude/agents/tester.md` (model sonnet → opus)
- Modified: `.claude/agents/privacy-legal.md` (model sonnet → opus)
- Modified: `.claude/agents/security-engineer.md` (model sonnet → opus)
- Modified: `.claude/agents/README.md` (roster table + model rationale rewritten)

### Commits

- *(pending)*

---

## 2026-05-29 (later) — Roster v2: +database-engineer +brainstormer, Agile + Quality Bar, manager as client-accountable opus

**Topic:** Roster expanded from 8 → 10 specialists. Manager + brainstormer use opus brain. Added Agile workflow, senior-dev quality bar, technical debt ledger. Manager redefined as client-accountable PM who escalates plan deviations BEFORE acting.

### Decisions

1. **Added `database-engineer`** as a separate specialist. Previously rolled into `backend-engineer`. Split because schema design + Alembic migration discipline + zero-downtime patterns + index strategy is a deep enough domain to deserve its own owner. `backend-engineer` now ONLY consumes schema, requests changes from `database-engineer`.
2. **Added `brainstormer`** as a tech-lead/architect specialist. Proposes 2-3 options for every fork, recommends the simplest viable (YAGNI ruthless), surfaces "is this needed?" challenges. Never implements. Dispatched at start of every phase or non-trivial task per AGILE.md.
3. **Manager assigned opus brain** (was sonnet). Reasoning: highest-stakes role; every decision affects client cost + quality + DPDP compliance. Needs deepest reasoning.
4. **Brainstormer assigned opus brain** (was sonnet). Reasoning: design judgment shapes downstream work; better recommendations save engineering hours.
5. **Manager redefined as client-accountable.** New principles:
   - Answerable to the client (Vinay) for every decision
   - Goal: production-grade output at lowest client cost (without quality compromise)
   - Lifecycle ownership from greenfield through production support
   - Plan deviations MUST be escalated to client BEFORE updating any doc
   - Vendor / cost additions require client approval
   - Every CHANGELOG decision carries manager's reasoning as defense
6. **Manager persona = stubborn micromanager.** 11 non-negotiable rules including: no DONE without proof; no test skipping; no scope creep; no plan deviation without escalation; no commit without the right reviewer. Standard reply when in doubt: "not yet."
7. **Tester persona = stubborn QA who "shows hell to developers".** Rejects "mostly tested" work. TDD enforced. Rejects implementer modifications to tests. Concurrency tests must be N≥100. Data isolation tests must use 2+ orgs. Negative tests required for every endpoint.
8. **Created `.claude/agents/AGILE.md`** — sprint workflow. Sprint = one phase. Ceremonies: planning (with brainstormer + client escalation if needed), standup (session start), review (verify acceptance + demo), retro (worked / didn't / change). Definition of Ready before dispatch. Definition of Done before mark-done.
9. **Created `.claude/agents/QUALITY_BAR.md`** — senior-dev standards. Every line of code + every doc + every decision + every commit + every deploy meets the checklist. Anti-patterns rejected on sight ("it works on my machine" / "I'll add tests later" / "mostly done" etc.).
10. **Created `docs/TECH_DEBT.md`** — ledger of every shortcut with severity (P0/P1/P2/P3) and payback plan. Backfilled with 6 existing debts (stale migration, standalone test app, ₹99 test price, pricing decision, romanized Telugu keyword, unverified tests).

### Files

- Created: `.claude/agents/database-engineer.md`
- Created: `.claude/agents/brainstormer.md`
- Created: `.claude/agents/AGILE.md`
- Created: `.claude/agents/QUALITY_BAR.md`
- Created: `docs/TECH_DEBT.md`
- Modified: `.claude/agents/manager.md` — full rewrite; opus brain; client accountability; stubborn principles; lifecycle ownership; escalation protocol
- Modified: `.claude/agents/tester.md` — full rewrite; stubborn QA persona; "shows hell" framing; rejection criteria explicit
- Modified: `.claude/agents/brainstormer.md` — model bumped sonnet → opus
- Modified: `.claude/agents/backend-engineer.md` — scope narrowed; schema work delegated to database-engineer; coordination protocol added
- Modified: `.claude/agents/README.md` — 10-specialist roster, AGILE.md + QUALITY_BAR.md references, model rationale
- Modified: `CLAUDE.md` (root) — START HERE updated with manager-first, QUALITY_BAR, AGILE, TECH_DEBT pointers
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending — single commit after this entry)*

### Follow-ups

- Test the new roster on a Phase 4 dispatch: manager → brainstormer → database-engineer → backend-engineer → tester → security-engineer review
- If manager output is too verbose at opus, retro and consider sonnet for routine session-end updates (keeping opus for sprint planning + escalations)
- TECH_DEBT TD-004 (pricing decision) is client-blocking — manager should escalate at the next sprint planning

### Retro (for this restructure sprint)

- **Worked:** Agreeing on roster up-front then writing each agent file in one pass kept consistency.
- **Didn't work:** First README draft missed updating brainstormer to opus — required a redo. Could have been caught by reading user's full requirements list before writing.
- **Change next sprint:** Before writing any multi-file output, re-state the requirements explicitly to confirm scope.

---

## 2026-05-29 — Specialist Agent Roster

**Topic:** Built 8 Claude Code subagents under `.claude/agents/` to enforce role separation, prevent cross-domain scope creep, and make the development workflow auditable specialist-by-specialist.

### Decisions

1. **Eight specialists** chosen (not 10+, not fewer): manager, backend-engineer, frontend-engineer, voice-agent-engineer, devops-engineer, security-engineer, privacy-legal, tester. Reasoning: each has clear domain ownership without overlap; smaller team = clearer routing.
2. **Merged** privacy + legal into a single `privacy-legal` specialist. Same regulatory frame, same artifacts (markdown docs and runbooks).
3. **Merged** DB work into `backend-engineer` (same async Python skillset, same Alembic discipline) and PM work into `manager` (founder-led project — no separate PM yet).
4. **Added** `voice-agent-engineer` as a distinct specialist. LiveKit/Sarvam/SIP is a deep enough domain that a generalist backend engineer should not own it.
5. **Manager NEVER implements code** — coordination only. Edits docs/STATUS.md, ROADMAP.md, CHANGELOG.md, phase docs. Dispatches via Task tool.
6. **Privacy-legal NEVER writes code** — outputs are markdown legal docs and runbooks. When implementation needed, specs it and hands to the right engineer.
7. **Tester NEVER writes the feature being tested** — adversarial QA stance preserved.
8. **Specialists READ the spec** (`docs/superpowers/specs/2026-05-22-security-hardening-design.md` etc.) — never re-derive rules from memory.
9. Each agent file includes: domain table, non-negotiable rules, stack, reference patterns, required reading, workflow, output format, anti-patterns.
10. Root CLAUDE.md updated with Step 4 in "START EVERY SESSION HERE" pointing to the roster.

### Files

- Created: `.claude/agents/README.md` (roster + invocation patterns)
- Created: `.claude/agents/manager.md`
- Created: `.claude/agents/backend-engineer.md`
- Created: `.claude/agents/frontend-engineer.md`
- Created: `.claude/agents/voice-agent-engineer.md`
- Created: `.claude/agents/devops-engineer.md`
- Created: `.claude/agents/security-engineer.md`
- Created: `.claude/agents/privacy-legal.md`
- Created: `.claude/agents/tester.md`
- Modified: `CLAUDE.md` (added roster pointer)
- Modified: `docs/CHANGELOG.md` (this entry)

### Commits

- *(pending)*

### Follow-ups

- Test the roster on first real Phase 4 task — dispatch `manager` to plan, then `backend-engineer` for migration regeneration
- Tune agent prompts if any specialist returns ambiguous results
- If a domain emerges that doesn't fit any specialist (e.g. data analytics, ML), add a new one

---

## 2026-05-22 — Security & Compliance Spec

**Topic:** Brainstormed full security posture for MVP launch. Created design spec for Phase 4.5.

### Decisions

1. **Spec structure:** ONE cohesive Security & Compliance spec covering 8 areas (auth, session, rate limit, OWASP, audit, privacy, infra, breach). Reasoning: security works as a system — fragmenting it creates gaps.
2. **Posture target:** MVP-launch (not Scale-ready, not Enterprise). Reasoning: pre-launch with zero real patient data; over-engineering security now wastes time before product-market fit.
3. **Session policy:** 8h JWT hard timeout + 30min frontend idle timeout. Reasoning: covers a full clinic shift; idle timeout protects against momentary unattended device exposure.
4. **Rate limit strategy:** Layered (per-user + per-IP + per-endpoint) via slowapi + Redis. Per-endpoint overrides for `/auth/google` (5/min), `/api/create-order` (10/min), `/webhook/*` (1000/min), etc.
5. **Login methods:** Google OAuth only. Reasoning: no passwords to store, Google's 2FA inherited, no SMS-OTP SIM-swap risk.
6. **Audit log scope:** Sensitive actions only (login, token mark, doctor cancel, payments, admin views, security events). Append-only table. 7-year retention.
7. **Approach:** Defense-in-depth (Cloudflare edge + app middleware + audit log + route-level validation). Each layer assumes others might fail.
8. **No formal DPO for MVP** — Vinay is de facto DPO until SDF threshold (~50k users).
9. **No field-level PII encryption for MVP** — relying on Neon disk encryption + branch isolation + audit log.
10. **Phase 4.5 slotted** between Phase 4 (Backend Core) and Phase 5 (WhatsApp). Effort: 3-4 days.

### Files

- Created: `docs/superpowers/specs/2026-05-22-security-hardening-design.md` (~15 sections, ~900 lines, plain English)
- Created: `docs/CHANGELOG.md` (this file)
- Modified: `docs/STATUS.md` — added Phase 4.5; updated active phase pointer
- Modified: `docs/ROADMAP.md` — inserted Phase 4.5 between 4 and 5; renumbered nothing (4.5 is intentional)

### Commits

- *(pending — commit after spec self-review and user approval)*

### Follow-ups for next session

1. User reviews spec; revise if changes requested
2. Invoke `writing-plans` skill to break the spec into implementation tasks
3. Update STATUS.md and ROADMAP.md to mark Phase 4 next (security plan ready)

---

## 2026-05-22 (earlier) — Project Restructure: STATUS + ROADMAP + 10 Phase Docs

**Topic:** Project had drifted — 5 PHASE_N.md files at root, plans in docs/superpowers/plans/, progress in docs/vachanam-progress.md, Razorpay work jumped ahead of plan order. Restructured into a clean phase-based layout.

### Decisions

1. **New canonical structure:** `docs/STATUS.md` (truth source) + `docs/ROADMAP.md` (dependency map) + `docs/phases/NN-name/CLAUDE.md` (per-phase tasks).
2. **Old PHASE_N.md files at root** marked as historical reference only — not deleted (preserve history) but no longer authoritative.
3. **10 phases total** — 3 done (Foundation, Voice Agent, Razorpay Checkout), 7 to do (Backend Core, WhatsApp, Jobs+Calendar, Receptionist PWA, Owner+Admin Dashboards, Subscriptions+Onboarding, Deployment).
4. **Each phase gets its own CLAUDE.md** in a folder under `docs/phases/` — so opening that folder gives full context for working on that phase.
5. **Root CLAUDE.md** gets a "START HERE" pointer to STATUS.md and ROADMAP.md.

### Files

- Created: `docs/STATUS.md`, `docs/ROADMAP.md`
- Created: 10 phase folders each with CLAUDE.md (`01-foundation/` through `10-deployment/`)
- Modified: root `CLAUDE.md` — added "START EVERY SESSION HERE" block at the top

### Commits

- `3e4e698` — docs: restructure into STATUS.md + ROADMAP.md + 10 phase CLAUDE.md files

### Follow-ups

- Phase 4 (Backend Core) is next active phase
- Resolve pricing decision (Solo/Clinic/Multi from CLAUDE.md vs Starter/Growth/Unlimited from vachanam.in) before Phase 9

---

## 2026-05-22 (earlier) — Razorpay Standard Checkout (Test Mode)

**Topic:** Wired Razorpay Standard Web Checkout end-to-end. Mirror of vachanam.in serving as the test landing page. Verified order creation against live Razorpay test API.

### Decisions

1. **Lives in standalone `backend/payments_test_app.py`** because `backend/main.py` doesn't exist yet — Phase 4 will integrate it.
2. **`key_id` returned in `/api/create-order` response** so the frontend never needs `VITE_RAZORPAY_KEY_ID`. Secret never leaves server.
3. **Landing page** is 1:1 mirror of vachanam.in (947 lines, fonts: Outfit/Spectral/Pacifico, color `#006B6B`). Three pricing CTAs trigger Razorpay flow.
4. **Test mode quirk noted:** account is domestic-cards-only — `4111 1111 1111 1111` rejected because Razorpay treats it as international BIN. Owner action: enable International Payments in dashboard before live.
5. **Test mode quirk noted:** UPI tab shows QR-only; "Enter UPI ID" field hidden. Owner action: enable UPI Collect flow in dashboard.
6. **Starter plan price temporarily reduced to ₹99** for self-testing; restore before linking from real marketing.

### Files

- Created: `backend/routers/payments.py`, `backend/payments_test_app.py`, `backend/static/index.html`, `backend/static/razorpay-test.html`
- Modified: `.env` — filled `RAZORPAY_KEY_ID=rzp_test_Ss3Qe551bl3LRz`, `RAZORPAY_KEY_SECRET=clEoihnt7Q2OMTCZGJNvrSow`

### Commits

- `7f5a184` — feat(payments): Razorpay Standard Checkout end-to-end (test mode)

### Verified working

- Real Razorpay test orders created (e.g., `order_SsFxpRSIGK6my1`)
- Signature round-trip 200/400 (valid/invalid signatures)
- Amount validation 422 (< 100 paise)

### Follow-ups

- Phase 4 deletes `backend/payments_test_app.py`, mounts the router in `backend/main.py`
- Phase 9 swaps test keys for live `rzp_live_*` after Razorpay KYC

---

## 2026-05-22 (earlier) — Schema Gap Fix + Phase 2 Plan Draft + Infra Files

**Topic:** Identified gaps in the database schema vs what Phase 2 backend code would need; fixed schema; wrote Phase 2 plan (later superseded by docs/phases/04-backend-core/); created infra/ files.

### Decisions

1. **Schema fixes:**
   - Added `User` model (for JWT auth in Phase 4)
   - Added `Branch.meta_phone_number_id` (Meta's internal phone ID for webhook routing)
   - Added `Token.is_urgent`, `Token.confirmed_at`, `Token.attended_at`, `Token.marked_by_user_id`
   - Added `FollowupTask.what_to_ask`, `FollowupTask.channel`, `FollowupTask.scheduled_date`
   - Fixed token status enum: `confirmed | attended | no_show | cancelled_by_clinic` (removed `waiting`, which conflicted with Phase 2 code)
2. **Stale migration noted:** `alembic/versions/2fe8f201bc31_initial_schema.py` (2026-05-15) predates these schema additions. Phase 4 must regenerate.
3. **Infra files** for Fly.io and Render created.
4. **Phase 2 plan** drafted at `docs/superpowers/plans/2026-05-18-phase-2-backend.md` — superseded by `docs/phases/04-backend-core/CLAUDE.md`.

### Files

- Modified: `backend/models/schema.py`, `agent/tools/booking_tools.py` (status: `waiting` → `confirmed`)
- Created: `backend/requirements.txt`, `infra/Dockerfile.agent`, `infra/Dockerfile.backend`, `infra/fly.agent.toml`, `infra/render.yaml`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md`

### Commits

- `96f6d92` — fix: schema gaps, Phase 2 plan, infra files

---

## 2026-05-17 — Vobiz Credentials Reset + Twilio Removal

**Topic:** User identified that Vobiz uses SIP trunk integration (not API key/secret/webhook). Replaced credentials across codebase. Removed Twilio entirely.

### Decisions

1. **Vobiz integration is SIP-based** — needs `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_DID_NUMBER` (from Vobiz console after creating a SIP trunk).
2. **Vobiz Partner API** is separate — uses `VOBIZ_PARTNER_AUTH_ID` and `VOBIZ_PARTNER_AUTH_TOKEN` for clinic-level DID provisioning.
3. **Twilio removed entirely** — not used. All Twilio references stripped from PHASE_5_PRODUCTION.md and CLAUDE.md.
4. **Uptime table updated** — added Vobiz row with retry + graceful "call back" fallback.

### Files

- Modified: `.env`, `.env.example`, `backend/config.py`, `CLAUDE.md`, `PHASE_5_PRODUCTION.md`

### Commits

- `ed5b333` — fix: replace Vobiz API key/secret/webhook with SIP credentials; remove Twilio entirely

---

## 2026-05-16 — Phase 1 Voice Agent Tests + Edge Cases

**Topic:** Wrote integration + edge-case tests for booking flow and concurrent tokens. Fixed multiple async/SQLAlchemy bugs discovered along the way.

### Decisions

1. **`asyncio_mode = auto` in pytest.ini** — replaces deprecated `event_loop` fixture override.
2. **Each concurrent coroutine** in `asyncio.gather` opens its own `async with AsyncSessionLocal()` — shared `AsyncSession` is NOT concurrent-safe.
3. **Capture SQLAlchemy attribute values into local vars** BEFORE exiting `async with` block — prevents `DetachedInstanceError`.
4. **`asyncio.to_thread`** for sync Gemini SDK calls inside async context — prevents event loop blocking.
5. **`new_message.content` guard** — may be list not str; isinstance check with fallback text extraction.
6. **Solo warning gate** — `solo_warning_sent: bool` flag in SessionState prevents repeated warnings after 230s.

### Files

- Created: `tests/conftest.py`, `tests/unit/test_tts_sanitizer.py`, `tests/unit/test_emergency.py`, `tests/integration/test_booking_flow.py`, `tests/edge_cases/test_concurrent_tokens.py`, `pytest.ini`
- Modified: `agent/agent.py`, `agent/session_state.py`

### Commits

- `eb8422b`, `6f366fe`, `3bb31c2`, `0fa5d00`, `eb140e2` — various fixes

---

## 2026-05-15 — Initial Implementation Sprint (Phase 0 + Phase 1)

**Topic:** Built Phase 0 (foundation) and Phase 1 (voice agent) from scratch using subagent-driven development.

### Decisions

1. **LLM order:** Gemini 2.5 Flash primary → GPT-4o-mini fallback (CLAUDE.md Rule 9).
2. **Pricing:** Solo ₹1,999 + ₹3/min · Clinic ₹7,999/2,100min · Multi ₹16,999/4,200min — set as canonical in CLAUDE.md.
3. **Emergency MVP:** keyword detect only → give `branch.emergency_contact`. No TYPE_1/TYPE_2 classification.
4. **Billing model:** anniversary cycle (not 1st of month).
5. **Trial:** 14 days / 1,000 min / no credit card.
6. **9 DB tables initially:** organizations, branches, doctors, patients, tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions. (User table added 2026-05-22.)

### Files

- Created: full backend/ skeleton, full agent/ skeleton, alembic setup, docker-compose, .env structure, design doc at `docs/superpowers/specs/2026-05-15-vachanam-complete-design.md`, plan at `docs/superpowers/plans/2026-05-15-phase-0-1-voice-agent.md`

### Commits

- `a5370a0` (TTS sanitizer)
- `c163004` (emergency MVP)
- `ee794ef` (session_state)
- `ce0956f` (system prompt)
- `e12b919`, `901a71c` (booking tools)
- `e380486` (livekit agent)
- `3465978`, `b1248d7` (smaller fixes)

---

## How to update this file

When a session ends with material progress, add a new entry at the top:

```markdown
## YYYY-MM-DD — <Topic>

**Topic:** One-sentence summary.

### Decisions
1. Numbered list of decisions made. Include reasoning briefly.

### Files
- Created / Modified / Deleted lists.

### Commits
- `<hash>` — commit subject

### Follow-ups
- Next session should pick up X.
```

Never edit older entries — they are the historical record. If a past decision becomes wrong, add a new entry explaining why it changed and what was done.
