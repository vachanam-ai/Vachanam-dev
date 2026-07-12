# How Vachanam Handles Your Data

**Effective date:** 2026-07-10
**Last updated:** 2026-07-12

This document walks through the complete life of your personal data inside Vachanam — from the moment you dial a clinic's number to the day the data is erased. It is the plain-language companion to our [Privacy Policy](/privacy) and describes what our software actually does, not just what we promise.

Vachanam is a **Data Processor** under the Digital Personal Data Protection (DPDP) Act 2023. The clinic you call is the **Data Fiduciary**. We process your data only to book and manage your appointment, on the clinic's documented instructions.

---

## 1. The Life of a Booking Call

### Step 1 — You dial the clinic's number

The number you dialled tells us which clinic you want. That is the ONLY thing we derive from the dialled number. Your own phone number arrives via caller ID and is used to identify your booking and greet you if you have visited before.

### Step 2 — The AI answers

Your voice is streamed in real time to our speech-recognition service. **The audio is converted to text and discarded — no voice recording is ever stored.** The text of the conversation is processed by an AI language model to understand your request. The AI is prohibited by design from giving medical advice, making diagnoses, or storing medical records.

### Step 3 — A token is reserved

When you pick a time, a token number is reserved atomically (a locking mechanism that makes double-booking impossible). The reservation lives in a temporary cache entry that **expires automatically the same day**. If your call ends without you confirming the booking, the reservation is released immediately — nothing about the un-confirmed attempt is kept.

### Step 4 — The booking is confirmed

On your explicit confirmation we store, in the clinic's own partition of our database:

| Stored | Where | Visible to |
|---|---|---|
| Your first name, phone number, age/gender if you gave them | `patients` table (one row per patient, per clinic) | Your clinic only |
| Token number, doctor, date, time | `tokens` table (one row per booking). Your spoken reason for visiting is used in-call for doctor routing and is NOT saved on this row. | Your clinic only |
| A consent record (that notice was given and you proceeded) | `consents` table | Your clinic only |
| An audit trail entry (what happened, when) | `audit_log` table (IDs only, no names) | Compliance use only |

A calendar event is created for the doctor containing **only your first name, the last 4 digits of your phone, and the token number** — never your health concern.

### Step 5 — After the call

- A text transcript of the call (audio is never kept) may be stored for up to **90 days** for call-quality monitoring. **Phone numbers are masked in the transcript before it is written.** A daily job deletes transcripts older than the window.
- A reminder call before your appointment uses your name and appointment time — nothing about your health concern is spoken in any notification.

---

## 2. Separation by Design

Every kind of data lives in its own dedicated table — patients, tokens, consents, calls, users (clinic staff), audit logs, and so on. Each row that can identify a person carries the clinic's `branch_id`, and **every read and write in the application is scoped to that clinic**. This is our RULE 1 (tenant isolation): no query, cache key, calendar event, or log line may expose one clinic's patient data to another clinic. It is enforced in code and covered by automated tests that run on every change.

Vachanam's own operator (the platform super-admin) is **locked out of clinic patient-data routes** by role checks — platform administration does not include browsing patient records.

---

## 3. Data Minimisation in Telemetry

Our production logs follow a strict PII discipline:

- Phone numbers appear as the **last 4 digits only** (`xx7554`).
- People are referenced by **internal IDs, never names**.
- No health information is written to logs, notifications, or calendar events.
- Every significant event (call lifecycle, booking, failure) is logged in structured form so problems can be investigated **without** widening data exposure.

---

## 4. Retention and Erasure (enforced by software)

| Data | Kept for | Then |
|---|---|---|
| Patient identity (name, phone, age, gender) | 2 years after last appointment | Erased by a daily job — name replaced with a placeholder, phone/age/gender cleared, erasure timestamped |
| Booking rows (token, date, doctor) | Retained after anonymisation | No longer link to an identifiable person; clinic keeps aggregate statistics |
| Call transcripts (text, phone-masked) | 90 days | Deleted by the same daily job |
| Consent records | Same window as the patient data they document | Pruned |
| Treatment visit notes + follow-up Q&A summary (optional feature; clinic-scoped) | Until patient-record erasure | Deleted / text cleared with the patient record |
| Temporary token counters (cache) | Same calendar day | Expire automatically |
| Voice audio | Never stored | — |
| Staff accounts | Until removed by the clinic owner (+30-day recovery buffer) | PII purged; anonymised audit records kept |
| Audit log | 7 years (IDs only, no names) | Deleted |

These are not policy aspirations — `data_retention.py` runs daily in production and its actions are logged.

---

## 5. Your Rights and How to Exercise Them

Under the DPDP Act 2023 you may request **access** to, **correction** of, or **erasure** of your personal data, **withdraw consent**, and **file a grievance**. Email **privacy@vachanam.in** (Vinay Rongala, Grievance Officer). We acknowledge within 48 hours and complete within 7 calendar days, after verifying your identity via your registered phone number. If unsatisfied, you may approach the Data Protection Board of India.

---

## 6. Security Measures

- All traffic encrypted in transit (TLS); database encrypted at rest (AES-256).
- Authentication via short-lived tokens (8-hour hard expiry, immediate revocation on logout), rate limiting on sensitive endpoints, and security headers on every response.
- Secrets are never stored in code; access to production systems is limited and audited.
- Third-party processors are listed by role and location in the [Privacy Policy](/privacy) §6 (the named list is available on request to privacy@vachanam.in) — no processor is added without a policy update first.

---

*Questions? hello@vachanam.in — we will answer in Telugu, Hindi, or English.*

© 2026 Vachanam (Vinay Rongala), Hyderabad, India. All rights reserved.
