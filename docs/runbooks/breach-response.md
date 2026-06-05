# Breach Response Runbook

**Owner:** Vinay Rongala (acting DPO)
**Contact:** privacy@vachanam.in | +91-ADMIN_PHONE (from env var)
**Last updated:** 2026-06-04
**Drill frequency:** Every 6 months (tabletop exercise, per spec section 12.3)

This runbook is designed so that anyone at 2 AM can follow it without asking questions. Read top to bottom. Execute each step in order.

---

## Quick Reference

| Item | Value |
|---|---|
| Grievance officer | Vinay Rongala, privacy@vachanam.in |
| DPB notification deadline | 72 hours from CONFIRMED breach involving personal data |
| Clinic notification deadline | 24 hours from CONFIRMED breach affecting their data |
| Post-mortem deadline | 14 days from breach confirmation |
| Incident doc location | `docs/incidents/YYYY-MM-DD-<slug>.md` |
| Audit log query | See Step 3 below |
| DPDP Act section | s.11 (breach notification to Board) |

---

## Step 1: Detect

**Goal:** Determine within 1 hour whether this is a real breach, a false alarm, or unclear.

### Alert sources (how you find out)

| Source | What it looks like |
|---|---|
| Log anomaly | Spike in 403s on data-isolation endpoints; unusual query patterns in structlog |
| Customer report | Clinic owner emails/calls: "I see data that is not mine" or "a patient says they got a call they did not make" |
| Vendor notification | Razorpay notifies a webhook secret was compromised; Neon notifies a credential rotation; Sarvam reports a data incident |
| Audit log anomaly | Unexpected `user.login.success` from unknown IP; bulk `token.attend` actions outside clinic hours; `rate_limit.exceeded` from an authenticated user |
| CI secret scan | Gitleaks CI job (`.github/workflows/ci.yml`) flags a secret in a commit |
| External security researcher | Email to security@vachanam.in reporting a vulnerability |

### Triage checklist (answer within 1 hour)

- [ ] Is personal data involved? (patient name, phone, complaint, or staff email)
- [ ] Is the data exposed to someone who should not have it? (external attacker, wrong clinic, unauthorized staff)
- [ ] Is the exposure ongoing or contained?
- [ ] How many data subjects are potentially affected? (1 patient? 1 clinic? all clinics?)

**If personal data IS exposed to unauthorized parties: this is a CONFIRMED BREACH. Proceed to Step 2 immediately.**

**If unsure: treat as a breach and proceed. Do not delay containment waiting for certainty.**

**If confirmed false alarm: document in `docs/incidents/YYYY-MM-DD-false-alarm-<slug>.md` with evidence. No further steps required.**

---

## Step 2: Contain

**Goal:** Stop the bleeding before investigating further. Do the minimum needed to prevent additional data exposure.

### Scenario-specific containment actions

#### Scenario A: JWT secret leaked (e.g., committed to GitHub)

All issued JWTs are now forgeable. An attacker can impersonate any user.

1. **Rotate JWT_SECRET immediately:**
   - Go to Render dashboard > your backend service > Environment
   - Generate a new secret: `openssl rand -hex 32` (run locally)
   - Update `JWT_SECRET` env var to the new value
   - Click "Save Changes" -- Render will automatically redeploy
2. **Force all users to re-login:**
   - The new JWT_SECRET invalidates all existing tokens (signatures no longer verify)
   - No additional action needed; users will get 401 and must re-authenticate
3. **Revoke the leaked commit:**
   - If the commit is public: `git revert <commit>` and force-push
   - If the commit is not yet pushed: `git reset --hard HEAD~1`
   - Rotate any OTHER secrets that were in the same commit or file
4. **Check GitHub audit log:**
   - If repo is public: check how long the commit was visible (GitHub event log)
   - If less than 1 hour and no evidence of exploitation: may not require DPB notification (assess in Step 3)

#### Scenario B: One receptionist account compromised (e.g., phishing)

A single user account is being used by an unauthorized person.

1. **Revoke the user's JWT immediately:**
   - Find their `user_id` in the database: `SELECT id, email FROM users WHERE email = '<email>';`
   - Find their active JTI: query audit_log for their most recent `user.login.success`
   - Add to revocation: in Redis, `SET revoked_jwts:<jti> 1 EX <remaining_seconds>`
