# Vachanam -- DPDP Gap Analysis (2026-06-04)

**Author:** privacy-legal specialist
**Baseline:** commit `a0867a3`, 132 passed / 1 skipped / 0 RED
**Scope:** Compare GPT's 13-point DPDP Healthcare Voice Agent framework against our security + compliance spec (2026-05-22, with three REVISIONS through 2026-06-02)
**MVP context:** MVP1 = voice call + token + calendar + receptionist PWA + owner dashboard + Razorpay. MVP2 = all WhatsApp features (deferred per CHANGELOG 2026-06-03).

---

## Section 1 -- Coverage Matrix

| # | GPT Item | Our Coverage | Where (spec section, code, doc) | Gap (MVP1 / MVP2 / N/A) | Priority |
|---|---|---|---|---|---|
| 1 | Data flow architecture (patient to voice agent to recording/STT/appointment/WA/CRM to dashboard to calendar) | Fully covered | Spec ss1-4 layered architecture; CLAUDE.md project structure; GRAPH_REPORT.md 402-node AST | N/A | -- |
| 2 | Role definition (Clinic = Data Fiduciary; Vachanam = Data Processor; DPA contract) | Partial | Spec ss9.1 mentions "clinic is primary Data Fiduciary, Vachanam is Data Processor" in prose. No formal DPA template document exists. | MVP1 | P0 |
| 3 | Consent architecture (call-start verbal notice + consent JSON record per call; WA first-interaction consent) | Partial | Spec ss9.3 says call starts with "this call is recorded for booking purposes." System prompt (agent/prompts/system_prompt.py) does NOT include this disclosure line. No `consents` table. No consent JSON stored per call. WA consent deferred to MVP2. | MVP1 | P0 |
| 4 | Data minimization (collect only name + mobile + doctor + date/time) | Fully covered | Spec ss9.2 item 6; CLAUDE.md Rule 10 (phone[-4:] in logs); schema.py Patient table has only name + phone + followup_consent + branch_id. Calendar stores first-name + last-4 phone per spec ss9.3. | N/A | -- |
| 5 | Security architecture (AES-256 at rest, TLS 1.2+, RBAC) | Partial | Spec ss10.1 TLS 1.2+ confirmed. Spec ss7 A02 confirms Neon disk encryption at rest (Neon default, not app-managed AES-256). RBAC via JWT claims (role, branch_ids, is_admin) + branch_guard middleware. No app-level AES-256 for recordings/transcripts (field-level encryption deferred to Scale-ready posture per spec ss14). | MVP1 (see note) | P1 |
| 6 | Voice recording controls (separate storage, signed URLs, access audit) | Missing | Spec ss9.2 item 7 states "Voice call recordings: 90 days" retention. But NO recording infrastructure exists. LiveKit is NOT configured to record. Sarvam processes audio in real-time streaming (no persistent storage of audio at Sarvam). No recording storage bucket, no signed URLs, no access audit for recordings. | MVP1 (decision needed) | P0 |
| 7 | AI transcript controls (PII detection + masking for analytics; separate raw vs analytics store) | Missing | No transcript storage exists in the schema. Sarvam STT output is consumed in-memory by the LLM during the call and never persisted to any table. audio_quality.py assesses transcripts in-memory only. No PII masking service. No analytics transcript store. | MVP1 (see note) | P1 |
| 8 | Retention (recordings 180d, transcripts 180d, appointments 2yr, audit 3yr, WA 1yr) | Partial | Spec ss9.2 item 7 defines: recordings 90 days, active bookings 2 years, audit log 7 years, deleted accounts PII purge 30 days. GPT says recordings 180d vs our 90d = DIVERGENCE. GPT says audit 3yr vs our 7yr = we are stricter (OK). No `data_retention.py` job exists yet (spec ss9.3 mentions "Phase 6+ scope"). | MVP1 | P1 |
| 9 | Data subject rights portal (Request My Data / Correct / Delete / Withdraw Consent) | Partial | Spec ss9.4 defines manual DSAR process: email to hello@vachanam.in, Vinay verifies identity, runs script, 7-day SLA. No self-service portal. No `scripts/dsar.py` exists yet. Manual process is adequate for MVP1 (<20 clinics). | MVP2 (portal); MVP1 (manual process + script) | P2 |
| 10 | Breach management architecture (detection, severity, containment, notification, postmortem) | Fully covered | Spec ss11 breach response runbook: 5 steps, 6 pre-rehearsed scenarios. 72-hour notification to Data Protection Board. All pre-rehearsed scenarios cover JWT leak, account compromise, DB access leak, webhook secret leak, recording exposure, cross-tenant leak. No `docs/runbooks/breach-response.md` file EXISTS yet (spec says it should be stored there). | MVP1 (file creation) | P0 |
| 11 | Vendor compliance register (DPA + security review per vendor) | Partial | Spec ss9.2 item 6 names all 9 vendors with privacy policy links. privacy-legal.md defines the processor table. But: no per-vendor DPA signed, no security review documented, no retention-review-per-vendor. GPT lists "Twilio, AWS, OpenAI" which don't match our stack (we use Vobiz, Neon/Upstash/Fly/Render, Sarvam+Gemini). | MVP1 | P1 |
| 12 | AI governance (per-action log JSON with call_id, model, prompt_version, action, confidence, timestamp) | Missing | No `ai_decisions` table. No logging of which LLM model handled each call, what prompt version was used, what confidence scores were returned, what booking actions were taken by the LLM. audit_log captures booking actions (token.attend, etc.) but NOT the AI decision layer (which model, which prompt, confidence). | MVP1 | P1 |
| 13 | Production architecture (consent service / appointment / calendar / WA / audit / security gateway / encrypted data layer / retention engine) | Partial | We have: appointment (tokens table), calendar (Phase 6), audit (audit_log table + @audit decorator), security gateway (4-layer defense per spec ss4). We do NOT have: consent service (no consents table), retention engine (no data_retention.py job), encrypted data layer (Neon disk only, no app-level). WA deferred MVP2. | MVP1 | P1 |
| **LC-1** | Privacy Policy published | Missing (doc) | Spec ss9.2 defines all 12 sections. No `docs/legal/privacy-policy.md` file created yet. No `/privacy` endpoint serving it. Phase 4.5 Task 11 (privacy-legal dispatch) was BLOCKED pending DPDP Rules check. | MVP1 | P0 |
| **LC-2** | Terms of Service published | Missing | No `docs/legal/terms-of-service.md`. Not mentioned in security spec. | MVP1 | P0 |
| **LC-3** | Data Processing Agreement (DPA) template | Missing | No `docs/legal/data-processing-agreement.md`. Spec ss9.1 acknowledges the Fiduciary/Processor relationship but no contract template. | MVP1 | P0 |
| **LC-4** | Consent script for calls | Partial | Spec ss9.3 says call starts with "this call is recorded for booking purposes." But system_prompt.py (the actual prompt) does NOT include this line. It says "Greet the patient warmly in Telugu" as step 1 -- no recording disclosure. | MVP1 | P0 |
| **LC-5** | WA consent language | Deferred MVP2 | WhatsApp removed from MVP1 entirely (client decision 2026-06-03). | MVP2 | -- |
| **LC-6** | Audit logging | Fully covered | audit_log table (spec ss8, migration `8559268c0c44`), @audit decorator (audit_service.py, 22/22 tests), PII denylist (TD-022 closed). | N/A | -- |
| **LC-7** | Encryption at rest + transit | Partial | TLS 1.2+ in transit (spec ss10.1). Neon disk encryption at rest (vendor-managed, not app-managed AES-256). No field-level encryption. Acceptable for MVP-launch posture per spec ss14 deferred items table. | N/A (accepted risk) | -- |
| **LC-8** | RBAC | Fully covered | JWT claims (role: super_admin / org_admin / receptionist), branch_ids list, is_admin flag. branch_guard middleware. require_admin dependency. 3-layer isolation (spec ss7 A01). | N/A | -- |
| **LC-9** | Retention/deletion engine | Missing | Spec ss9.3 mentions `data_retention.py` as "Phase 6+ scope." No job exists. No automated deletion of expired data. Retention periods stated in spec ss9.2 but not enforced. | MVP1 | P1 |
| **LC-10** | DSAR workflow | Partial | Spec ss9.4 defines manual process. No `scripts/dsar.py` exists. No `docs/runbooks/dsar.md` exists. | MVP1 | P1 |
| **LC-11** | Incident response plan | Fully covered (spec) | Spec ss11 is comprehensive. But the file `docs/runbooks/breach-response.md` does not exist yet -- the runbook is embedded in the spec only. | MVP1 (extract to file) | P0 |
| **LC-12** | Vendor register document | Partial | Processor list is in spec ss9.2 item 6 and privacy-legal.md. No standalone `docs/compliance/third-party-processors.md` file exists. No per-vendor DPA status tracked. | MVP1 | P1 |
| **LC-13** | AI decision logs | Missing | Same as item 12 above. | MVP1 | P1 |

