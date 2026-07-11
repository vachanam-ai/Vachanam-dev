# Data Subject Access Request (DSAR) Runbook

**Owner:** Vinay Rongala (acting DPO, Grievance Officer)
**Contact:** hello@vachanam.in
**SLA:** 7 calendar days from verified request to completed response
**Legal basis:** DPDP Act 2023 Sections 11-13 (rights of Data Principal)
**Last updated:** 2026-06-04

---

## Overview

A Data Subject Access Request (DSAR) is when a patient, doctor, or clinic staff member asks us to:

1. **Access** -- "Give me a copy of all data you have about me"
2. **Correct** -- "My name is spelled wrong; fix it"
3. **Delete** -- "Delete all my data" (right to erasure)
4. **Withdraw consent** -- "Stop sending me follow-up calls" (does not affect existing bookings)

This runbook covers the step-by-step process for handling each type. Follow it exactly.

---

## Step 1: Receive the Request

### How requests arrive

| Channel | Action |
|---|---|
| Email to hello@vachanam.in | Primary channel. Proceed to Step 2. |
| Email to hello@vachanam.in | Forward to hello@vachanam.in. Proceed to Step 2. |
| Verbal request to clinic owner | Clinic owner forwards to hello@vachanam.in on behalf of patient. Proceed to Step 2. |
| Phone call to ADMIN_PHONE | Ask the requester to also email hello@vachanam.in so there is a written record. Then proceed to Step 2. |

### Information to capture from the request

- Requester's full name
- Requester's phone number (the one used for booking)
- Which clinic they booked with (if they remember)
- What they are requesting: access, correction, deletion, or consent withdrawal
- If correction: what data is wrong and what it should be

If the email does not contain enough information to proceed, reply asking for the missing details. The 7-day SLA clock starts when we have enough information to identify the requester and their request.

---

## Step 2: Verify Identity

