# Vachanam — Status (single source of truth)

> **2026-07-24 — P0 VOICE LATENCY CORRECTION (PRODUCTION — Fly v177).**
> Production call evidence showed first audio at 14.36s, despite the caller
> reporting roughly 7s, and ordinary reply gaps around 1.4–1.7s. Root causes
> were concrete: returning-caller personalization forced uncached live greeting
> synthesis; recording serialized the whole opening before capture/session
> setup; startup opened a throwaway Soniox warm stream plus two filler synth
> streams and hit the account's 429 concurrency limit; forced Sarvam STT added
> 0.79–0.88s transcription delay. The inbound opening now starts from a stable
> branch cache immediately after tenant resolution, while caller/billing/prompt
> work runs behind it. Recorded admin calls isolate and finish only the notice
> before capture, then overlap the cached intro with session startup. The
> redundant TTS warm stream is deleted and filler banks synthesize sequentially.
> Both production branches' Soniox intro/notice Redis entries are pre-warmed.
> The new Japan-project key authenticated against both Japan endpoints and
> returned real STT and Telugu TTS audio. Production now uses Soniox Japan for
> STT and TTS. Honest acceptance gates: first audible
> response p50 <0.5s after branch resolution; normal perceived turn gap p50
> <1.0s and p95 <1.5s. A semantic answer <0.5s is not currently possible while
> measured Soniox TTS TTFB alone is ~0.57–0.59s.

> **2026-07-24 — TEMPORARY ADMIN-ONLY RECORDING + SONIOX-ONLY TTS (PRODUCTION).**
> `RECORDING_ENABLED=true` can now record audio only when
> the caller/callee exactly matches configured `ADMIN_PHONE`; every other
> LiveKit session explicitly starts with `record=False`. The localized recording
> notice is the first segment and must finish before audio capture starts; a
> notice-playback failure disables recording for that call. Capture is audio
> only (no transcript, traces, or logs), and a per-call `recording` consent row
> is written. LiveKit Agent Insights retains uploads for 30 days; its project
> Data & Privacy “Agent observability” toggle must be enabled. Shutdown is one
> secret flip: `flyctl secrets set RECORDING_ENABLED=false -a vachanam-agent`.
> TTS is now Soniox-only across live replies, greetings, fillers, blocked-call
> notices, and the Settings catalog. Smallest imports, runtime adapters, config,
> packages, services, scripts, and rollback branches were removed. Legacy stored
> voice IDs resolve to Priya until changed to a Soniox catalog voice. Proof so
> far: focused 164 checks green; full unit 754 green after one corrected
> recording-aware prompt-cache guard; Settings integration 2 green; Ruff,
> frontend lint, 6 Vitest tests, Vite build, and seven real Soniox sample WAVs
> green. Local agent image installed the new dependency set, then Docker Desktop
> aborted in LiveKit's existing turn-detector `download-files` layer after it
> reported completion; the remote CI/Fly build is the deployment gate.

> **2026-07-24 — EXPRESSION-AWARE SLOW-TOOL HOLDS.** Availability,
> booking lookup, booking, rescheduling, and cancellation now play a cached
> language-specific “one moment / checking” cue ending in Soniox
> `[long pause]` while the operation runs. Quick tools remain quiet and the
> existing 12-second cooldown prevents repeated holds in one booking flow.
> Prompt guidance makes expression placement explicit and prevents the model
> from duplicating the runtime-owned pause.

> **2026-07-24 — VOICE PROMPT + APPOINTMENT-TRUTH RELEASE.** Rewrote the
> production voice prompt around concrete audible
> behaviour: calm baseline, optional/rare disfluency, one closed Soniox
> expression allowlist, and no forced filler cadence. The TTS boundary now
> strips invented expression tags and converts only phone-length digit runs;
> times, dates, ages, fees, and tokens remain natural in the call language.
> One shared branch-local `booking_is_upcoming` predicate now drives caller
> context, lookup, availability, cancel, and reschedule, so a finished same-day
> slot cannot be presented or mutated as future. Successful booking and
> reschedule confirmations add the natural-language equivalent of "Please come
> on time"; cancellation does not. Latency plan updated from the measured
> 1.4s p50 / 2.5s p95 trace; next step is classify unaccounted/commit outliers
> before provider tuning. Proof: 776 unit tests, 105 focused unit/integration
> checks, Ruff, frontend lint + 6 Vitest tests + Vite production build green.