**Coverage summary:**

| Status | Count |
|---|---|
| Fully covered (no action) | 5 (items 1, 4, LC-6, LC-8, LC-11-spec) |
| Partial (need work) | 11 (items 2, 3, 5, 8, 9, 11, 13, LC-4, LC-7, LC-10, LC-12) |
| Missing for MVP1 | 7 (items 6, 7, 12, LC-1, LC-2, LC-3, LC-9) |
| Deferred MVP2 | 1 (LC-5) |
| Out of scope adjustments | 1 (item 11 vendor names -- GPT's list doesn't match our stack) |

---

## Section 2 -- Confirmed: GPT Items Already in Our Spec (No Action Needed)

**GPT Item 1 (Data Flow Architecture):** Our spec ss4 documents the 4-layer architecture (Edge, App, Route, Data) with a clear diagram. GRAPH_REPORT.md (graphify AST, 402 nodes, 1006 edges) maps every data flow from patient call through agent to backend to DB. CLAUDE.md project structure is the canonical file tree. Coverage is complete.

**GPT Item 4 (Data Minimization):** Our spec ss9.3 purpose-limitation row states "Data used only for booking + analytics shown to the owning clinic; never sold; never used to train AI models on patient data." CLAUDE.md Rule 10 mandates `phone[-4:]` in all logs. Schema.py Patient table collects only: name, phone, followup_consent, branch_id. Calendar events store first-name + last-4 digits only (spec ss9.3 data-minimization row). No Aadhaar, PAN, address, or medical history collected anywhere. This exceeds GPT's recommendation.

