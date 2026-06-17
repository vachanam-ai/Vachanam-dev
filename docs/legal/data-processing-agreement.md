# Data Processing Agreement

**Between:**

1. **The Clinic** ("Data Fiduciary," "you"), as identified in the signature block below, and
2. **Vachanam** ("Data Processor," "we"), sole proprietorship of Vinay Rongala, Hyderabad, Telangana, India.

**Effective date:** The date both parties sign this agreement.

This Data Processing Agreement (DPA) supplements the Vachanam Terms of Service and establishes how Vachanam processes personal data on behalf of the Clinic, in compliance with the Digital Personal Data Protection (DPDP) Act 2023.

---

## 1. Definitions

- **Personal data:** Any data about an identifiable natural person, as defined in DPDP Act 2023 Section 2(t).
- **Data Fiduciary:** The Clinic -- the entity that determines the purpose and means of processing personal data (DPDP Act Section 2(i)).
- **Data Processor:** Vachanam -- the entity that processes personal data on behalf of the Data Fiduciary (DPDP Act Section 2(k)).
- **Data Principal:** The patient, doctor, or staff member whose personal data is processed.
- **Processing:** Any operation performed on personal data, including collection, recording, organization, structuring, storage, retrieval, use, disclosure, or deletion (DPDP Act Section 2(x)).
- **Platform:** The Vachanam AI-powered appointment booking service, including the voice agent, backend API, receptionist web app, and owner dashboard.

---

## 2. Scope and Purpose of Processing

Vachanam processes personal data solely on the documented instructions of the Clinic, for the following purposes:

- Answering inbound patient phone calls via AI voice agent
- Understanding the patient's health concern to route them to the appropriate doctor
- Checking doctor availability and assigning appointment tokens
- Creating calendar events for doctors
- Providing a receptionist queue management interface
- Providing clinic owner analytics (appointment counts, attendance rates)
- Sending booking confirmations (via WhatsApp in upcoming release, with separate notice)
- Generating billing records for the Clinic's Vachanam subscription

Vachanam will NOT process personal data for any purpose beyond those documented above without prior written consent from the Clinic.

---

## 3. Categories of Data Processed

### 3.1 Categories of data subjects

| Category | Description |
|---|---|
| Patients | Individuals who call the Clinic's number to book an appointment |
| Doctors | Medical professionals at the Clinic whose schedules are managed through the Platform |
| Staff | Clinic owner(s) and receptionist(s) who log into the Platform |

### 3.2 Categories of personal data

| Data subject | Personal data processed |
|---|---|
| Patient | First name, mobile phone number, complaint summary (one-line description of health concern), appointment date, token number |
| Doctor | Name, specialization, working hours |
| Staff | Email address, name, role (owner or receptionist) |

### 3.3 Data NOT processed

- Voice call recordings (not stored; audio processed in real time only)
- Full medical history, diagnosis, prescriptions, or test results
- Aadhaar number, PAN number, or other government ID numbers
- Patient payment or financial information
- Biometric data

---

## 4. Sub-Processors

Vachanam uses the following sub-processors to deliver the service. By signing this DPA, the Clinic consents to the use of these sub-processors.

| Sub-processor | What they process | Data location | Purpose |
|---|---|---|---|
| Sarvam AI | Voice audio (real-time speech-to-text only) | India | Convert patient speech to text during calls |
| smallest.ai (Waves) | The agent's response text, including the patient's spoken name, converted to voice (text-to-speech) | Global | Convert the agent's responses to natural speech during calls |
| Google (Calendar API) | Calendar events containing patient first name + last 4 digits of phone number | Global (Google Cloud) | Create appointment events on doctor's calendar |
| Google (OAuth) | Staff email address | Global (Google Cloud) | Authenticate clinic staff login |
| Google (Gemini 2.5 Flash) | Real-time conversation transcript | Global (Google Cloud) | Primary AI language model for understanding patient requests; also performs automated quality review (scoring) of call transcripts for service improvement — the stored output is non-identifying (a numeric score + issue tags, no patient data) |
| OpenAI (GPT-4o mini) | Real-time conversation transcript | Global (OpenAI) | Backup AI language model (used only when Gemini is unavailable) |
| Razorpay | Clinic billing amount, clinic owner email | India | Process Clinic subscription payments |
| Resend | Clinic staff / owner email address | Global (US) | Send one-time verification codes (email OTP) during staff signup |
| Neon | All database records (patients, doctors, tokens, staff, audit log) | Singapore | Database hosting |
| Upstash | Temporary token counters (daily booking counts only) | Mumbai, India | Prevent double-booking via atomic token assignment |
| LiveKit | Audio routing metadata (no storage of call content) | Mumbai, India | Voice call infrastructure |
| Fly.io | Voice agent compute (processes calls in real time) | Mumbai, India | Host voice agent server |
| Render | Backend API compute (processes API requests) | Singapore | Host backend application server |
| Cloudflare | HTTP request metadata (IP, URL, headers) | Global edge | CDN, DNS, web application firewall |

### 4.1 Changes to sub-processors

If Vachanam intends to add or replace a sub-processor:

- We will notify the Clinic at least 30 days before the new sub-processor begins processing data.
- The Clinic may object within 14 days of notification. If the objection cannot be resolved, the Clinic may terminate this DPA and the subscription, with data handled per Section 9.
- The current sub-processor list is also published in the Vachanam Privacy Policy at app.vachanam.in/privacy (Section 6).

---

## 5. Security Measures

Vachanam implements the following security measures to protect personal data processed on behalf of the Clinic:

### 5.1 Technical measures

