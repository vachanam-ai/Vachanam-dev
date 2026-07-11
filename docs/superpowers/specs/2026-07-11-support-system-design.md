# Vachanam Support System — Design Spec

**Date:** 2026-07-11
**Author:** Claude (with Vinay)
**Status:** Draft for review
**Branch:** master (clinic product feature). Migrations deploy-gated as usual.

## Goal

Give every Vachanam audience a path to help: an AI FAQ chatbot, self-serve
help center, and a full ticket/live-chat/CSAT/SLA support suite with an admin
inbox where Vinay answers. Built lean (reuse existing Gemini + Resend +
APScheduler; no new vendors), phased value-first, with the heavy machinery
dormant until real clinics exist to staff it.

## Audiences (and what each actually needs)

1. **Patients (callers)** — their support *is* the voice agent + the clinic's
   own emergency contact (RULE 7). **Nothing new is built for patients.**
   Explicitly out of scope; documented so it isn't re-litigated.
2. **Prospective clinics (public, pre-auth)** — FAQ, a sales chatbot, and a
   "contact / book a demo" form on the marketing site.
3. **Clinic owners & staff (in-app, authed)** — the real suite: help center,
   AI assistant, tickets, live chat, CSAT, SLA/escalation, canned macros.
4. **Vinay (super_admin)** — a cross-org support inbox to triage and answer.

Two delivery surfaces — **public** and **in-app** — share one engine.

## Non-goals (YAGNI)

- No third-party support vendor (Intercom/Zendesk/Crisp) — cost + DPDP PII
  export + isolation posture. KB lives in our repo, tickets in our DB.
- No websocket/presence server. "Live chat" = ticket thread + short-poll
  (decided 2026-07-11). Upgradable to real-time later without UI change.
- No patient-facing support additions.
- No public knowledge-base authoring UI — KB is markdown in the repo, edited
  by us via git. (Admin macro snippets are the only editable text, and those
  can start as a constant list.)

## Architecture overview

```
                 ┌─────────────────────────────────────┐
 Public visitor  │  /help (FAQ search) + chat widget    │  Turnstile-gated
 (no auth)  ────▶│  /support/chat (public KB subset)    │  chat + contact form
                 │  contact/demo form → support_tickets │  (org_id NULL)
                 └─────────────────────────────────────┘
                                  │ shared engine
 Clinic user     ┌─────────────────────────────────────┐
 (JWT) ─────────▶│  Help page + AI assistant (full KB,  │
                 │  plan/status aware, product Qs only) │
                 │  My Tickets (submit/track/reply)     │
                 │  Live chat = ticket thread + poll    │
                 │  CSAT on resolve                     │
                 └─────────────────────────────────────┘
                                  │
 Vinay           ┌─────────────────────────────────────┐
 (super_admin)──▶│  Admin support inbox (cross-org):    │
                 │  triage, reply, status/priority,     │
                 │  canned macros                       │
                 └─────────────────────────────────────┘

 Cross-cutting:  Resend email notifications (RULE 8: never block a write)
                 APScheduler job: SLA-overdue → escalation email to Vinay
```

## Data model (2 new tables)

`support_tickets`
- `id` uuid pk
- `org_id` uuid nullable FK organizations — **NULL = public lead** (contact/demo
  form from a non-authenticated visitor). Non-null = clinic ticket. This is the
  single org scope; no branch_id (support is org-level, not branch data).
- `email` text — reply-to (the authed user's email, or the public form's email)
- `name` text nullable — submitter display name (public form)
- `subject` text
- `category` enum (`billing`, `technical`, `onboarding`, `feature_request`,
  `sales_demo`, `other`)
- `status` enum (`open`, `pending`, `resolved`, `closed`) default `open`
  - `open` = awaiting first staff response; `pending` = awaiting user reply;
    `resolved` = staff marked done (CSAT sent); `closed` = terminal.
- `priority` enum (`low`, `normal`, `high`, `urgent`) default `normal`
- `sla_due_at` timestamptz — set at create by priority (see SLA below)
- `first_responded_at` timestamptz nullable
- `resolved_at` timestamptz nullable
- `csat_score` smallint nullable (1–5)
- `csat_comment` text nullable
- `source` enum (`in_app`, `public_chat`, `public_form`, `email`) — provenance
- `created_at`, `updated_at`
- Indexes: `(org_id)`, `(status, sla_due_at)` for the SLA sweep, `(created_at)`.

`support_messages`
- `id` uuid pk
- `ticket_id` uuid FK support_tickets, indexed
- `sender` enum (`user`, `staff`, `bot`, `system`)
- `sender_user_id` uuid nullable
- `body` text
- `created_at` timestamptz
- Index `(ticket_id, created_at)`.

Migration is additive (two CREATE TABLEs) → deploy-gated on prod; local first.
Follow the project's provisioning note (create_all + stamp head; the base
Alembic chain is broken — see memory `alembic-chain-broken`). Author the
migration to be applied on prod, but do not apply to prod until Vinay confirms.