**GPT Item 10 (Breach Management):** Our spec ss11 covers all 5 steps GPT recommends (detect, assess severity, contain, notify, postmortem) plus 6 pre-rehearsed scenarios. Our 72-hour notification matches DPDP Act s.11. Our spec adds quarterly tabletop drill (spec ss12.3) which GPT does not mention. Our coverage is strictly better.

**LC-6 (Audit Logging):** audit_log table exists (migration `8559268c0c44`), @audit decorator exists (audit_service.py), PII denylist enforcement exists (TD-022 closed, 22/22 tests GREEN), append-only enforcement planned for Phase 10 prod-init (TD-023). Coverage is complete for MVP-launch posture.

**LC-8 (RBAC):** JWT claims carry role (super_admin / org_admin / receptionist), branch_ids list, is_admin flag. branch_guard middleware enforces at Layer 3. require_admin dependency gates admin routes. 3-layer isolation (middleware + JWT + DB WHERE) per spec ss7 A01. GPT's "clinic admin / doctor / receptionist / support engineer / platform admin" maps cleanly to our role model.

**LC-7 (Encryption at rest + transit):** TLS 1.2+ confirmed (spec ss10.1). Neon provides AES-256 disk encryption by default. This is vendor-managed, not application-managed -- but spec ss14 explicitly accepts this trade-off for MVP-launch posture and documents the upgrade path to field-level encryption at Scale-ready posture (~50 clinics). GPT recommends "managed cloud KMS" which is what Neon provides. No gap for MVP-launch.

**Retention divergence flagged (GPT Item 8 vs our spec ss9.2 item 7):**

| Data type | GPT says | Our spec says | Resolution |
|---|---|---|---|
| Call recordings | 180 days | 90 days | We are STRICTER (shorter retention = less data at risk). Our 90 days is defensible. No action needed unless clinic contracts require 180 days. |
| Appointment records | 2 years | 2 years | Match. |
| Audit logs | 3 years | 7 years | We are STRICTER. 7 years aligns with Indian medical record norms even though we don't store medical records. Conservative default is correct. |
| WhatsApp logs | 1 year | Not yet defined (WA deferred MVP2) | Will define when Phase 5 begins. |

---

## Section 3 -- Critical Gaps for MVP1 (Must Address Before First Paying Clinic)

### Gap 3.1 -- Missing Privacy Policy, Terms of Service, and DPA Template

**WHAT:** No `docs/legal/privacy-policy.md`, `docs/legal/terms-of-service.md`, or `docs/legal/data-processing-agreement.md` exists. Spec ss9.2 defines the 12-section structure for the privacy policy but the document has not been authored. The DPA (contract between Vachanam-as-processor and clinic-as-fiduciary) does not exist at all.

**WHY (DPDP risk):** DPDP Act s.5 requires notice to data principals BEFORE processing their data. s.6 requires "free consent" based on that notice. Without a published privacy policy, the first patient whose data we process has a valid complaint to the Data Protection Board. Without a DPA, the clinic has no contractual assurance that we process data only on their instructions (s.8 requirement for processors).

**WHERE TO ADD:**
- Privacy policy: `docs/legal/privacy-policy.md` (12 sections per spec ss9.2) + rendered at `app.vachanam.in/privacy`
- Terms of Service: `docs/legal/terms-of-service.md`
- DPA template: `docs/legal/data-processing-agreement.md` (clinic signs during onboarding, Phase 9)

**WHO:** privacy-legal (this specialist) authors all three documents. frontend-engineer renders at `/privacy` and `/terms`. backend-engineer links from signup flow.

**COST:** Medium (3-4 hours privacy-legal for all three documents).

**BLOCK vs SOFT:** HARD BLOCK. Cannot accept first paying clinic without a published privacy policy and a signed DPA. This is a legal requirement, not a nice-to-have.

---

### Gap 3.2 -- Missing Consent Record Architecture