> **2026-07-24 — LIVE-TEST FEEDBACK ROUND (#455, after v1.9.0 deploy).** Vinay's
> Venkateshwara call: robotic tone, unwanted follow-up-consent question, ~3s
> perceived latency. Shipped: humanized `<role>` (real Hyderabad receptionist —
> reactive first words, mirror energy, no announce-then-act), `followup_consent`
> defaulted True (never asked), and the #444/#446/#447/#449 per-turn ms trace
> RESTORED from git history (voice_turn_latency lines → Redis `lat:turns`;
> `scripts/analyze_voice_latency.py --redis` = the per-ms notes Vinay asked for).
> Also live in v1.10.x: full Soniox expression vocabulary + sound-human prompt.
> NEXT: Vinay re-calls → pull lat:turns → ms table → fix the measured stage only.

> **2026-07-24 — SUPERSEDED TTS DESIGN (history): SONIOX SWITCH + FEASIBLE LATENCY TECHNIQUES + ODIA REMOVED
> (built + unit-green LOCAL; NOT deployed).** Vinay: latency #1, keep Soniox
> (better voice), then-smallest fallback, drop Soniox cloning. The fallback and
> provider switch described below were removed by the Soniox-only release above.
> Against the 12-technique
> writeup, built the genuinely-feasible set and proved the rest:
> • **TTS → Soniox tts-rt** streaming primary + smallest.ai RULE-8 fallback,
>   `TTS_PROVIDER` kill-switch (instant rollback, no deploy). Model `tts-rt-v1`,
>   default voice Priya. No cloning.
> • **#8 TTS prewarm** — Soniox WS warmed per worker, reused on matching turns
>   (kills the ~450ms cold connect that made Soniox TTFB look bad).
> • **#5 tool prefetch** — doctor-routing fired in parallel on booking turns, on a
>   DEDICATED session (RULE 1 branch-scoped), cancel-safe; kill-switch VOICE_TOOL_PREFETCH.
> • **Already done (proven in code):** #1 preemptive, #2 streaming TTS, #3 Vertex
>   cache #417, #7 async-eval, #11 KV, #12 STT-JP-edge + LLM-Mumbai.
> • **Not built (honest):** #4/#9 tiered routing (LLM not the bottleneck, gain≈0),
>   #6 AEC (N/A on PSTN), #10 cached-audio injection (BANNED — same as the #399
>   revert). See `docs/superpowers/specs/2026-07-24-soniox-tts-latency-design.md`.
> • **Odia removed** — platform now 7 Indian languages (te/hi/ta/kn/ml/mr/bn) +
>   English on request. get_lang('or')→Telugu, no migration. ⚠ CLAUDE.md pricing
>   copy still says "all 8" — needs a Vinay marketing-copy update to "all 7".
> • **Soniox expression tags** — OPEN set ([Happy]/[Giggles]/[Angry]/… examples,
>   LLM adds any that fits); Soniox acts them, smallest fallback strips ANY [Word]
>   tag (RULE 6). **Prompt freed** of the verbose number/time pronunciation rules —
>   the deterministic English-digit sanitizer (#408) KEPT (still enforces + guards
>   the fallback); only the LLM-facing pronunciation how-to was removed.
> • **Pre-push audit (#453)** fixed 4 real bugs: prewarm was a silent no-op (WS
>   connect now fires at session build), three-voice call (greeting/fillers/blocked
>   line now synth via Soniox — ONE voice per call; provider-marked greeting cache),
>   /voices picker now offers the real Soniox voices (Priya/Meera/Arjun/Rohan),
>   prefetch task exception retrieval. Copy all-8→all-7 everywhere (incl CLAUDE.md,
>   ToS).
> • **Voice cloning REMOVED platform-wide (#454, Vinay):** endpoints, service fns,
>   billing gates (CLONING_PLANS/cloning_allowed), agent per-language clone
>   resolution, Settings clone UI + recorder, and all marketing copy. Catalog
>   voices only. branches.cloned_voices column retained (inert; drop = future
>   migration).
> ⚠ NOT deployed: unit suite green locally, prod still on the pre-existing image.
> Needs a live call to validate the Soniox voice, then push (CI auto-deploys).
> The measured floor stands: latency is the Soniox STT Tokyo RTT, not the pipeline —
> Soniox TTS trades ~a bit of TTFB for the better voice, offset by #8 prewarm.

> **2026-07-24 — REVERTED THE TTFA LATENCY EXPERIMENTS (commit `4932c49`).**
> Vinay's call: the per-turn latency work did not deliver a satisfying win, so
> the voice path is rolled back to the last known-good checkpoint `0584e31`.
> REVERTED: F5 deterministic confirmations (#445, confirm_speech.py + i18n
> confirm lines + VOICE_DETERMINISTIC_CONFIRM flag), the #444 per-turn
> `voice_turn_latency` trace (turn_trace.py) and its #446/#447 telemetry fixes,
> and the #449 latency ladder. The "come on time" booking-instruction addition
> went with them. STT/booking behavior is now exactly `0584e31`. The two banners
> below (#445, #444) are HISTORY — no longer current. KEPT: the CI/CD auto-deploy
> pipeline, semver versioning, one-click rollback. The raw-latency sandbox rig
> (sandbox/raw-latency/, Dockerfile.speed, fly.speed.toml, analyze_voice_latency.py)
> is deleted; Fly app `vachanam-speed` scaled to 0 (secrets kept). DIDs routed
> back to `vachanam-agent`. ⚠ Prod runtime still runs the pre-revert image until
> the next master deploy — redeploy to put `0584e31` voice code live.

> **2026-07-22 — F5 DETERMINISTIC CONFIRMATIONS (#445).** Successful booking/
> reschedule/cancel now speak a fixed native-script line DIRECTLY (StopResponse
> suppresses the second LLM pass) — tool completion → first audio ≈0.3-0.5s on
> the product's most valuable turns (was ~1.5-2.5s). te/en/hi templates (token
> doctors: TOKEN+date; appointment doctors: DATE+TIME only; come-on-time close);
> other languages keep the LLM path. Live-AgentSession gate keeps every tool
> test contract unchanged. Kill switch VOICE_DETERMINISTIC_CONFIRM. ⚠ te lines
> first-pass — validate on a real call. FLY_API_TOKEN secret added 2026-07-22 —
> this push is the pipeline's first live release+deploy.

> **2026-07-22 — CI/CD PIPELINE LIVE + TTFA REVIEW + PHASE-1 TRACE (#444).**
> CI/CD: master push now auto-runs lint/pytest/frontend/gitleaks → semver tag →
> GitHub Release → Fly agent deploy; one-click rollback workflow (any tag);
> baseline tag `v1.0.0`; CI clock pinned IST (8 date tests failed on UTC
> runners 18:30-24:00 UTC — proven + fixed in CI-identical Docker). TTFA deep
> review: docs/superpowers/specs/2026-07-22-ttfa-deep-review.md — measured
> stages sum 1.6-2.3s vs ~3s perceived; sub-1s judged unreachable for
> conversational turns (Telugu endpoint physics) but reachable post-tool via
> deterministic confirm lines (F5); prime suspect for the unattributed ~1s =
> preemptive-generation cancels (F2). Phase 1 implemented (#444): per-turn
> `voice_turn_latency` trace + scripts/analyze_voice_latency.py. NEXT: deploy,
> collect ≥30 calls (plan Phase 2), fix the measured dominant stage ONLY.

> **2026-07-21 — CLIENT-DEMO CALL RELEASE #443.** Production prompt replaced
> by a compact priority/state machine; fresh symptoms invalidate old routing;
> Soniox receives clinic specialties plus Telugu dental/ENT context; పని/పంటి
> ambiguity is clarified; reminders contain private data without tool
> signatures; streamed TTS has a deterministic internal-trace firewall.
> Latency profile: Soniox level 1 + vendor-default sensitivity/cap, 200ms
> VAD manual finalization, LiveKit 50–300ms post-final window. Offer pricing is
> restored for the first 3 paid months after the universal 14-day trial;
> WhatsApp remains Clinic/Multi. Release gate: 1,263 passed / 2 skipped plus
> Python compile and production frontend build. DEPLOYED: commit `18ce737`;
> Render health build `18ce737`; public frontend bundle has trial + offer copy;
> Fly v151 image `deployment-01KY1N6B05EBTWGDAHDA8P747G`; runtime profile
> Agents/Soniox 1.6.6, level=1, cap=2000, sensitivity=None, manual_finalize=200;
> fresh LiveKit India West registration 06:19:34Z.

> **2026-07-21 — SONIOX TURN-LATENCY ROLLOUT DEPLOYED (FIXLOG #442, FLY v149).**
> LiveKit/Soniox 1.6.6 endpoint tuning is wired with a one-variable rollout:
> semantic endpoint latency level 1 only. Sensitivity stays vendor-default,
> maximum endpoint delay stays 2000 ms, and manual finalize stays OFF. A
> cancellable, per-call 200 ms+ manual-finalize path and Soniox/Sarvam provider
> switch exist as guarded follow-up experiments/rollback controls. Worker
> startup reports installed versions plus the effective profile. Regression:
> full repository 1,256 passed / 2 skipped; focused latency/STT 37 passed.
> Production proof: Agents/Soniox 1.6.6, inference + 3 job processes healthy,
> registered LiveKit India West 04:44:57Z; active profile level=1, cap=2000,
> sensitivity=None, manual_finalize=0. Research: SONIOX_LATENCY_RESEARCH.md.

> **2026-07-14 — WHATSAPP MVP2 CODE-COMPLETE (spec 2026-07-13, T1-T10) + REAL-CALL FIXES #361-370.**
> WhatsApp: clinic-number Coexistence, direct Meta Cloud API. Built: plan
> gate (Clinic+Multi) · ff29 migration (wa_phone_number_id + ratings —
> DEPLOY-GATED, not on prod) · wa_service sends · 4 template builders + real
> MetaService bridge (agent stub delegates) · HMAC webhook w/ RULE 5 branch
> resolution + Redis dedupe · buttons (rating FULL; reschedule/cancel day-1
> = Dashboard PatientMessage + honest "clinic will call you" — self-serve
> slot-pick = T6b after _do_reschedule extraction) · Gemini free-text chat
> (RULE 7) · reminder ride-along + 19:00 IST rating batch + cascade leave
> ping · admin PATCH link + Dashboard RatingsCard + Settings status.
> EVERYTHING no-ops without creds — prod-safe from first deploy. GO-LIVE
> GATES: Vinay's Meta setup (runbooks/META_WHATSAPP_SETUP.md; webhook A7
> after next backend deploy) + templates (runbooks/META_TEMPLATES.md) +
> ff29 applied to prod + branch link (B1-B5, max 2 numbers pre-verification).
> Real-call fixes DEPLOYED (Fly v106): #361 booking writes survive barge-in,
> #362/363 switch gap + per-language fillers, #364 per-doctor calendars
> (Vinay: paste calendar IDs in Doctors page), #365 whose-number ask,
> #368 short intros all languages, #370 garbled-switch ladder, #369 test
> EMAIL fuse (mail bursts were our own suite via live Resend key), #366/367
> mobile Help + chat scroll. TD-039 deploy deaf-window (~2 min) logged.
> "Vachanam for Doctors" assessed + PARKED (build only if the doctor returns).

> **2026-07-12 (evening) — MAIL-SPAM ROOT-CAUSED + CI GREEN PATH, MESSAGES-FOR-DOCTOR, TRANSFER ESCALATION, PAY BUTTON (FIXLOG #346-351).**
> The "spam" was GitHub Actions: keepalive bash exit-code bug red EVERY 5 MIN
> since Jul 3 (~2,600 runs) + secrets-scan conftest import + npm form-data HIGH
> + CI had NO pytest + 4 real test failures once it did (biggest:
> `fastapi>=0.110` float → CI got 0.139 lazy include_router; NOW PINNED
> `fastapi==0.139.0`; rate-limiter test walks effective_route_contexts()).
> NEW: patient_messages (ee28 **APPLIED to prod**) + take_message tool +
> Dashboard "Messages for the doctor" card + urgent owner-email (no text in
> mail, RULE 9) — replaces the empty "I informed the clinic". Inbound
> follow-up replies now reach FollowupTask.response_summary (#347). Transfer
> escalation (#350): urgent = immediate transfer; third doctor-ask ALWAYS
> transfers; failed transfer speaks the emergency number digit-by-digit.
> Settings pay button always visible (#351; active-no-cycle orgs had NO pay
> path). GSI white ring cropped (#348). Suites: integration 321 + unit/sec
> 652 green local; CI-replica container proof for the fastapi pin.
> **SCOREBOARD (e622d19): CI ✅ (pytest on GitHub runners green for the FIRST
> TIME) + security-gate ✅ + keep-render-warm ✅ — the failure-mail flood is
> over.** Agent Fly v101 deployed (bom) with #333/#347/#349/#350. Last
> gremlin was setup-python's pip-cache post-step failing the job while every
> real step passed (removed — installs are --no-cache-dir).

> **2026-07-12 — LEGAL REBRAND + VENDOR SCRUB + UI BATCH + END-TREATMENT (FIXLOG #321-323).**
> Legal pages (/privacy /terms /dpa /refunds /data-handling /data-safety) now
> brand-styled (teal tokens, Fraunces/Outfit, dark mode, topbar). Processors
> listed BY ROLE (stack confidential; named list via privacy@ on request;
> Google+Razorpay stay named). NEW terms §6.1 — 10 "not responsible for" heads.
> UI: `.input` alias fixed 19 unstyled support controls; compact density
> (btn/field text-sm py-2) + 44px touch via pointer:coarse; navbar signout
> nowrap+truncate; logo → roleHome. NEW end-treatment endpoint + button
> (one-time visitor cleanup; optional DPDP erase via shared
> services/patient_erasure.py, extracted from retention job).

> **2026-07-12 — FAULT-TOLERANCE PRIMITIVES + CHAOS HARNESS (FIXLOG #320, master-local).**
> `backend/services/resilience.py`: one `guard(name, coro_factory, timeout,
> retries, backoff, fallback)` wrapper = chaos injection → circuit breaker
> (5-fail open, 30s reset, half-open probe) → per-attempt timeout → backoff retry
> → metrics (ok/failed/timeout/rejected + latency avg/p95/error-rate). Chaos
> (per-dependency latency + fail-rate) is HARD-OFF unless `CHAOS_ENABLED=true`
> (new flag, default False) so it can never fire in prod. Wired into both Resend
> paths (support + watchdog) sharing one `resend_email` breaker. Owner endpoints:
> `GET /admin/resilience` (board), `POST/DELETE /admin/resilience/chaos` (arm/
> disarm drill). In-process state (single Render worker; Redis path noted for
> multi-worker). Proof: `tests/unit/test_resilience.py` (10). No migration.

> **2026-07-11 — SUPPORT SYSTEM PHASE 1 (master, code pushed; migration deploy-gated).**
> Self-serve support core (FIXLOG #314): a markdown KB (`docs/support/*.md`,
> audience-filtered) + a Gemini-grounded chatbot (`/support/chat`) that
> auto-logs ONE ticket per chat — answered→`ai_resolved`, stuck→`open` (the
> human fallback). New `support_tickets`+`support_messages` (migration `aa24`,
> **APPLIED to prod 2026-07-11** — prod head now `aa24`; `/support/kb` live 200).
> Org-scoped ticket reads (IDOR-walled). Frontend: public `/help` (KB search +
> chat) + in-app `/tickets` thread + Support nav. `"support"` role value added
> (no route yet). Bot: RULE 1 (no clinic-data access), RULE 8 (safe refusal),
> RULE 9 (logs IDs). **Phase 2+3 SHIPPED (FIXLOG #315):** `support` role
> (platform staff, PII-locked via forbid_admin) + super_admin staff provisioning;
> cross-org support dashboard (list/reply/status/priority/macros); clinic-user
> reply + CSAT; SLA due-dates + hourly escalation (rides maintenance wake, #299);
> public contact/demo form → lead ticket. Frontend: SupportAdmin, MyTickets
> live-poll+reply+CSAT, Help contact form + status link. **Migration `bb25`
> (ALTER TYPE user_role ADD 'support') applied to prod 2026-07-11.** Spec+plan in
> `docs/superpowers/{specs,plans}/2026-07-11-support-*`. Suite green + build green.

> **2026-07-05 — VOICE FIRST-IMPRESSION OVERHAUL (deployed: Fly agent + master pushed).**
> (1) **Instant REAL greeting** (FIXLOG #264): canned welcome clip + outbound
> welcome_short_audio mask DELETED; the actual per-call opening (welcome +
> disclosure / greet-by-name / reminder / doctor's question) synthesizes fresh
> and streams on a temp track CONCURRENT with session.start — first audio ~1s
> after pickup (`lat_first_word`); outbound pre-synthesizes during RING.
> Greeting seeded into chat_ctx; session.say fallback speaks SAME segments
> (single source: `agent/livekit_minimal/greeting.py`).
> (2) **Per-language clinic voices** (FIXLOG #265): ONE cloned voice per
> language, upsert semantics; call-language clone always wins in
> `_voice_for_lang`; catalog = RULE 8 fallback only. Settings "Clinic voices"
> card with in-browser mic recording (`frontend/src/lib/recorder.js`).
> (3) **Loudness** (FIXLOG #266): peak normalization on both TTS paths;
> A/B voice samples in `sandbox/tts-shootout/samples` — ⏳ Vinay to pick
> default voice. (4) **Turn latency** (FIXLOG #267): measured breakdown
> EOU 1.12–1.35s + Gemini ttft 1.46–1.78s + TTS ttfb 0.34–0.65s; `lat_eou`
> now logs `transcription_delay` to attribute the EOU overshoot — next real
> call decides the one targeted change. Suite: **616 passed, 2 skipped**.
> ⚠ Next real call: verify `lat_first_word` <2s + read new lat_eou fields.

> **2026-06-15 (late) — TTS PROVIDER SWITCH.** Replaced Sarvam Bulbul TTS with
> **smallest.ai Waves Lightning v3.1** (STT stays Sarvam Saaras). Per-clinic voice
> from the smallest catalog (`GET /branches/{id}/voices`) + **voice cloning**
> (`POST/DELETE /branches/{id}/voice-clone`, org_admin). smallest's language codes
> match our `Branch.language` codes (all 8 incl Bengali+Odia verified live).
> `branches.tts_voice` is now a nullable smallest voice_id (NULL→language default
> voice: padmaja for te/ta/kn/ml, niharika for hi/mr/bn/or). **Alembic head now
> `n10smallestvoice2026`.** Needs `SMALLEST_API_KEY`. 445 tests pass. ⚠ live voice
> cloning UNVERIFIED — SDK clone path is server-deprecated (TD-027); TTS + catalog
> are live-proven. ROTATE the smallest key (pasted in chat). FIXLOG #127.
>
> **2026-06-15 — LATEST.** This session: (1) removed the smallest.ai TTS trial →
> **Sarvam-only**; (2) **signup reworked to email + password + EMAIL OTP**, mobile
> dropped, password now needs lower+upper+digit+special (matches the new image);
> (3) **market repositioned Hyderabad → all-India** (legal jurisdiction kept);
> (4) favicon updated; (5) **multilingual voice agent** — a clinic picks its
> language in Settings (te/hi/ta/kn/ml/mr/bn/or); `Branch.language` drives Sarvam
> STT/TTS codes + per-language spoken lines (`agent/i18n`) + a PRIMARY-LANGUAGE
> prompt directive. **Telugu validated; the other 7 are first-pass, flagged**
> (`docs/multilingual_lines_review.md`). Also built the **per-clinic Vobiz
> sub-account credential seam** (concurrency isolation): per-branch SIP creds
> (encrypted at rest) + per-clinic outbound trunk + `/branches/{id}/telephony`;
> outbound jobs/agent dial the per-clinic trunk, falling back to the global
> account. Needs **`FIELD_ENCRYPTION_KEY`** in prod. ⚠ Vobiz-API auto-provisioning
> of sub-accounts deferred (partner-API capability TBD — TECH_DEBT); creds manual.
> **Alembic head now `m9subacct2026`** (run `alembic upgrade head` before deploy —
> adds `branches.language` + the Vobiz sub-account columns). Test suite:
> **446 passing** (2 pre-existing seed_phase1 env failures unrelated). FIXLOG #122–126.
>
> **2026-06-13 — (everything below this block is historical and stale).**
>
> **All code phases are built**: voice agent (LiveKit), backend (auth, queue, doctors,
> availability, branches/settings, analytics, admin console, payments+webhook), jobs
> (calendar writer, reminders, cascade rebook, trial pause, stale-call reconcile),
> React PWA (login, queue, walk-in, doctor schedule, settings, admin, availability),
> and the full DPDP/security layer. **Test suite: ~400 passing.**
>
> **Launch status:** code-complete; blocked only on external accounts + one real-call
> validation. See **[`docs/GO_LIVE.md`](GO_LIVE.md)** for the exact split of what's done
> vs what Vinay must do (Razorpay live, Vobiz/LiveKit wiring, secrets, deploy, test call).
>
> Recent work history: **[`docs/FIXLOG.md`](FIXLOG.md)** (#1-94) and **[`docs/TECH_DEBT.md`](TECH_DEBT.md)**.
> Five bug-bounty rounds + a go-live sprint closed payments billing, metering durability,
> cancel-status split, calendar resync, recording hard-off, non-root containers.
>
> Alembic head: `j6cancelpatient2026`.

---

**Last updated:** 2026-06-06 (Phase 1 code complete, blocked on Vobiz KYC) — STALE, see block above
**Active phase:** Phase 1 — Voice Agent Core (code complete, pending real-call validation)
**Reliability posture:** MVP-launch (~99.4% uptime target). Phase 11 deferred until volume / outage / customer trigger fires. See [`docs/phases/11-reliability-hardening/CLAUDE.md`](phases/11-reliability-hardening/CLAUDE.md).

Read this at the start of every session. It tells you what's real, what's broken, what's next. If anything here contradicts an older doc, this file wins.

Also check [`docs/CHANGELOG.md`](CHANGELOG.md) for session-by-session decision history and [`docs/TECH_DEBT.md`](TECH_DEBT.md) for the shortcut ledger.

---

## ✅ PHASE 4.5 CLOSED — 2026-06-05

Security and Compliance sprint complete. 18 spec acceptance criteria: **14 GREEN + 3 MANUAL-VERIFICATION + 1 DEFERRED** (Shannon AI scan deferred to Phase 3 exit gate).

**Results summary:**
- JWT auth + jti revocation, fastapi-limiter rate limits, SecurityHeadersMiddleware, CORS exact-origin, audit_log table + @audit decorator with PII denylist, secrets-in-repo test, GitHub Actions CI + Dependabot, Cloudflare deploy runbook (Tasks 1-10, 14-16).
- Privacy policy + ToS + DPA + breach runbook + DSAR runbook (Tasks 11+13). /privacy /terms /dpa public HTML routes (Task 12).
- Voice agent Step 0 disclosure on call start (DPDP s.5 compliance).
- ZAP baseline CI workflow (PR + nightly) + 4 legal-routes coverage tests (Task 17a).
- Vobiz LiveKit provisioning script + agent_name fix (adjacent Phase 1+5 critical path).

**Test gate:** 155 passed + 1 skip. Zero regressions.

**Closed debts this sprint:** TD-015 (CI), TD-019 (FK ondelete), TD-022 (PII denylist). **Opened:** TD-026, TD-027, TD-028, TD-029.

---

## NEXT: Phase 1 — Voice Agent Core (code complete, pending real-call validation)

Phase 1 code is complete. Six dispatches shipped today (D1-D4, D-Emergency, D-Cleanup):
- D1: Win asyncio + dotenv + structlog JSON bootstrap (`20869d6`)
- D2: Alembic verified + seed_phase1.py with idempotency (`e7745d3`)
- D3: CalendarService stub + MetaService stub + audit_log voice hooks (`156b483`)
- D4: Strip silence/audio (-655 LOC) + DID resolution + tool registration (`ad4bd7f`)
- D-Emergency: SIP transfer on emergency keyword (`d0eb08e`)
- D-Cleanup: TD-031..036 + DISPATCHES backfill + STATUS update (this commit)

Smoke test green: agent boots, registers as `voice-assistant`, 96/96 unit tests pass.

### BLOCKED on Vobiz KYC (4-24h wait)

First inbound call blocked on Vobiz account activation. Diagnosed root cause: `is_verified=false` + DID `provider=""` + recycled number (released April, repurchased June). Support ticket prepared. Waiting 4-24h for Vobiz to complete KYC verification and assign DID provider.

### Resume path (after Vobiz activates)

1. First inbound test call (phone -> Vobiz DID -> LiveKit SIP -> agent answers)
2. First outbound test (SIP REFER on emergency keyword)
3. Phase 1 close (STATUS + CHANGELOG + DISPATCHES update)
4. Next phase: Phase 2 backend gaps OR Phase 3 frontend (Vinay's call after Phase 1 closes)

### Other blockers (not blocking Phase 1 close)

- **Fly.io firewall ports** — Fly.io Mumbai VM needs ports 5060/UDP (SIP) + 10000-60000/UDP (RTP) opened for inbound calls. Phase 10 deploy prep.
- **Anthropic API key for Shannon** — must be in `.env` as `ANTHROPIC_API_KEY` by end of Phase 3. Shannon scan is Phase 3 exit gate (TD-029).

---

## ✅ PHASE 4 COMPLETE — 2026-06-01

All 7 tasks shipped. `backend/main.py` boots, `/health` → 200, `/queue/{branch}/today` requires JWT, `POST /api/create-order` creates real Razorpay orders.

- ✅ Task 1: Alembic migration regenerated (`ffcf1134aa8f`) — 10 tables applied
- ✅ Task 2: `init_db()` helper added to `backend/database.py`
- ✅ Task 3: JWT auth middleware + branch_guard + admin guard
- ✅ Task 4: `POST /auth/google`, `GET /auth/me`, `POST /auth/logout`
- ✅ Task 5: `GET /queue/{branch_id}/today`, `PATCH .../attend`, `PATCH .../no-show` + 9 new tests (6 auth + 3 isolation)
- ✅ Task 6: `backend/main.py` with CORS, routers, landing mount, /health, prod-disabled /docs
- ✅ Task 7: Retired `backend/payments_test_app.py` (TD-002 closed)

Closed debts: TD-001, TD-002. Still open: TD-005, TD-014, TD-018, TD-020, TD-021.

---

## ✅ FIX SPRINT COMPLETE — 2026-05-29

Per the 2026-05-29 full-project audit (produced TD-007..TD-013). Closed 7 tech debt items:

- ✅ TD-007 P0 — Replaced `_llm_with_fallback` with built-in `livekit.agents.llm.FallbackAdapter`
- ✅ TD-008 P0 — `session.disconnect()` → `session.aclose()`
- ✅ TD-009 P1 — Added `_solo_cap_watchdog` background polling task
- ✅ TD-010 P2 — Concurrency test N=5 → N=100 + limit-boundary variant
- ✅ TD-011 P3 — conftest uses `settings.redis_url`
- ✅ TD-012 P2 — conftest pre-flushes Redis
- ✅ TD-013 P2 — 8 obsolete docs archived to `docs/_legacy/`

Voice agent ready for Phase 5 telephony enablement. Test suite below tester.md bar fixed.

## Open tech debt (carry into Phase 4 / 4.5 / 9 / 10)

**P1 (high):**
- TD-015 — No CI / secret-scan job → Phase 4.5

**P2 (medium):**
- TD-014 — Dockerfiles run as root → fix before Phase 10
- TD-018 — Initial migration has zero non-unique indexes → 2nd migration before Phase 5
- TD-020 — Pre-cached greeting WAV not yet published via LiveKit track-publish API → Phase 10
- TD-021 — STT confidence threshold (Layer A) not wired (LiveKit abstraction); Layer B active → Phase 10

**P3 (low):**
- TD-005 — Romanized `padipōyāḍu` vs Telugu script → verify in Phase 10 acceptance
- TD-019 — FKs default to NO ACTION ondelete (should be explicit RESTRICT/CASCADE) → Phase 4.5

**Recently closed (2026-05-29 + 2026-06-01):** TD-003 + TD-004 (pricing), TD-006 (test suite green), TD-016 + TD-017 (event-loop bugs), TD-001 (Alembic migration regenerated), **TD-002 (payments_test_app deleted; main.py mounts payments router)**

## Test baseline (verified 2026-06-01)

`pytest tests/ -v` against Docker Postgres 16 + Redis 7 + Python 3.14 → **77/77 pass** (60 unit + 4 integration + 5 edge-case + 8 security-prep). Baseline locked.

---

## What works right now (verified end-to-end)

| Component | Status | Where |
|---|---|---|
| Voice agent: TTS sanitizer | 11/11 tests pass | [agent/services/tts_sanitizer.py](../agent/services/tts_sanitizer.py) |
| Voice agent: human transfer (intent-based — explicit ask or persistent intent; keyword module removed 2026-06-07) | LLM prompt + transfer tool | [agent/bot.py](../agent/bot.py) |
| Voice agent: session state, system prompt | manual review | [agent/session_state.py](../agent/session_state.py), [agent/prompts/system_prompt.py](../agent/prompts/system_prompt.py) |
| Voice agent: 4 booking tools (route, check, assign, confirm) | unit logic verified | [agent/tools/booking_tools.py](../agent/tools/booking_tools.py) |
| Voice agent: Pipecat entrypoint (Solo cap, transfer, token rollback) | live calls tested | [agent/bot.py](../agent/bot.py) |
| Razorpay Standard Checkout | order_id created against live Razorpay test API, signature verify works | [backend/routers/payments.py](../backend/routers/payments.py) |
| Razorpay test landing page | renders, all 3 plan buttons trigger checkout | [backend/static/index.html](../backend/static/index.html) (mirror of vachanam.in) |
| DB schema (10 tables: Org, Branch, Doctor, Patient, Token, Call, FollowupTask, BillingCycle, WhatsAppSession, User) | imports without error | [backend/models/schema.py](../backend/models/schema.py) |
| Alembic configured (loads URL from settings) | env.py works | [alembic/env.py](../alembic/env.py) |
| docker-compose for Postgres + Redis | starts cleanly | [docker-compose.yml](../docker-compose.yml) |

---

## What's broken or unverified

| Issue | Severity | Fix-where |
|---|---|---|
| `alembic/versions/2fe8f201bc31_initial_schema.py` was generated 2026-05-15, **before** the schema additions on 2026-05-22 (User model, Branch.meta_phone_number_id, Token timestamps, FollowupTask channel). Needs a follow-up migration. | HIGH | Phase 4 task |
| Tests have not been executed in this session — Docker likely not running, DB not migrated | HIGH | Phase 4 first acceptance check |
| `backend/main.py` does not exist. Razorpay router lives only inside the standalone `payments_test_app.py` | HIGH | Phase 4 main task |
| Razorpay test mode merchant account rejects `4111 1111 1111 1111` ("domestic cards only") and UPI tab only shows QR (collect flow disabled) | LOW (test mode quirk) | Phase 9 — enable in dashboard before live mode |
| Pricing mismatch: root `CLAUDE.md` says Solo ₹1,999 / Clinic ₹7,999 / Multi ₹16,999. Live site (`vachanam.in`) shows Starter ₹6,999 / Growth ₹9,999 / Unlimited ₹14,999. The landing page mirror uses the **live site** tiers, the master spec uses the original. | DECISION-NEEDED | Resolve before Phase 9 — see "Decisions needed" below |
| The Sarvam STT romanization of `padipōyāḍu` in emergency keywords may not match real STT output (could need Telugu script form `పడిపోయాడు`) | LOW | Phase 10 — verify with real call |

---

## Active confusion to clean up

| Confusion | Action |
|---|---|
| Multiple competing plan docs: `PHASE_0_*.md` ... `PHASE_5_*.md` at root, `docs/superpowers/plans/*.md`, `docs/vachanam-progress.md`, and now `docs/phases/`. | **NEW canonical:** `docs/phases/`. Old docs kept as historical reference only. |
| `backend/static/index.html` is a 1:1 mirror of vachanam.in serving as a Razorpay test target. It is NOT the receptionist app or the owner dashboard — those are separate frontends built in Phases 7 and 8. | Marked in [docs/phases/03-razorpay-checkout/CLAUDE.md](phases/03-razorpay-checkout/CLAUDE.md) |
| `backend/payments_test_app.py` is a temporary standalone FastAPI that hosts only the Razorpay router. It exists because `backend/main.py` doesn't yet. Phase 4 deletes it. | Marked in [docs/phases/04-backend-core/CLAUDE.md](phases/04-backend-core/CLAUDE.md) |

---

## Decisions needed (block work in later phases)

1. **Pricing tiers final answer.** Original SaaS pricing (Solo / Clinic / Multi) vs live-site pricing (Starter / Growth / Unlimited)? Whichever is canonical must be reflected in CLAUDE.md, the landing page button amounts, and the three `RAZORPAY_PLAN_*_ID` env vars.
2. **Live Razorpay account activation.** Production needs `rzp_live_*` keys, KYC, and the 3 subscription plans created in dashboard. Owner action.
3. ~~**Meta WhatsApp Business account.**~~ **DEFERRED to MVP2** (client decision 2026-06-03). Not needed for MVP1 launch. Will be required when Phase 5 WhatsApp work begins in MVP2.
4. **Vobiz SIP trunk.** Need actual `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_DID_NUMBER` from the Vobiz console before the voice agent can answer real calls.

---

## Phase map (full detail in `docs/ROADMAP.md`)

```
Phase 1   Foundation              ✅ DONE
Phase 2   Voice agent core        ✅ DONE  (tests pass, manual call needs Phases 4 + 9 to dial-in)
Phase 3   Razorpay checkout       ✅ DONE  (test mode, standalone)
Phase 4   Backend core            ✅ DONE
Phase 4.5 Security & compliance   ✅ DONE  (closed 2026-06-05)
Phase 1*  Voice agent telephony   🔨 CODE COMPLETE  ← blocked on Vobiz KYC; pending real-call validation
Phase 5   WhatsApp                🅿️ DEFERRED-MVP2 (client decision 2026-06-03)
Phase 6   Jobs + Calendar         ⬜ (MVP1 REDUCED: Calendar + token expiry only; WA jobs → MVP2)
Phase 7   Receptionist PWA        ⬜
Phase 8   Owner + Admin dashboards ⬜
Phase 9   Subscriptions + Onboarding ⬜ (email reminders, not WA; WA → MVP2)
Phase 10  Deployment              ⬜ (no Meta WA infra needed for MVP1)
🔒 Shannon scan gate — must pass 0 critical before Phase 4 onboarding work begins
```

---

## What "next session" looks like

Wait for Vobiz KYC activation (4-24h). Once activated:

1. First inbound test call — phone call to Vobiz DID, verify AI answers in Telugu
2. First outbound test — speak emergency keyword, verify SIP REFER transfer
3. Phase 1 close — update STATUS + CHANGELOG + DISPATCHES
4. Vinay decides next phase: Phase 2 backend gaps OR Phase 3 frontend

Then Phase 6 (Jobs + Calendar) begins after the chosen next phase completes.