## Knowledge base

- Location: `docs/support/*.md`, one file per topic, each with front-matter:
  `title`, `audience` (`public` | `clinic` | `both`), `category`, `tags`.
- Loaded at startup into an in-memory list (small corpus; reload on deploy).
  `ponytail:` in-memory, add a cache-bust/DB move only if the corpus outgrows
  memory or needs runtime edits.
- Seed set (~12–15 entries): what Vachanam is, supported languages, pricing &
  plans, how a call works, adding doctors/staff, connecting a DID, Google
  Calendar setup, trial & billing, Razorpay/GST, PWA install, "call failed"
  triage, data/DPDP, refunds (link existing /refunds), contact.
- Public `/support/kb` returns the `public`+`both` subset (for the /help page
  search). In-app returns `clinic`+`both`.

## Chatbot (`/support/chat`)

- Engine: reuse the backend Gemini client pattern from
  `backend/jobs/call_scoring.py` — `from google import genai`,
  `genai.Client(api_key=settings.gemini_api_key)`,
  `client.aio.models.generate_content(model="gemini-2.5-flash-lite",
  config=ThinkingConfig(thinking_budget=0))`. GPT-4o-mini fallback mirrors the
  agent's fallback policy (LLM failure → fallback, RULE 8). Per memory
  `feedback-no-auto-prompt-tuning`: this is a fixed system prompt, no
  judge/sim rewrite loop.
- Grounding: system prompt = "You are Vachanam's support assistant. Answer ONLY
  from the KNOWLEDGE BASE below. If the answer isn't there, say you're not sure
  and offer to open a ticket / email hello@vachanam.in. Never invent pricing,
  features, or medical advice." + the relevant KB subset for the caller's
  audience. Keep answers short (phone-support tone), plain text (no markdown
  symbols that render badly).
- **RULE 1:** the bot answers *product* questions only. It has NO tool access
  and NO DB read of clinic data — it cannot "show my patients / my tokens".
  The in-app variant may be told the caller's plan + org status (from the JWT)
  so it can answer "what's included in my plan", but nothing patient-level.
- Endpoints:
  - `POST /support/chat` (public) — Turnstile-gated (reuse `require_turnstile`),
    rate-limited (reuse `default_limit`), body `{question, history?}`.
  - `POST /support/chat` authed variant — same handler, JWT branch: uses full
    KB + plan/status context. (One route, auth-optional; behaviour forks on
    whether a valid JWT is present.)
- "Escalate" affordance: the chat UI offers "Still stuck? Create a ticket",
  which prefills a ticket with the transcript as the first `bot`/`user`
  messages.
- Cost guard: cap history length + max output tokens; the KB is small so
  context stays cheap (~gemini-flash-lite, thinking off).

## Ticketing

- `POST /support/tickets` — authed (org ticket) or public (Turnstile, org_id
  NULL). Creates ticket + first `support_message`. Sets `sla_due_at`.