**WHAT:** Spec ss9.3 says the call starts with "this call is recorded for booking purposes." But:
1. The actual system prompt (`agent/prompts/system_prompt.py` line 59: "Greet the patient warmly in Telugu") does NOT include any recording disclosure.
2. No `consents` table exists in the database schema.
3. No consent JSON is stored per call (call_id, notice_version, timestamp, consent_type).
4. The `Patient.followup_consent` boolean in schema.py is a start but only covers follow-up calls, not recording consent or data-processing consent.

**WHY (DPDP risk):** DPDP Act s.6 requires "free consent" that is "specific, informed, unconditional, and unambiguous." If we record calls (see Gap 3.3 below), verbal disclosure is the minimum. Even if we do NOT record calls, we still process personal data (name, phone, complaint summary) -- consent notice is required. Without a stored consent record, we cannot demonstrate to a regulator that consent was obtained.

**WHERE TO ADD:**
- System prompt: add recording/data-processing disclosure as step 0 (before greeting)
- Schema: add `consents` table with columns: id (UUID), call_id (FK to calls), patient_phone (String), consent_type (ENUM: recording, data_processing, followup), notice_version (String), timestamp (DateTime), method (ENUM: verbal, written, whatsapp)
- Agent code: insert consent row at call start after verbal disclosure plays
- Migration: Alembic migration for new table

**WHO:** privacy-legal writes the consent script text and the table spec. database-engineer creates migration. voice-agent-engineer wires the disclosure into agent.py. backend-engineer adds the insert endpoint.

**COST:** Medium (consent text: 1 hour privacy-legal; table + migration: 1 hour database-engineer; agent wiring: 1 hour voice-agent-engineer; endpoint: 1 hour backend-engineer).

**BLOCK vs SOFT:** HARD BLOCK. Cannot process patient data without demonstrable consent mechanism. The consent TABLE can be a Phase 6 add (before first clinic goes live), but the verbal disclosure script must be in the system prompt NOW.

---

### Gap 3.3 -- Recording Policy Decision Needed

**WHAT:** Our spec ss9.2 item 7 states "Voice call recordings: 90 days" retention. Our spec ss9.3 says the call starts with "this call is recorded." But:
1. LiveKit is NOT configured to record calls (no `egress` service, no room recording, no S3/GCS bucket).
2. Sarvam processes audio via real-time WebSocket streaming -- audio is consumed in-flight and NOT stored by Sarvam.
3. No call recording infrastructure exists anywhere in the codebase.
4. The system prompt says "Greet the patient warmly" -- no recording disclosure.

The spec ASSUMES we record. The code does NOT record. This is a contradiction that must be resolved before launch.

**WHY (DPDP risk):** Two risks:
- If we DO record without telling patients: violation of s.5 (notice) and s.6 (consent). Potential criminal liability under Indian Telegraph Act s.22 (wiretapping without disclosure).
- If we do NOT record but our privacy policy SAYS we record: misleading notice. Less severe but still a compliance defect.

**OPEN QUESTION FOR CLIENT:** Are we recording calls for MVP1? This is a business decision, not a technical one.

- **Option A (DO NOT RECORD for MVP1):** Remove "call recordings: 90 days" from the privacy policy retention table. Remove "this call is recorded" disclosure from call script. Add "Call recording may be enabled in future versions with notice" to the policy. Simplest. No storage cost. No recording infrastructure to build.
- **Option B (RECORD for MVP1):** Configure LiveKit Egress to record to a cloud storage bucket (Fly volumes or external S3-compatible). Build signed-URL access. Build access audit. Build 90-day auto-deletion job. Significant infrastructure work (2-3 days devops + backend).

**Recommendation:** Option A for MVP1. Recording adds significant infrastructure cost and compliance surface (GPT Item 6 -- storage bucket, signed URLs, access audit, 90-day deletion job). The core product value is booking, not recording. Recordings can be added in MVP2 with proper infrastructure.

**WHERE TO ADD:** If Option A: update spec ss9.2 retention table to remove recordings row; update spec ss9.3 to remove "this call is recorded" from consent script; privacy policy omits recordings. If Option B: new spec section ss9.5 "Recording Architecture" per GPT Item 6.

**WHO:** Client decides Option A or B. privacy-legal updates spec and policy accordingly.

**COST:** Option A = low (doc updates only). Option B = high (2-3 days devops + backend + privacy-legal).

**BLOCK vs SOFT:** HARD BLOCK on the DECISION. The contradiction between spec ("we record") and code ("we don't record") must be resolved. Either way, the privacy policy and consent script must be consistent with reality.

---

### Gap 3.4 -- Breach Response Runbook Not Extracted to File

**WHAT:** Spec ss11 contains a comprehensive breach response runbook (5 steps, 6 scenarios). But the file `docs/runbooks/breach-response.md` does not exist. The runbook lives ONLY in the security spec. Phase 4.5 acceptance criteria (spec ss15 line 13) requires "Breach response runbook saved at docs/runbooks/breach-response.md."

**WHY:** In a real breach at 2 AM, Vinay needs to open ONE file and follow the steps. Searching through a 835-line security spec under stress is unacceptable. The runbook must be a standalone document.

