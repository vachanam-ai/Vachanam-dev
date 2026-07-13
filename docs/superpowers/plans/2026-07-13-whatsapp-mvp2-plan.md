# WhatsApp MVP2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clinic-number WhatsApp (Meta Cloud API direct): 4 outbound utility templates + button/Gemini inbound chat, gated to Clinic+Multi plans, fully no-op without creds.

**Architecture:** New webhook router + `wa_service` (sends) + `wa_chat` (Gemini free text) in backend; existing `MetaService` stubs become thin bridges to `wa_service`; branch resolved from receiving `phone_number_id` (RULE 5); all booking writes reuse existing atomic paths (RULE 2/3).

**Tech Stack:** FastAPI, httpx, tenacity, google-genai (existing pattern from `support_bot.py`), Alembic, Redis (idempotency), React dashboard card.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-13-whatsapp-mvp2-design.md` — decisions table is binding.
- Plan gate: `WHATSAPP_PLANS = frozenset({"clinic", "multi"})` in `backend/services/billing_math.py` (single source).
- No creds (`META_ACCESS_TOKEN` or branch `wa_phone_number_id` empty) → every send no-ops with `wa_skipped_unconfigured` / `wa_skipped_plan` log. Prod-safe from first deploy.
- RULE 4: outbound send failure NEVER raises into a booking path — `wa_service` catches everything terminal and logs `wa_send_failed`.
- RULE 5: inbound branch = `Branch.wa_phone_number_id == value.metadata.phone_number_id`. Never the patient's number.
- RULE 9: template bodies carry logistics only (clinic, doctor, date/time, token, address). No complaint/visit-note text anywhere, incl. low-score alert email.
- Template names (Meta + code must match): `booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook`; languages `te`, `en` day 1.
- Webhook: `GET/POST /webhooks/whatsapp`, public (no JWT), HMAC `X-Hub-Signature-256` with `META_APP_SECRET`, GET handshake with `META_WEBHOOK_VERIFY_TOKEN`. Always 200 on POST after auth (Meta retry-storm guard); 403 only on bad HMAC/verify-token.
- Idempotency: inbound `messages[].id` via Redis `SETNX wa:msg:{id}` TTL 24h (use `backend` redis_client helper — NEVER per-call clients, #305).
- Migration deploy-gated as usual: additive only (`branches.wa_phone_number_id` VARCHAR(32) NULL; `ratings` table).
- FIXLOG not required (feature, not fix) — CHANGELOG + STATUS rows instead. Full suite green before each push.

---

### Task 1: Config + plan gate

**Files:** Modify `backend/config.py` (add `meta_access_token`, `meta_phone_number_id`, `meta_waba_id`, `meta_webhook_verify_token`, `meta_app_secret` — all `str = ""`, matching `.env.example` names), `backend/services/billing_math.py` (add `WHATSAPP_PLANS`). Test `tests/unit/test_billing_math.py` (append).

**Interfaces produced:** `settings.meta_*`; `billing_math.WHATSAPP_PLANS`.

- [ ] Failing test: `test_whatsapp_plans_gate()` → `assert WHATSAPP_PLANS == {"clinic", "multi"}` and `"solo" not in WHATSAPP_PLANS`.
- [ ] Implement; verify `.env.example` names match config fields exactly (drift has bitten — CLAUDE.md).
- [ ] Run `pytest tests/unit/test_billing_math.py -q` → green. Commit `feat(wa): config + plan gate`.

### Task 2: Migration — `wa_phone_number_id` + `ratings`

**Files:** Modify `backend/models/schema.py`; create `alembic/versions/ff29_whatsapp_ratings.py` (down_revision = current head ee28).

**Interfaces produced:**
- `Branch.wa_phone_number_id: Mapped[str | None]` (String(32), unique=True — one number, one branch).
- `Rating` model: `id UUID pk, branch_id UUID FK branches CASCADE (indexed), token_id UUID FK tokens SET NULL UNIQUE, patient_id UUID FK patients SET NULL, score int (CheckConstraint 1..5), created_at tz-aware`.

- [ ] Failing test `tests/integration/test_ratings_model.py::test_rating_unique_per_token` (insert two ratings same token_id → IntegrityError) and `::test_rating_score_bounds` (score=6 → IntegrityError).
- [ ] Model + migration (create_all covers tests; migration is for prod). Green. Commit `feat(wa): schema — wa_phone_number_id + ratings`.

### Task 3: `wa_service` — sends

**Files:** Create `backend/services/wa_service.py`. Test `tests/unit/test_wa_service.py`.

**Interfaces produced (later tasks consume these EXACT signatures):**
```python
async def send_template(branch, to: str, template: str, lang: str,
                        body_params: list[str],
                        buttons: list[dict] | None = None) -> bool