- `GET /support/tickets` — authed: caller's org tickets only (RULE 1: `WHERE
  org_id = current_user.org_id`). super_admin path is the admin inbox (below).
- `GET /support/tickets/{id}` + `GET /support/tickets/{id}/messages` —
  org-scoped; 404 if not caller's org (mirror the IDOR wall pattern).
- `POST /support/tickets/{id}/messages` — add a reply (user or staff). A user
  reply flips status `pending`→`open`; a staff reply flips `open`→`pending` and
  stamps `first_responded_at` on the first one.
- `PATCH /support/tickets/{id}` — status/priority (staff only for status beyond
  the user's own close; user may close their own ticket).
- Email (RULE 8, best-effort, never blocks the write): ticket created → notify
  `hello@vachanam.in` + ack the submitter; staff reply → email the user; resolve
  → email with CSAT link. Reuse the Resend POST pattern from
  `backend/jobs/trial_pause.py`.

## Live chat (= ticket thread + poll)

- No new backend. A ticket of category `technical`/`other` opened from the
  in-app chat widget IS the chat. The widget polls
  `GET /support/tickets/{id}/messages` every ~4 s (TanStack Query
  `refetchInterval`) while open. Staff reply from the admin inbox shows up on
  the next poll → feels live when Vinay is online; degrades to a normal ticket
  when he's not.
- A lightweight "typing/online" nicety is out of scope (needs presence).

## CSAT, SLA, escalation

- **CSAT:** on `status→resolved`, email + in-app prompt with a 1–5 rating that
  writes `csat_score`/`csat_comment`. `GET`/`POST /support/tickets/{id}/csat`.
- **SLA:** `sla_due_at = created_at + hours[priority]` where hours =
  `{urgent:4, high:8, normal:24, low:72}` (business-hours refinement deferred).
- **Escalation job:** new `backend/jobs/support_sla.py::run_sla_escalation()`,
  registered in `main.py` scheduler (hourly). Finds `status in (open) AND
  sla_due_at < now AND first_responded_at IS NULL`, emails Vinay a digest
  (Redis nx dedup per ticket, mirror `run_trial_nudge`). No auto-actions.
- **Canned macros:** start as a constant list of `{label, body}` markdown
  snippets the admin inbox can insert into a reply. `ponytail:` constant now,
  move to a table only if Vinay wants to edit them without a deploy.

## Admin inbox (super_admin)

- `GET /support/admin/tickets` — cross-org list with filters (status, priority,
  category, overdue). **This is the one place super_admin reads across orgs.**
  Permitted because tickets are a *support* data class, not clinic PII routes.
  Reuse the admin-guard pattern (`is_admin`/`super_admin`), NOT `forbid_admin`.
- Admin can reply, set status/priority, insert macros. Replies notify the user.
- Frontend: a new section under the existing Admin page (or a sibling route).

## DPDP / security posture

- **Tickets are a new data class** (support conversations), distinct from the
  patient-PII routes super_admin is locked out of. The ticket form shows a
  notice: "Don't paste patient names, phone numbers, or health details —
  describe the issue instead." (Decision 2026-07-11: warn + treat as support
  data; no auto-scrub.)
- RULE 1 still holds for clinic data: the chatbot has no clinic-data access;
  ticket reads are `WHERE org_id` scoped for clinic users; only super_admin
  crosses orgs, and only for tickets.
- RULE 9: ticket/message bodies are user-authored support text; log IDs +
  last-4 of any phone, never full bodies, in structured logs.
- RULE 8: every email send is best-effort and must never fail/block a ticket
  or message write.
- Rate-limit + Turnstile on all public endpoints (chat, ticket create) to stop
  spam/abuse (API4 resource consumption). Cap body length (e.g. 8 KB) and
  history length at the boundary (Pydantic) — mirrors the #313 bounded-field
  posture.
- Public lead tickets (org_id NULL) are a spam target: Turnstile + rate limit +
  length caps are the defense; no auth by design.

## Frontend surfaces

- **Public:** `/help` page (FAQ search over public KB + chat widget + contact
  form). A chat launcher on Landing. Dark-mode aware (reuse the token system +
  ThemeToggle from #311).
- **In-app:** a "Help" entry in the Shell nav → Help page (AI assistant + KB
  search + "My Tickets" + new-ticket form). A persistent help launcher is
  optional.
- **Admin:** support inbox section in the Admin area.
- All new UI uses existing patterns: TanStack Query, axios JWT interceptor,
  Tailwind CSS-var tokens, GSAP only where it already fits (no new deps).

## Config / env

No new secrets. Reuses `GEMINI_API_KEY`, `OPENAI_API_KEY` (fallback),
`RESEND_API_KEY`/`RESEND_FROM`, `TURNSTILE_SECRET_KEY`, `ALERT_EMAIL`
(escalation target — already `hello@vachanam.in`). Optional new tunables with
safe defaults: `SUPPORT_SLA_HOURS` (JSON, defaulted in code),
`SUPPORT_BOT_MAX_OUTPUT_TOKENS`.

## Phasing (each phase ships working software)

- **Phase 1 — Self-serve + bot.** KB corpus + `/support/kb` + `/support/chat`
  (public+authed, grounded, rate-limited) + public `/help` page + in-app Help
  page + "contact us → email" (no ticket table yet; contact routes to email).
  *Highest value, smallest surface, no migration.*
- **Phase 2 — Ticketing + live-chat-poll.** Migration (2 tables) + ticket CRUD
  + My Tickets UI + admin inbox + email notifications + chat-widget polling +
  "escalate from bot to ticket". Contact form now creates a ticket.
- **Phase 3 — CSAT + SLA/escalation + macros + demo form + status link.** CSAT
  flow, SLA job + escalation email, canned macros, "book a demo" public form
  (public lead ticket), UptimeRobot status link.

## Testing strategy

- **Phase 1:** chatbot grounds to KB (mock Gemini → assert prompt carries KB +
  refusal on empty KB); RULE 1 (bot route has no clinic-data access / never
  returns another org's data); public chat requires Turnstile + is rate-limited;
  KB audience filtering (public subset excludes clinic-only). Length caps 422.
- **Phase 2:** ticket create/list/reply org-scoped (extend the IDOR wall —
  clinic B cannot read clinic A's ticket → 404); status transitions; email
  best-effort (Resend down → ticket still writes, RULE 8); admin inbox
  cross-org allowed for super_admin but blocked for org_admin; migration head
  test.
- **Phase 3:** SLA due-date computation per priority; escalation job selects
  only overdue+unanswered and dedups; CSAT write bounds (1–5).
- FIXLOG row per phase; full suite green after each (Docker PG/Redis up);
  `npm run build` gate on frontend phases.

## Open items for Vinay

- KB content accuracy — I'll draft the ~15 entries; Vinay proofreads pricing,
  DID/onboarding, and refund wording before they go live.
- Prod migration apply (Phase 2) is a gated step Vinay confirms separately.
- Whether canned macros need runtime editing (table) or a constant list is fine
  to start.