**WHERE TO ADD:** `docs/runbooks/breach-response.md` -- extract spec ss11 verbatim, add quick-reference header with emergency contacts.

**WHO:** privacy-legal authors the standalone file.

**COST:** Low (1 hour -- mostly extraction from spec ss11 + adding quick-reference header).

**BLOCK vs SOFT:** SOFT BLOCK. The content exists in the spec. Extracting to a file is a usability improvement. Can ship with the spec as the reference, but should be done before first clinic goes live.

---

### Gap 3.5 -- Consent Script Not in System Prompt

**WHAT:** The system prompt (`agent/prompts/system_prompt.py`) instructs the AI to "Greet the patient warmly in Telugu" as step 1. There is no step 0 for recording disclosure or data-processing notice.

Even if we choose Option A (no recording) from Gap 3.3, we still need a data-processing disclosure: "This call is handled by an AI assistant. Your name and phone number will be used to book your appointment."

**WHY (DPDP risk):** DPDP Act s.5 requires notice BEFORE processing. The call IS the processing event. Notice must come at the start of the call, not buried in a website privacy policy the patient has never seen.

**WHERE TO ADD:** `agent/prompts/system_prompt.py` -- add step 0 before the greeting. Text options:
- If recording: "idi record avutundi. mee appointment kosam mee peru mariyu phone number vadatamu." (This is being recorded. We will use your name and phone number for your appointment.)
- If NOT recording: "idi AI assistant. mee appointment kosam mee peru mariyu phone number vadatamu." (This is an AI assistant. We will use your name and phone number for your appointment.)

**WHO:** privacy-legal writes the Telugu/Hindi/English consent text. voice-agent-engineer adds it to system_prompt.py.

**COST:** Low (30 min privacy-legal for text; 30 min voice-agent-engineer to add step 0).

**BLOCK vs SOFT:** HARD BLOCK. No data processing without notice. This must be in the system prompt before first live call.

---

### Gap 3.6 -- DSAR Runbook and Script Missing

**WHAT:** Spec ss9.4 defines a manual DSAR process but:
1. No `docs/runbooks/dsar.md` file exists.
2. No `scripts/dsar.py` script exists.
3. The manual process is described only in the spec.

**WHY (DPDP risk):** DPDP Act s.11-13 gives data principals the right to access, correct, and erase their data. Our spec commits to a 7-day SLA. Without a runbook and script, the first DSAR request will be handled ad-hoc, risking SLA breach and inconsistent execution.

**WHERE TO ADD:**
- `docs/runbooks/dsar.md` -- step-by-step process for Vinay
- `scripts/dsar.py` -- CLI tool to query/export/delete patient data by phone number + branch_id

**WHO:** privacy-legal authors the runbook. backend-engineer creates the script.

**COST:** Medium (1 hour privacy-legal for runbook; 2 hours backend-engineer for script).

**BLOCK vs SOFT:** SOFT BLOCK. DSAR requests are unlikely in the first month with <5 clinics. But the 7-day SLA commitment in the privacy policy means we need the process documented before the policy goes live.

---

## Section 4 -- MVP2 Gaps (Add Later)

### 4.1 -- WhatsApp Consent Storage (GPT Item 3, WA portion)

When Phase 5 (WhatsApp) ships in MVP2, we need:
- First-interaction text message: "You are receiving booking confirmations from [Clinic Name] via Vachanam. Reply STOP to opt out."
- Consent record stored: patient_id, timestamp, channel=whatsapp, notice_version, opted_in=true
- STOP handler that sets opted_in=false and immediately stops all WA messages to that patient
- `consents` table row per WA interaction (can reuse the same table from Gap 3.2)

**WHO:** privacy-legal writes WA consent text. backend-engineer builds STOP handler. database-engineer extends consents table if needed.

### 4.2 -- DSAR Self-Service Portal (GPT Item 9)

Manual DSAR process is adequate for <20 clinics. When patient volume exceeds ~10 DSAR requests/month, build a self-service portal:
- Patient enters phone number, receives OTP
- After verification: "Download My Data" / "Correct My Data" / "Delete My Data" / "Withdraw Consent"
- Backend processes request, returns JSON export or confirmation
- Audit log entry for every DSAR action

**WHO:** frontend-engineer builds the portal page. backend-engineer builds the API. privacy-legal writes the user-facing text.

### 4.3 -- WhatsApp Vendor DPA (Meta)

When WhatsApp is enabled in MVP2, Meta becomes an active data processor. Requires:
- Update third-party processors list
- Review Meta's DPA (standard Meta Business Data Processing Terms)
- Document retention alignment (Meta retains messages per their policy; our policy must state this)
- Update privacy policy section 6 (third-party processors)

### 4.4 -- PII Masking Service for Transcripts (GPT Item 7)