| Measure | Implementation |
|---|---|
| Encryption in transit | TLS 1.2+ on all connections; HSTS enforced |
| Encryption at rest | AES-256 disk encryption (managed by Neon, our database provider) |
| Data isolation | Every database query is scoped to the Clinic's branch_id; one clinic cannot access another's data |
| Access control | Role-based JWT authentication (owner, receptionist, admin); Google OAuth login (no passwords stored) |
| Audit logging | Append-only audit log of all sensitive actions (login, data access, token assignment, payment); 7-year retention |
| Rate limiting | Per-endpoint, per-user request throttling; IP blocklist for brute-force attempts |
| Web application firewall | Cloudflare managed OWASP Core Rule Set + Bot Fight Mode |
| Session security | 8-hour hard JWT expiry; 30-minute idle timeout; immediate revocation on logout |
| Secret management | All API keys and secrets stored as environment variables; secret scanning on code repository |
| PII protection in logs | Phone numbers truncated to last 4 digits in all log output; PII denylist enforced on audit log metadata |

### 5.2 Organizational measures

| Measure | Implementation |
|---|---|
| Access to production systems | Limited to Vinay Rongala (founder, acting DPO); all access audit-logged |
| Security reviews | Pre-release OWASP ZAP scan; quarterly dependency audit; quarterly breach response drill |
| Incident response | Documented breach response runbook (5 steps, 6 pre-rehearsed scenarios); 72-hour notification to Data Protection Board |

---

## 6. Breach Notification

### 6.1 Notification to the Clinic

If Vachanam becomes aware of a breach of personal data affecting the Clinic's data:

- Vachanam will notify the Clinic within **24 hours** of confirming the breach, via email to the Clinic's registered owner email address and phone call to the registered owner phone number.
- The notification will include: nature of the breach, categories and approximate number of data subjects affected, likely consequences, measures taken or proposed to address the breach.

### 6.2 Notification to the Data Protection Board

Vachanam will notify the Data Protection Board of India within **72 hours** of confirming a breach involving personal data, as required by DPDP Act 2023 Section 11.

### 6.3 Remediation report

Vachanam will provide the Clinic with a written post-mortem report within **14 days** of the breach, including root cause analysis, scope of impact, remediation actions taken, and changes made to prevent recurrence.

---

## 7. Data Subject Rights

### 7.1 Assistance with requests

When a Data Principal (patient, doctor, or staff member) exercises their rights under DPDP Act 2023 Sections 11-13 (access, correction, erasure, grievance):

- If the request comes to the Clinic: the Clinic may forward it to Vachanam at privacy@vachanam.in. Vachanam will execute the request within 7 calendar days.
- If the request comes directly to Vachanam: Vachanam will notify the Clinic and execute the request within 7 calendar days after identity verification.

### 7.2 Identity verification

Vachanam will verify the identity of any requester before processing a data subject request, to prevent unauthorized access to personal data. Verification methods: OTP confirmation of the phone number on record, and/or photo of government-issued ID.

---

## 8. Audit Rights

### 8.1 Clinic audit access

The Clinic may request an extract of all audit log entries for their branch_id, up to once per calendar year, at no additional charge. Vachanam will provide the extract within 14 calendar days of the request.

### 8.2 Scope of audit

The audit extract will include: all actions logged for the Clinic's branch_id, including user logins, data access events, token assignments, and any data subject requests processed. Patient phone numbers will be truncated to last 4 digits in the extract (consistent with our PII protection policy).

### 8.3 Regulatory audit

If a regulatory authority (including the Data Protection Board of India) requires an audit of data processing activities related to the Clinic's data, Vachanam will cooperate fully with the Clinic and the authority within the timeframes set by the authority.

---

## 9. Data Return and Deletion on Termination

When this DPA terminates (due to subscription cancellation, DPA termination, or any other reason):

### 9.1 Data export

The Clinic may request a full export of all their data within 14 days of termination. Vachanam will provide the export in JSON format, including: all patient records, doctor records, token/booking records, and staff records associated with the Clinic's branch_id(s).

### 9.2 Data deletion

Within 30 calendar days of termination (or after the data export is delivered, whichever is later), Vachanam will permanently delete all personal data processed on behalf of the Clinic, except:

- **Audit log entries:** Retained for 7 years from creation date, as required for regulatory compliance. These entries contain action descriptions, timestamps, and user IDs -- not full personal data (phone numbers are truncated to last 4 digits).
- **Billing records:** Retained as required by Indian tax law (currently the Income Tax Act requires 6 years; we retain for 7 years to align with audit log retention).

### 9.3 Deletion confirmation

Vachanam will confirm deletion in writing (email to the Clinic's registered owner email) within 7 days of completing the deletion.

---

## 10. Duration

This DPA remains in effect for the duration of the Clinic's active Vachanam subscription, plus the retention windows specified in Section 9 above.

---

## 11. Governing Law

This DPA is governed by the laws of India, including the DPDP Act 2023 and the DPDP Rules notified on 14 November 2025. Any dispute will be subject to the exclusive jurisdiction of the courts in Hyderabad, Telangana, India.

---

## 12. Signature

By signing below, both parties agree to the terms of this Data Processing Agreement.

### Vachanam (Data Processor)

| Field | Value |
|---|---|
| Name | Vinay Rongala |
| Title | Founder, Vachanam |
| Email | hello@vachanam.in |
| Date | _________________ |
| Signature | _________________ |

### Clinic (Data Fiduciary)

| Field | Value |
|---|---|
| Clinic name | _________________ |
| Authorized signatory name | _________________ |
| Title | _________________ |
| Email | _________________ |
| Date | _________________ |
| Signature | _________________ |

---

*This DPA is version 1.0, effective 2026-06-04. Updates to this DPA will follow the same 30-day notice process as the Vachanam Privacy Policy and Terms of Service.*