2. **Disable the user account:**
   - In database: `UPDATE users SET is_active = false WHERE id = '<user_id>';`
   - (REQUIRES: backend-engineer to add `is_active` field to User model; for MVP, manually set via psql)
3. **Notify the clinic owner:**
   - Email and call the clinic owner. Ask them to verify the receptionist's identity and re-enable when confirmed.
4. **This is typically NOT a reportable breach** unless the attacker accessed and exfiltrated patient data. Assess in Step 3.

#### Scenario C: Database read-only access leak (e.g., analytics user credentials exposed)

Someone may have read access to the entire database.

1. **Rotate the compromised database credentials immediately:**
   - Go to Neon dashboard > your project > Connection Details
   - Reset the password for the compromised role
   - Update `DATABASE_URL` env var in Render dashboard
   - Render will automatically redeploy
2. **Pause writes if the main application role is compromised:**
   - In Render dashboard, set env var `READ_ONLY_MODE=true` and redeploy
   - This prevents additional data from being written while you investigate
3. **Query Neon query log** (if available on your plan) to see what queries the attacker ran
4. **This is LIKELY a reportable breach.** Proceed to Step 3 to assess scope.

#### Scenario D: Webhook secret leaked (Razorpay)

Someone could forge payment webhook calls.

1. **Rotate the webhook secret:**
   - Go to Razorpay Dashboard > Settings > Webhooks > Edit webhook > regenerate secret
   - Copy the new secret
   - Update `RAZORPAY_WEBHOOK_SECRET` env var in Render dashboard
   - Render will automatically redeploy
2. **Review recent webhook activity:**
   - Query audit_log: `SELECT * FROM audit_log WHERE action LIKE 'payment.%' AND created_at >= '<leak_time>' ORDER BY created_at;`
   - Look for unexpected `payment.verify.success` entries
3. **This is typically NOT a reportable breach** (no patient PII is accessible via webhook signing). But if fake payments were processed, notify Razorpay.

#### Scenario E: Audit log tamper attempt

Someone tried to UPDATE or DELETE audit_log entries to cover their tracks.

1. **Verify audit_log integrity:**
   - Check if DB permissions are correctly set: `SELECT has_table_privilege('vachanam_app', 'audit_log', 'UPDATE');` and `SELECT has_table_privilege('vachanam_app', 'audit_log', 'DELETE');`
   - Both should return `false` (per TD-023, Phase 10 prod-init)
   - If either returns `true`: the GRANT/REVOKE was not applied. Apply immediately:
     ```sql
     REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM vachanam_app;
     GRANT INSERT, SELECT ON audit_log TO vachanam_app;
     ```
2. **If UPDATE/DELETE succeeded** (permissions were wrong):
   - This is a SERIOUS incident. The audit trail may be unreliable.
   - Check if you have Neon point-in-time recovery (PITR) available
   - Restore audit_log from the most recent backup before the tamper
3. **Investigate who did it:** The tamper itself should show in Neon's connection logs or the application logs.

#### Scenario F: Cross-tenant data leak (Branch A sees Branch B data)

This is the most serious scenario. It means the branch_id isolation has failed.