Only relevant IF we start persisting transcripts (currently we do not). If a future analytics feature requires transcript storage:
- Build a PII detection + masking pipeline: phone numbers, names, addresses replaced with [PHONE], [NAME], [ADDRESS]
- Separate raw transcript store (encrypted, 90-day TTL) from analytics store (PII-masked, longer retention)
- Access audit on raw transcript store

This is NOT needed for MVP1 because we do not store transcripts at all.

---

## Section 5 -- Items GPT Raises That Are Out of Scope for Us

### 5.1 -- "AWS storage" (GPT Items 6, 13)

GPT assumes AWS S3 for recording storage. We do not use AWS. Our infrastructure is:
- Database: Neon Postgres (Singapore)
- Cache: Upstash Redis (Mumbai)
- Voice agent: Fly.io (Mumbai)
- Backend: Render (Singapore)
- Frontend: Cloudflare Pages (global CDN)

If we enable recordings (Option B), we would use Fly Volumes (attached to the voice agent VM in Mumbai) or a Cloudflare R2 bucket (S3-compatible, India-proximate, no egress fees). NOT AWS S3.

### 5.2 -- "Twilio voice" (GPT Item 11)

GPT lists Twilio as a voice vendor. We use Vobiz SIP + LiveKit, not Twilio. Vobiz is an Indian telephony provider with data residency in India. This is actually a DPDP ADVANTAGE: voice data never leaves India. Twilio routes through US/EU infrastructure.

### 5.3 -- "OpenAI transcripts" (GPT Item 7, 11, 12)

GPT lists OpenAI as the transcript processor. We use Sarvam AI (Indian company, data processed in India) for STT/TTS and Google Gemini 2.5 Flash (primary LLM) with GPT-4o mini as fallback only. Sarvam's India-based processing is a DPDP advantage for data residency. OpenAI is only the FALLBACK LLM, not the STT provider.

### 5.4 -- "CRM" (GPT Item 1)

GPT mentions CRM in the data flow. We do not have a CRM. Patient data lives in our Postgres database (patients table). There is no Salesforce, HubSpot, or similar external CRM.

---

## Section 6 -- Concrete Next-Action Recommendations (Ranked)

These are the dispatches the manager should queue. Written so a clinic owner without a lawyer can understand what we are doing and why.

### Priority 0 (Must complete before first paying clinic)

**Action 1: Decide the recording question.**
- Client (Vinay) must decide: Do we record voice calls for MVP1?
- If NO (recommended): spec and privacy policy say "no recording" and we avoid building recording infrastructure.
- If YES: we need 2-3 days of infrastructure work (storage bucket, signed URLs, access audit, deletion job).
- This decision unblocks Actions 2 and 3.
- Target: immediate (client decision, no engineering).
- Blocking: YES -- privacy policy text depends on this answer.

**Action 2: Author Privacy Policy + Terms of Service + DPA template.**
- Dispatch: privacy-legal
- Scope: write `docs/legal/privacy-policy.md` (12 sections per spec ss9.2), `docs/legal/terms-of-service.md`, `docs/legal/data-processing-agreement.md`
- Depends on: Action 1 (recording decision)
- Estimated effort: 3-4 hours privacy-legal
- Target sprint: Phase 4.5 remaining tasks (this sprint)
- Blocking client decision: YES (recording policy from Action 1)

**Action 3: Write call-start consent/disclosure script.**
- Dispatch: privacy-legal writes text, voice-agent-engineer adds to system_prompt.py
- Scope: add step 0 to system prompt with recording disclosure (if recording) or AI-assistant disclosure (if not recording) + data-processing notice
- Depends on: Action 1 (recording decision)
- Estimated effort: 1 hour total
- Target sprint: Phase 4.5 (this sprint)
- Blocking client decision: YES (recording policy from Action 1)

**Action 4: Extract breach response runbook to standalone file.**
- Dispatch: privacy-legal
- Scope: extract spec ss11 to `docs/runbooks/breach-response.md` with quick-reference header
- Depends on: nothing
- Estimated effort: 1 hour
- Target sprint: Phase 4.5 (this sprint)
- Blocking client decision: NO

### Priority 1 (Should complete before first paying clinic; can ship with known gap + immediate follow-up)

**Action 5: Create `consents` table + migration.**
- Dispatch: database-engineer creates migration; backend-engineer creates insert endpoint
- Scope: new `consents` table (id, call_id, patient_phone, consent_type, notice_version, timestamp, method)
- Depends on: Action 3 (consent text finalized)
- Estimated effort: 2 hours (database-engineer + backend-engineer)
- Target sprint: Phase 6 (before first clinic go-live)
- Blocking client decision: NO