async def send_text(branch, to: str, text: str) -> bool
async def send_interactive(branch, to: str, interactive: dict) -> bool
def wa_enabled(branch, plan: str) -> bool   # creds + wa_phone_number_id + plan gate
```
POST `https://graph.facebook.com/v21.0/{branch.wa_phone_number_id}/messages`, bearer `settings.meta_access_token`, httpx timeout 10s, tenacity 3× expo (1-4s), terminal failure → `wa_send_failed` log, return False. `wa_enabled` False → `wa_skipped_unconfigured|wa_skipped_plan` log, return False. Logs: `to_last4`, template name, branch_id — never body text (RULE 9).

- [ ] Failing tests (httpx mocked via `respx` if installed else monkeypatch `httpx.AsyncClient.post`): payload shape for template with body params + quick-reply buttons; no-op paths (no token / no number / solo plan) send NOTHING; network error → False, no raise.
- [ ] Implement. Green. Commit `feat(wa): wa_service sends`.

### Task 4: Template builders + real MetaService bridge

**Files:** Create `backend/services/wa_templates.py` (pure functions returning `(template, lang, body_params, buttons)` per flow; lang = patient's per-caller language if in {te,en} else "en"). Rewrite `backend/services/meta_service.py` `send_booking_confirmation` to resolve branch + org plan, build `booking_confirm` params (clinic, doctor, date/time or token, address + `https://maps.google.com/?q={quoted address}`), call `send_template`; buttons `[{"id": f"rs:{token_id}", "title": "Reschedule"}, {"id": f"cx:{token_id}", "title": "Cancel"}]`. Mirror in `agent/services/meta_stub.py` — replace stub body with import+delegate to backend real service (agent already imports backend modules). Test `tests/integration/test_wa_confirmation.py`.

**Button ID contract (Task 6 consumes):** `rs:{token_id}`, `cx:{token_id}`, `rate:{token_id}:{1-5}`, `slot:{token_id}:{date}:{HH:MM|none}`.

- [ ] Failing tests: linked clinic-plan branch → one send with correct params; solo/unlinked → zero sends; wa failure does not raise (RULE 4).
- [ ] Implement. Green. Commit `feat(wa): booking confirmation template + bridge`.

### Task 5: Webhook router — verify, HMAC, dispatch skeleton

**Files:** Create `backend/routers/whatsapp_webhook.py`; register in `backend/main.py`. Test `tests/integration/test_wa_webhook.py`.

**Interfaces produced:** `GET /webhooks/whatsapp` (hub.mode/verify_token/challenge → 200 challenge or 403); `POST /webhooks/whatsapp` → verify HMAC (`hmac.compare_digest`, sha256 of RAW body) → parse `entry[].changes[].value`; resolve branch by `value.metadata.phone_number_id`; unknown branch → log+200; dedupe message id (Redis SETNX); route: `interactive.button_reply.id` prefixes → Task 6 handlers, `text.body` → Task 7 chat, `statuses` → log only. Every handler wrapped: exception → `wa_inbound_error` log + 200.

- [ ] Failing tests: handshake ok/bad token; POST bad signature 403; good signature dispatches to a monkeypatched handler; RULE 1 test — event with branch B's phone_number_id NEVER reaches branch A data (two branches fixture, crossed event asserts handler got branch B only); duplicate message id processed once.
- [ ] Implement. Green. Commit `feat(wa): webhook router`.

### Task 6: Button handlers (reschedule / cancel / rating)

**Files:** Create `backend/services/wa_actions.py`. Test `tests/integration/test_wa_actions.py`.

**Interfaces produced:**
```python
async def handle_reschedule_start(db, branch, patient_phone: str, token_id: str) -> None
# → next 3 open slots via existing availability logic → send_interactive list,
#   row ids "slot:{token_id}:{date}:{time|none}"
async def handle_slot_pick(db, branch, patient_phone, token_id, date_s, time_s) -> None
# → SAME atomic reschedule path the voice tool uses (import the shared service
#   function the agent's _do_reschedule delegates to for assign/confirm/cancel;
#   do NOT reimplement) → send_text confirmation or "call us" line
async def handle_cancel(db, branch, patient_phone, token_id) -> None  # confirm prompt → on 2nd tap cancel via existing path
async def handle_rating(db, branch, patient_phone, token_id, score: int) -> None
# → upsert Rating (unique token); score <= 2 → owner email via support_email
#   pattern (subject only, "low rating {score}/5 from …last4" — NO free text)
```
Phone→patient scoped by branch (RULE 1). Token ownership check: token.branch_id == branch.id AND patient phone matches — smuggled token_id in button payload → log + generic "call us" reply, no data.

- [ ] Failing tests: reschedule offers ≤3 slots; slot pick books atomically (no double-book — reuse concurrency fixtures pattern); cancel two-step; rating stored once, low-score email fired w/o body text; cross-branch token_id rejected.
- [ ] Implement. Green. Commit `feat(wa): button flows`.

### Task 7: `wa_chat` — Gemini free text

**Files:** Create `backend/services/wa_chat.py`. Test `tests/unit/test_wa_chat.py`.

**Interfaces produced:** `async def handle_text(db, branch, patient_phone: str, text: str) -> None`. Gemini via `support_bot._call_gemini` pattern (same breaker `guard("gemini_wa_chat", ...)`), prompt: clinic context + RULE 7 block (verbatim discipline from voice prompt: no medical judgment, no diagnoses; medical/new-booking/complaint → reply with tap-to-call `tel:` clinic number line) + tool schema as JSON intent output: `{"intent": "reschedule|cancel|location|faq|out_of_scope", ...}`. `reschedule`→`handle_reschedule_start`; `cancel`→`handle_cancel`; `location`→send_text address+maps link; `faq`→answer from branch FAQ rows (existing model) else out_of_scope. Gemini failure/unparseable → static "please call us at {number}" (RULE 8). 24h-window discipline: this is only ever invoked as a REPLY to an inbound message → always in-window; no unprompted session sends anywhere.

- [ ] Failing tests (Gemini mocked): each intent routes correctly; medical text → tap-to-call, no LLM answer relayed of medical content; Gemini exception → static fallback; prompt contains RULE 7 markers ("no medical", "book appointments only" — unwrappable tokens).
- [ ] Implement. Green. Commit `feat(wa): gemini free-text chat`.

### Task 8: Outbound jobs — reminder, rating batch, leave-rebook

**Files:** Modify `backend/jobs/pre_appt_reminder.py` (after voice dispatch per booking: independent try/except `send_template(appt_reminder)`), `backend/services/cascade_cancel.py` (leave-rebook ping alongside call), `backend/routers/queue.py` Seen transition (set nothing new — rating batch reads Seen tokens), create `backend/jobs/wa_rating_ask.py` (APScheduler daily 19:00 IST: today's tokens status Seen, branch linked + plan ok, no Rating row, no prior ask — mark via `tokens`-scoped Redis key `wa:rated:{token_id}` TTL 7d; send `rating_ask` with `rate:{token_id}:{n}` buttons). Register job in scheduler setup (same place other jobs register). Test `tests/integration/test_wa_outbound_jobs.py`.

- [ ] Failing tests: reminder job fires template only for linked+gated branches and never raises into the voice dispatch on wa failure; rating batch sends once per token (Redis key) and skips already-rated; cascade sends ping alongside rebook, failure silent.
- [ ] Implement. Green. Commit `feat(wa): outbound jobs`.

### Task 9: Admin link endpoint + dashboard surfaces

**Files:** Modify `backend/routers/admin.py` (super_admin `PATCH /admin/branches/{branch_id}/whatsapp {"wa_phone_number_id": "..."}` — set/clear; unique-violation → 409), `backend/routers/branches.py` (GET `/{branch_id}/ratings/summary` → `{"avg": float|None, "count": int, "low_count": int}` owner-scoped), `frontend/src/pages/Dashboard.jsx` (RatingsCard: avg stars + count, low-score chip; hidden when count==0; `revealNow` pattern like MessagesCard), `frontend/src/pages/Settings.jsx` (read-only "WhatsApp: linked/not linked" line in a small section). Tests: `tests/integration/test_wa_admin_link.py` (RULE 1: owner of org A cannot read B's summary; admin sets id; duplicate id 409), frontend `npm run build`.

- [ ] Failing tests → implement → green → build green. Commit `feat(wa): admin link + ratings dashboard`.

### Task 10: Meta template registration pack + docs + ship

**Files:** Create `docs/runbooks/META_TEMPLATES.md` — exact copy for the 4 templates × te/en to paste into Meta Business Manager (body with {{1}}.. placeholders, buttons, category UTILITY; Telugu copy generated via humanizer/Gemini spoken-style, never hand-written). Update `docs/runbooks/META_WHATSAPP_SETUP.md` B4 with the real admin PATCH call. Update `docs/STATUS.md`, `docs/CHANGELOG.md`, `.env.example` (already has the 5 vars — verify). Memory file update (project-mvp1-mvp2-split note: WhatsApp now building).

- [ ] Full suite `pytest tests/unit tests/integration -q` green + `npm run build` green + ruff green.
- [ ] Commit `feat(wa): template pack + docs`, push (webhook endpoint goes live on Render) → tell Vinay A7 is unblocked.

## Self-review

- Spec coverage: decisions table → T1 (gate), T2 (schema), T3-4 (sends+confirm), T5 (webhook), T6 (buttons), T7 (Gemini+RULE 7), T8 (reminder/rating/leave), T9 (dashboard+admin), T10 (templates+runbooks). Costs/rollout sections are ops, covered by runbooks. ✓
- Placeholders: none — signatures, ids, payload shapes, test intents all pinned. ✓
- Type consistency: `send_template(branch, to, template, lang, body_params, buttons)` used identically in T4/T8; button id grammar defined once (T4) consumed in T5/T6/T8. ✓