1. **Identify the affected endpoint immediately:**
   - What API endpoint returned wrong data? (Check the clinic owner's report, audit logs, support logs)
2. **Disable the affected endpoint:**
   - If it is a single route: comment out the route in the appropriate router file, commit, push, Render redeploys
   - If it is unclear: set `READ_ONLY_MODE=true` in Render env and redeploy (disables writes; reads still need branch_guard)
3. **Deploy the fix:**
   - Add or correct the `branch_id` WHERE clause (Rule 1 violation)
   - Write a test that reproduces the cross-tenant access and asserts 403/empty result
   - Deploy fix
4. **Assess scope:**
   - Query audit_log for ALL requests to the affected endpoint: `SELECT * FROM audit_log WHERE action = '<action>' AND branch_id != '<requesting_user_branch>' AND created_at >= '<deploy_date_of_bug>';`
   - Determine how many branches were affected and how much data was exposed
5. **This IS a reportable breach.** File with DPB within 72 hours. Notify BOTH affected clinic owners immediately (within 24 hours).

---

## Step 3: Assess

**Goal:** Determine the scope of the breach -- who was affected, what data was exposed, and how long it lasted.

### Query the audit log

Run the following query to get all actions during the incident window:

```sql
SELECT
    action,
    user_id,
    ip_address,
    branch_id,
    resource_type,
    resource_id,
    success,
    metadata_json,
    created_at
FROM audit_log
WHERE created_at >= '<incident_start_timestamp>'
  AND created_at <= '<incident_end_timestamp>'
ORDER BY created_at;
```

Replace `<incident_start_timestamp>` with the earliest known or suspected time of compromise, and `<incident_end_timestamp>` with the current time or the time containment was achieved.

### Assessment questions

- [ ] Which user accounts were involved? (user_id values in the query results)
- [ ] Which branches (clinics) were affected? (branch_id values)
- [ ] What data was accessed? (resource_type: patient, token, user, etc.)
- [ ] How many data subjects (patients, staff) were affected?
- [ ] Was data only read, or was it also modified or deleted?
- [ ] Was data exfiltrated (sent outside our systems)?
- [ ] What is the earliest sign of compromise? (first suspicious audit_log entry)
- [ ] Is the compromise ongoing or fully contained?

### Determine if notification is required

| Condition | Notification required? |
|---|---|
| Personal data (name, phone, email) was exposed to an unauthorized party | YES -- notify DPB within 72h + clinic within 24h + affected patients |
| Only internal access (Vachanam staff accessed data they already could access) | NO -- but document and review access controls |
| Only metadata exposed (IP addresses, timestamps, action names) with no PII | NO -- but document |
| Attacker had access but no evidence of data retrieval | YES (conservative) -- notify with "no evidence of data access but potential exposure existed" |
| Unclear whether PII was accessed | YES -- notify with what is known; update later |

**DPDP Act s.11 requires notification even when investigation is incomplete.** Do not delay notification because you are still assessing. Notify with what you know; send updates as you learn more.

---

## Step 4: Notify

**Deadline: 72 hours from CONFIRMED breach for DPB; 24 hours for clinic owners.**

### 4.1 Notify the Data Protection Board of India

Per DPDP Act 2023 Section 11 and DPDP Rules (notified 14 November 2025):

**Current process (as of 2026-06-04):** The DPB notification portal at dpb.gov.in should be used if available. If the portal is not yet operational, send notification via email to the DPB contact specified in the DPDP Rules, or via registered post to:

> Data Protection Board of India
> [Address per DPDP Rules -- update when published by DPB]

**Notification must include:**

1. Nature of the breach (what happened)
2. Categories of personal data affected (name, phone, complaint summary, etc.)
3. Approximate number of data subjects affected
4. Likely consequences of the breach
5. Measures taken or proposed to address the breach and mitigate harm
6. Contact details of Vachanam's grievance officer (Vinay Rongala, privacy@vachanam.in)

**ACTION ITEM: Update this section with the exact DPB notification portal URL, form, and process once the DPB publishes operational guidance. Monitor dpb.gov.in quarterly.**

### 4.2 Notify affected clinic owners

**Within 24 hours of confirmed breach.** Use both email AND phone call.

**Email template:**

> Subject: Vachanam Security Incident Notification -- [Clinic Name]
>
> Dear [Clinic Owner Name],
>
> We are writing to inform you of a security incident that may have affected your clinic's data on the Vachanam platform.
>
> **What happened:** [Brief, factual description. E.g., "On [date], we discovered that a software bug allowed an authenticated user to view appointment data from a different clinic for approximately [duration]."]
>
> **What data was involved:** [Specific data types. E.g., "Patient first names, last 4 digits of phone numbers, appointment dates, and token numbers."]
>
> **What we have done:**
> - [Containment action taken. E.g., "We fixed the bug and deployed the patch within 2 hours of discovery."]
> - [Investigation status. E.g., "Our audit log shows that [N] patient records from your clinic were accessed."]
> - [Regulatory notification. E.g., "We have notified the Data Protection Board of India as required by law."]
>
> **What you should do:**
> - If you wish to inform your patients directly, we can provide you with the list of affected patient names and appointment dates.
> - If any patient contacts you about this incident, please direct them to privacy@vachanam.in or share this notification with them.
>
> **What we are changing:** [Preventive measure. E.g., "We have added an additional automated test to prevent this type of bug from reaching production."]
>
> We sincerely apologize for this incident. If you have any questions, please contact us at privacy@vachanam.in or call [ADMIN_PHONE].
>
> Vinay Rongala
> Founder, Vachanam

### 4.3 Notify affected patients

**For MVP1:** Contact affected patients via email (if we have their email) or request the clinic owner to notify their patients using their own communication channels. Provide the clinic owner with a plain-language patient notification template.

**For MVP2 (when WhatsApp is live):** Send WhatsApp notification to affected patients directly.

**Patient notification template** (for clinic owner to forward):

> Namaskaram [Patient Name],
>
> We are contacting you on behalf of [Clinic Name]. The appointment booking service used by [Clinic Name] (called Vachanam) experienced a security incident on [date].
>
> **What this means for you:** [Simple explanation. E.g., "Your name and appointment details may have been seen by someone who was not authorized to see them. No medical records, prescriptions, or payment information were involved."]
>
> **What you need to do:** Nothing is required from you. Your future appointments are not affected.
>
> **Your rights:** You have the right to request a copy of your data, ask us to correct it, or ask us to delete it. Contact privacy@vachanam.in or call [ADMIN_PHONE].
>
> We apologize for the inconvenience.
>
> [Clinic Name] and Vachanam

### 4.4 Public statement (if warranted)

If the breach affects a large number of data subjects (100+) or is likely to receive media attention, publish a statement at vachanam.in/security with:

- Date and time of discovery
- Nature of the breach (factual, no speculation)
- Scope (number of clinics, approximate number of patients)
- Containment and remediation actions
- How affected individuals can contact us
- DPB notification status

---

## Step 5: Remediate and Report

**Goal:** Fix the root cause, document everything, and share with stakeholders.

### 5.1 Patch the root cause

- Within 7 days of the breach: deploy a fix that eliminates the vulnerability
- Write automated tests that would have caught the issue before it reached production
- If the fix requires a database migration: coordinate with database-engineer
- If the fix requires infrastructure changes: coordinate with devops-engineer

### 5.2 Post-mortem document

Create a file at `docs/incidents/YYYY-MM-DD-<slug>.md` with:

1. **Summary:** One paragraph describing what happened
2. **Timeline:** Minute-by-minute from first indicator to full remediation
3. **Root cause:** 5-whys analysis (keep asking "why" until you reach the systemic cause)
4. **Impact:** Number of data subjects affected; what data was exposed; duration of exposure
5. **Detection:** How was the breach detected? Could we have detected it earlier?
6. **Response:** Steps taken to contain, assess, and notify
7. **Remediation:** What was fixed? What tests were added?
8. **Prevention:** What systemic changes will prevent similar incidents? (process, code, infrastructure, training)
9. **Open items:** Any remaining work with owners and deadlines

### 5.3 Share with stakeholders

- **Within 14 days:** Share the post-mortem with all affected clinic owners
- **Within 14 days:** Update the Data Protection Board with remediation actions taken
- **Within 30 days:** Review and update this runbook if the breach revealed gaps in the response process

---

## Appendix A: Contact Directory

| Role | Name | Contact | When to reach |
|---|---|---|---|
| Acting DPO / Grievance Officer | Vinay Rongala | privacy@vachanam.in, ADMIN_PHONE | Any breach, any time |
| Data Protection Board of India | DPB | dpb.gov.in | Within 72 hours of confirmed breach |
| Neon (database) | Neon Support | neon.tech support portal | Database credential compromise |
| Razorpay | Razorpay Support | dashboard.razorpay.com | Webhook secret compromise, payment fraud |
| Render | Render Support | render.com support | Backend environment compromise |
| Fly.io | Fly.io Support | fly.io support | Voice agent environment compromise |
| Sarvam AI | Sarvam Support | sarvam.ai support | STT/TTS data incident |

---

## Appendix B: Drill Schedule

Tabletop exercise every 6 months. Pick one scenario from Step 2. Walk through all 5 steps with a timer. Document the drill in `docs/incidents/YYYY-MM-DD-drill-<scenario>.md` with:

- Scenario chosen
- Time to complete each step
- Gaps identified in the runbook
- Updates made to this document as a result

| Drill # | Target date | Scenario | Status |
|---|---|---|---|
| 1 | 2026-12-01 | TBD (pick before drill) | Scheduled |
| 2 | 2027-06-01 | TBD | Scheduled |

---

*This runbook is a living document. Update it every time a breach occurs, a drill reveals a gap, or the DPDP Rules provide additional guidance on notification format.*