**Action 6: Add AI decision audit logging.**
- Dispatch: database-engineer creates table/migration; voice-agent-engineer adds logging to agent.py
- Scope: new `ai_decisions` table OR fold into audit_log with action="ai.decision" and metadata_json containing {call_id, model_used, prompt_version, action, confidence, timestamp}
- Recommended approach: fold into existing audit_log table. The audit_log already has metadata_json (JSONB), action (String), and timestamp. Adding a new action prefix "ai." is cleaner than a separate table. The PII denylist (TD-022) already prevents patient data from leaking into metadata_json.
- Estimated effort: 2 hours (voice-agent-engineer to add structlog + audit_log writes to agent.py at key decision points)
- Target sprint: Phase 6 or Phase 10 (before production go-live)
- Blocking client decision: NO

**Action 7: Author DSAR runbook + create placeholder DSAR script.**
- Dispatch: privacy-legal writes `docs/runbooks/dsar.md`; backend-engineer creates `scripts/dsar.py` (CLI tool)
- Estimated effort: 3 hours total
- Target sprint: Phase 9 (before onboarding first clinic)
- Blocking client decision: NO

**Action 8: Create standalone vendor compliance register.**
- Dispatch: privacy-legal
- Scope: `docs/compliance/third-party-processors.md` with per-vendor columns: vendor name, what they process, data location, their privacy policy URL, DPA status (signed/pending/not-required), retention alignment status, last security review date
- Estimated effort: 1 hour
- Target sprint: Phase 4.5 (this sprint)
- Blocking client decision: NO

**Action 9: Create `data_retention.py` job specification.**
- Dispatch: privacy-legal writes the spec (which data types, which retention periods, which deletion method); backend-engineer implements in Phase 6
- Scope: spec document for the daily retention enforcement job
- Estimated effort: 1 hour (spec only; implementation is Phase 6)
- Target sprint: spec in Phase 4.5; implementation in Phase 6
- Blocking client decision: YES (recording decision from Action 1 affects whether recordings are in scope)

### Priority 2 (MVP2 or later)

**Action 10: WhatsApp consent storage + STOP handler.** Target: MVP2 Phase 5.

**Action 11: DSAR self-service portal.** Target: post-MVP2 when DSAR volume exceeds 10/month.

**Action 12: PII masking service for transcripts.** Target: only if/when we start persisting transcripts.

---

## Section 7 -- Spec Amendments Needed

The security + compliance spec (`docs/superpowers/specs/2026-05-22-security-hardening-design.md`) needs these amendments based on this gap analysis:

### Amendment 1: ss9.1 -- Explicitly state fiduciary/processor roles

Add after the current ss9.1 second paragraph:

> **Formal role classification under DPDP Act 2023:**
> - **Data Fiduciary:** the clinic (Organization entity in our system). They determine the purpose of processing (booking appointments for their patients).
> - **Data Processor:** Vachanam. We process personal data solely on the clinic's documented instructions per a Data Processing Agreement signed during onboarding.
> - **Data Principal:** the patient. They have rights under DPDP ss11-13 (access, correction, erasure, grievance).

### Amendment 2: ss9.2 item 7 -- Align retention table with recording decision

If Option A (no recording): Remove "Voice call recordings: 90 days" row. Add footnote: "Call recording may be enabled in a future version with appropriate notice and consent."

If Option B (recording): Keep 90 days. Add reference to new ss9.5 Recording Architecture.

### Amendment 3: ss9.3 -- Add consent architecture subsection

Add new subsection ss9.3a "Consent Architecture":

> **Per-call consent record:** Every inbound voice call starts with a verbal disclosure (Step 0 of the system prompt). The AI agent says: "[disclosure text -- see Gap 3.5]". A `consents` table row is inserted with: call_id, patient_phone, consent_type='data_processing' (or 'recording' if recording enabled), notice_version='1.0', timestamp, method='verbal'.
>
> **Follow-up consent:** Asked explicitly during booking flow (Step 7 of system prompt): "Can we call you for a follow-up?" Stored as Patient.followup_consent (existing field) AND consents table row with consent_type='followup'.
>
> **WhatsApp consent (MVP2):** First WA message includes opt-in disclosure. Reply STOP triggers opt-out. Stored in consents table with consent_type='whatsapp', method='written'.

### Amendment 4: Add ss9.5 "AI Decision Audit"

> **AI decision logging:** Every call where the AI agent takes a booking action logs to audit_log with:
> - action: `ai.model_selected`, `ai.doctor_routed`, `ai.token_assigned`, `ai.booking_confirmed`, `ai.emergency_detected`
> - metadata_json: `{"call_id": "...", "model": "gemini-2.5-flash|gpt-4o-mini", "prompt_version": "1.0", "confidence": 0.95, "action_detail": "routed to Dr. X based on keyword match"}`
>
> This enables regulator inquiries ("show me all AI decisions for this patient's call") and internal quality audits ("which calls used the fallback LLM?").

### Amendment 5: ss11 -- Add recording incident scenario (if recordings enabled)

If Option B: add to spec ss11.2 scenarios table:
> | Voice recording exposed via misconfigured storage | Revoke access, delete exposed copies, audit access log | Yes if any patient PII in recordings was accessed |