**This step is mandatory. Never skip it.** Processing a DSAR without verifying identity is itself a data breach (giving one person another person's data).

### Verification process

1. **Phone OTP verification:**
   - Send an OTP to the phone number the requester claims to own (the phone number on their booking records)
   - Ask the requester to provide the OTP
   - If the OTP matches: identity verified for that phone number

2. **Government ID verification (if OTP is insufficient):**
   - Ask the requester to send a photo of a government-issued ID (Aadhaar card, PAN card, voter ID, passport, driving license)
   - Verify that the name on the ID matches the name on our records
   - Verify that the photo on the ID reasonably matches the requester (if video call is needed)
   - After verification, delete the photo of the ID from our systems (do not retain copies of government IDs)

3. **Clinic-forwarded requests:**
   - If the clinic owner forwards the request on behalf of a patient, the clinic owner's identity is already verified (they are logged into Vachanam)
   - Still verify the patient's identity via OTP before releasing data

### When verification fails

If the requester cannot verify their identity:
- Do NOT process the request
- Reply: "We were unable to verify your identity. For your protection, we cannot process data requests without verification. Please try again with a different form of identification, or visit your clinic in person to request their assistance."
- Log the failed attempt in the audit log

---

## Step 3: Acknowledge the Request

**Deadline: 48 hours from receiving the request (or from successful identity verification, whichever is later).**

Send an acknowledgment email:

> Subject: Your Data Request -- Acknowledged [Request ID: DSAR-YYYY-MM-DD-NNN]
>
> Dear [Requester Name],
>
> We have received and verified your request to [access / correct / delete / withdraw consent for] your personal data.
>
> **Request ID:** DSAR-YYYY-MM-DD-NNN
> **Request type:** [Access / Correction / Deletion / Consent Withdrawal]
> **Date received:** [date]
> **Expected completion:** Within 7 calendar days (by [date])
>
> If you have any questions, reply to this email or contact us at hello@vachanam.in.
>
> Vinay Rongala
> Grievance Officer, Vachanam

Generate the Request ID in format `DSAR-YYYY-MM-DD-NNN` where NNN is a sequential number for that day (e.g., DSAR-2026-06-10-001).

---

## Step 4: Execute the Request

### 4A: Access Request (export data)

**Automated (when `scripts/dsar.py` is available):**

```bash
python scripts/dsar.py --phone "+91XXXXXXXXXX" --branch <branch_uuid> --action export
```

This will output a JSON file containing all personal data associated with the phone number in the specified branch.

(REQUIRES: backend-engineer to create `scripts/dsar.py` CLI tool in Phase 6+.)

**Manual fallback (MVP1, until the script is available):**

Connect to the Neon database and run the following queries:

```sql
-- 1. Find the patient record
SELECT id, name, phone, followup_consent, created_at, updated_at
FROM patients
WHERE phone = '+91XXXXXXXXXX'
  AND branch_id = '<branch_uuid>';

-- 2. Get all their bookings
SELECT t.id, t.token_number, t.date, t.status, t.doctor_id, d.name as doctor_name, t.created_at
FROM tokens t
JOIN doctors d ON t.doctor_id = d.id
WHERE t.patient_id = '<patient_id_from_step_1>'
  AND t.branch_id = '<branch_uuid>'
ORDER BY t.date DESC;

-- 3. Get all their call records
SELECT id, started_at, ended_at, duration_seconds, language, emergency_flag
FROM calls
WHERE patient_phone = '+91XXXXXXXXXX'
  AND branch_id = '<branch_uuid>'
ORDER BY started_at DESC;

-- 4. Get any follow-up tasks
SELECT id, task_type, scheduled_for, status, created_at
FROM followup_tasks
WHERE patient_id = '<patient_id_from_step_1>'
  AND branch_id = '<branch_uuid>'
ORDER BY scheduled_for DESC;

-- 5. Get audit log entries for this patient (last 4 digits of phone only)
SELECT action, created_at, metadata_json
FROM audit_log
WHERE branch_id = '<branch_uuid>'
  AND metadata_json::text LIKE '%<last_4_digits_of_phone>%'
ORDER BY created_at DESC
LIMIT 100;
```

Compile the results into a JSON file. Redact any internal system IDs (UUIDs) that serve no purpose for the patient. Include: name, phone (masked as +91XXXX1234), all appointment dates and statuses, doctor names, call timestamps and durations.

### 4B: Correction Request

**Via the receptionist PWA (preferred):**
- Ask the clinic owner or receptionist to edit the patient's details through the web app (Queue page > patient card > edit)
- Confirm the correction with the requester

**Manual fallback (if PWA edit is not available for the specific field):**

```sql
-- Example: correct patient name
UPDATE patients
SET name = '<corrected_name>', updated_at = NOW()
WHERE id = '<patient_id>'
  AND branch_id = '<branch_uuid>';
```

Verify the correction by re-querying and confirming with the requester.

### 4C: Deletion Request (right to erasure)

**Step 1: Soft delete (immediate)**

```sql
-- Mark patient as deleted (soft delete)
UPDATE patients
SET name = '[DELETED]', phone = '[DELETED]', followup_consent = false, updated_at = NOW()
WHERE id = '<patient_id>'
  AND branch_id = '<branch_uuid>';
```

**Step 2: Hard delete (30 days later)**

After 30 days, permanently delete the patient record and associated data:

```sql
-- Delete follow-up tasks
DELETE FROM followup_tasks WHERE patient_id = '<patient_id>' AND branch_id = '<branch_uuid>';

-- Delete call records
DELETE FROM calls WHERE patient_phone = '<original_phone>' AND branch_id = '<branch_uuid>';

-- Delete token/booking records
DELETE FROM tokens WHERE patient_id = '<patient_id>' AND branch_id = '<branch_uuid>';

-- Delete patient record
DELETE FROM patients WHERE id = '<patient_id>' AND branch_id = '<branch_uuid>';
```

**What is NOT deleted:**

- Audit log entries (retained for 7 years per regulatory requirements). These entries contain only truncated phone numbers (last 4 digits) and action descriptions, not full personal data.
- Aggregated analytics data (total booking counts per day) that cannot be traced back to an individual.

**The 30-day soft delete window** exists to allow recovery if the request was made in error. If the patient explicitly requests immediate permanent deletion (and confirms they understand it is irreversible), proceed to hard delete immediately.

(REQUIRES: backend-engineer to implement automated hard-delete sweep in `data_retention.py` job, Phase 6+.)

### 4D: Consent Withdrawal

**Follow-up consent withdrawal:**

```sql
UPDATE patients
SET followup_consent = false, updated_at = NOW()
WHERE id = '<patient_id>'
  AND branch_id = '<branch_uuid>';
```

The patient can still book new appointments. Only follow-up outreach is stopped.

**Marketing consent withdrawal (future, if marketing consent is ever collected):**

Set the relevant consent flag to false. Immediately stop all marketing communications to this patient.

Consent withdrawal does not affect processing that already occurred before the withdrawal, and does not affect the patient's ability to use the booking service.

---

## Step 5: Respond to the Requester

**Deadline: 7 calendar days from the verified request.**

Send the response email:

> Subject: Your Data Request -- Completed [Request ID: DSAR-YYYY-MM-DD-NNN]
>
> Dear [Requester Name],
>
> Your data request has been completed.
>
> **Request ID:** DSAR-YYYY-MM-DD-NNN
> **Request type:** [Access / Correction / Deletion / Consent Withdrawal]
>
> [For ACCESS:]
> Please find attached a JSON file containing all personal data we hold about you for [Clinic Name]. If you have questions about any of the data, reply to this email.
>
> [For CORRECTION:]
> The following data has been corrected:
> - [Field]: Changed from "[old value]" to "[new value]"
> Please confirm that this is correct by replying to this email.
>
> [For DELETION:]
> Your personal data has been marked for deletion. Your name and phone number have been removed from our active records immediately. All remaining associated data (booking history, call records) will be permanently deleted within 30 days. Audit log entries containing only your truncated phone number (last 4 digits) are retained for 7 years per regulatory requirements.
>
> [For CONSENT WITHDRAWAL:]
> Your consent for [follow-up calls / marketing] has been withdrawn. You will no longer receive [follow-up calls / marketing communications]. This does not affect your ability to book future appointments.
>
> If you are not satisfied with how we handled your request, you have the right to file a grievance with the Data Protection Board of India at dpb.gov.in.
>
> Vinay Rongala
> Grievance Officer, Vachanam

---

## Step 6: Write the Audit Log Entry

Every DSAR must have a corresponding audit log entry. This is how we demonstrate compliance to regulators.

**Automated (when `scripts/dsar.py` is available):**

The script writes the audit log entry automatically.

**Manual fallback (MVP1):**

```sql
INSERT INTO audit_log (id, action, user_id, ip_address, branch_id, resource_type, resource_id, success, metadata_json, created_at)
VALUES (
    gen_random_uuid(),
    'data_subject_request',
    '<vinay_user_id>',       -- the user who processed the request (Vinay for MVP1)
    '127.0.0.1',             -- or the IP from which the psql session ran
    '<branch_uuid>',
    'patient',
    '<patient_id>',
    true,
    '{"request_id": "DSAR-YYYY-MM-DD-NNN", "type": "<export|correct|delete|withdraw>", "phone_last4": "XXXX", "completed_at": "<timestamp>"}',
    NOW()
);
```

Note: `metadata_json` must NOT contain the full phone number or patient name (PII denylist enforcement per TD-022). Use only the request ID, request type, and last 4 digits of the phone.

---

## Step 7: Retain the DSAR Record

Retain the following for 3 years from the date the request was completed:

| What to retain | Where to store | Why |
|---|---|---|
| Original request email | Email archive (hello@vachanam.in inbox) | Compliance demonstration: we received the request |
| Identity verification evidence | Email archive (delete government ID photos after verification) | Compliance demonstration: we verified identity |
| Acknowledgment email sent | Email archive (sent items) | Compliance demonstration: we acknowledged within 48h |
| Response email sent | Email archive (sent items) | Compliance demonstration: we responded within 7 days |
| Data export file (if access request) | Encrypted local storage (Vinay's machine, encrypted drive) | Compliance demonstration: we provided the data |
| Audit log entry | Database (audit_log table, 7-year retention) | Compliance demonstration: we logged the action |

After 3 years, delete the email correspondence and data export files. The audit log entry remains for 7 years.

---

## Summary: Timeline and SLA

| Milestone | Deadline | Who |
|---|---|---|
| Request received | Day 0 | Patient emails hello@vachanam.in |
| Identity verified | Day 0-1 | Vinay (OTP + optional government ID) |
| Acknowledgment sent | Within 48 hours of receipt | Vinay |
| Request executed | Day 1-6 | Vinay (manual SQL for MVP1; automated script later) |
| Response sent | Within 7 calendar days of verified request | Vinay |
| Audit log entry written | Same day as response | Vinay |
| Hard deletion (if delete request) | 30 days after soft delete | Automated job (Phase 6+) or manual |

---

## Escalation

If a DSAR cannot be completed within 7 days (e.g., complex multi-branch request, database issue, identity verification deadlocked):

1. Email the requester before the 7-day deadline explaining the delay and providing a new estimated completion date.
2. Complete the request as soon as possible. Do not exceed 14 calendar days total.
3. Document the reason for the delay in the audit log entry metadata.

If a requester is unsatisfied with the response:

1. Review the request again with fresh eyes.
2. If the requester's concern is valid: correct the response and re-send.
3. If the requester's concern is outside our ability to address: inform them of their right to file a grievance with the Data Protection Board of India at dpb.gov.in.

---

*This runbook is a living document. Update it when the DSAR script is built, when the DPDP Rules provide additional guidance on DSAR process, or when experience reveals gaps.*