(Note: this scenario already exists in ss11.2 as the 5th pre-rehearsed scenario. Confirm it remains accurate after recording architecture is built.)

### Amendment 6: ss15 -- Update acceptance criteria

Current acceptance criteria (spec ss15) includes "Privacy policy page renders at /privacy with all 12 sections." Add:
- "Breach response runbook saved at docs/runbooks/breach-response.md (extracted from spec ss11)"
- "DSAR runbook saved at docs/runbooks/dsar.md"
- "Vendor compliance register at docs/compliance/third-party-processors.md"
- "DPA template at docs/legal/data-processing-agreement.md"
- "Call-start disclosure script present in system_prompt.py Step 0"

---

## Section 8 -- Launch Checklist Gap Assessment

| GPT Launch Checklist Item | Present? | Location | Notes |
|---|---|---|---|
| Privacy Policy | MISSING | Should be at `docs/legal/privacy-policy.md` + served at `/privacy` | Phase 4.5 Task 11 (BLOCKED on recording decision) |
| Terms of Service | MISSING | Should be at `docs/legal/terms-of-service.md` + served at `/terms` | Not in original spec; needed before accepting payment |
| DPA (Data Processing Agreement) | MISSING | Should be at `docs/legal/data-processing-agreement.md` | Clinic signs during Phase 9 onboarding |
| Consent script for calls | MISSING (from code) | Spec ss9.3 mentions it; system_prompt.py does NOT include it | Must add Step 0 to system prompt |
| WA consent language | DEFERRED MVP2 | WhatsApp removed from MVP1 (client decision 2026-06-03) | Phase 5 MVP2 |
| Audit logging | PRESENT | audit_log table, @audit decorator, 22/22 tests GREEN | TD-023 (GRANT/REVOKE) deferred to Phase 10 |
| Encryption at rest + transit | PRESENT | TLS 1.2+ (spec ss10.1) + Neon disk encryption | Field-level encryption deferred to Scale-ready |
| RBAC | PRESENT | JWT roles + branch_guard + require_admin | Working, tested |
| Retention/deletion engine | MISSING | Spec ss9.3 mentions "Phase 6+ scope" | Need spec + implementation before first clinic |
| DSAR workflow | MISSING (docs/script) | Spec ss9.4 defines process; no file or script exists | Need runbook + script |
| Incident response plan | PRESENT (in spec) | Spec ss11 | Need extraction to `docs/runbooks/breach-response.md` |
| Vendor register | PARTIAL | Spec ss9.2 item 6 + privacy-legal.md processor table | Need standalone `docs/compliance/third-party-processors.md` |
| AI decision logs | MISSING | Not in spec or code | Need spec amendment + implementation |

**Summary:** 4 of 13 items PRESENT, 2 PARTIAL, 6 MISSING, 1 DEFERRED.

---

## Section 9 -- DPDP Rules Status Note

As of this analysis (2026-06-04), the client was asked to check `meity.gov.in` for the DPDP Rules finalization status per:
- Spec ss9.3 (references "DPDP Rules" for breach notification format)
- CHANGELOG 2026-06-02 (brainstormer Pick 4 spec-staleness flag)
- Phase 4.5 Task 11 blocker entry

**If DPDP Rules are now gazetted:**
- This analysis must be updated to reflect any mandated language for:
  - Breach notification format to the Data Protection Board
  - Specific consent mechanisms required (verbal vs written vs digital)
  - Significant Data Fiduciary threshold (currently assumed ~50,000 users per spec ss9.3)
  - Specific retention periods mandated by the Rules (may override our chosen periods)
  - Children's data processing requirements (currently spec ss9.2 item 9 says parent/guardian only)
- The privacy policy, breach runbook, and DSAR runbook must incorporate the gazetted language.

**If DPDP Rules are still in consultation:**
- This analysis stands as-is.
- The privacy policy should include a forward-looking statement: "This policy will be updated to comply with the Digital Personal Data Protection Rules when finalized."
- Breach notification format follows the spec's current language (72 hours, summary of incident, scope, mitigation, contact).

**Action:** Client to confirm DPDP Rules status. privacy-legal will update this analysis and downstream documents accordingly.

---

## Appendix -- Open Questions for Client

1. **Recording decision (Gap 3.3):** Do we record voice calls for MVP1? Recommendation: NO (Option A). This unblocks the privacy policy, consent script, and retention table.

2. **DPDP Rules status:** Have the DPDP Rules been gazetted as of June 2026? This affects mandatory language in the privacy policy and breach runbook.

3. **Retention period for recordings (if recording):** Our spec says 90 days. GPT recommends 180 days. If we record, which period? Recommendation: 90 days (shorter = less risk, lower storage cost). Can be extended by clinic contract if requested.

4. **AI decision logging granularity:** Should we log every LLM turn (high volume, ~10-20 rows per call) or only booking-action decisions (low volume, 3-5 rows per call)? Recommendation: booking-action decisions only for MVP1. Full turn logging for scale-ready posture.
