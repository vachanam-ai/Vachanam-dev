# Vachanam Privacy Policy

**Effective date:** 2026-06-04
**Last updated:** 2026-07-11

This policy explains, in plain language, what personal data Vachanam collects, why we collect it, who sees it, how long we keep it, and what rights you have. If any part is unclear, email us at hello@vachanam.in and we will explain it in Telugu, Hindi, or English -- whichever you prefer.

---

## At a Glance

| Question | Answer |
|---|---|
| Do you record my call? | **No.** Audio is processed in real time and discarded. |
| What do you store? | First name, phone, one-line reason for visit, appointment details. |
| Who owns the data? | The clinic you called (Data Fiduciary). Vachanam only processes it. |
| Can other clinics see my data? | **Never** — enforced at the database level on every query. |
| Do you sell data or run ads? | **No**, and we never use patient data to train AI. |
| How long is data kept? | Identity: 2 years after last visit. Transcripts (text, masked): 90 days. Enforced by software. |
| Whom do I contact? | hello@vachanam.in — Grievance Officer: Vinay Rongala. |

**Contents:** 1. Who We Are · 2. Data We Collect · 3. Why We Collect · 4. Legal Basis (DPDP) · 5. Who Sees Your Data · 6. Third-Party Processors · 7. How We Protect Your Data · 8. Retention · 9. Your Rights · 10. Children's Data · 11. Cookies · 12. Changes · 13. Effective Date

---

## 1. Who We Are

**Vachanam** is an AI-powered appointment booking service for clinics in India. We help patients book appointments by phone, and we help clinics manage their schedules.

- **Company:** Vachanam (sole proprietorship of Vinay Rongala)
- **Location:** Hyderabad, Telangana, India
- **General contact:** hello@vachanam.in
- **Privacy and grievance contact:** hello@vachanam.in (Vinay Rongala, Grievance Officer)
- **Website:** vachanam.in

Under the Digital Personal Data Protection (DPDP) Act 2023, the clinic you visit is the "Data Fiduciary" -- they decide why your data is processed. Vachanam is the "Data Processor" -- we process your data on the clinic's behalf, only to book and manage your appointment.

---

## 2. Data We Collect

We collect different data depending on your role. We collect only what is needed for the booking service to work.

### If you are a patient

| Data | How we get it | Example |
|---|---|---|
| First name | You tell us during the phone call | "Ravi" |
| Mobile number | Caller ID from your phone call | +91 98765 XXXXX |
| Complaint summary | You describe your health issue in one line | "knee pain for 2 weeks" |
| Appointment date and time | Assigned during booking | "2026-06-10, Token #5, morning slot" |

**What we do NOT collect from patients:**

- We do NOT record your phone call. Audio is processed in real time to understand your words, then discarded. No voice recording is stored anywhere.
- We do NOT store your full medical history, diagnosis, prescriptions, test results, or Aadhaar/PAN number.
- We do NOT ask you to create an account or set a password.

**If your clinic uses treatment follow-ups** (optional feature): your doctor may record short visit-progress notes (what was done this visit, what comes next) and schedule a follow-up call. The AI's follow-up question and a short summary of your answer are stored for your doctor to read. This data is entered by or visible only to YOUR clinic, is never used for anything except your continuing care, and is erased together with your patient record. Follow-up calls are made only if you agreed to them when booking — if you said no (or withdraw later), the call simply never happens.

**About call transcripts:** a text transcript of the conversation (what was said, not the audio) may be kept for up to 90 days to monitor and improve call quality. Phone numbers are masked in the transcript before it is saved -- no unmasked copy is stored anywhere. The saved transcript is visible only to your own clinic; within Vachanam, production access is limited to the founder (acting Data Protection Officer) and every such access is audit-logged. The transcript is automatically deleted after the 90-day window by a daily software job.

### If you are a doctor

| Data | How we get it |
|---|---|
| Name | Clinic owner enters it during setup |
| Specialization | Clinic owner enters it |
| Working hours | Clinic owner enters it |

Note: WhatsApp-based doctor schedule management is planned for an upcoming release. When that feature launches, doctors' WhatsApp numbers will be collected, and this policy will be updated with 30 days notice.

### If you are a clinic staff member (owner or receptionist)

| Data | How we get it |
|---|---|
| Email address | You sign in with your Google account |
| Name | From your Google account |
| Role (owner or receptionist) | Assigned by the clinic owner |

---

## 3. Why We Collect Your Data

Every piece of data we collect has a specific purpose. We do not collect data "just in case."

| Data | Purpose |
|---|---|
| Patient name | So the doctor and receptionist know who is coming |
| Patient mobile number | To identify your appointment; to send booking confirmation (in upcoming WhatsApp release) |
| Complaint summary | To route you to the correct doctor (e.g., "chest pain" goes to the cardiologist, not the dentist) |
| Appointment date and token number | To reserve your spot and prevent double-booking |
| Doctor name and specialization | To match patients to the right doctor |
| Doctor working hours | To check availability before assigning a token |
| Staff email and name | To let staff log in securely via Google and manage the clinic's queue |
| Staff role | To control who can see what (a receptionist sees the queue; only the owner sees analytics) |

We also use anonymized, aggregated data (e.g., "this clinic had 35 bookings today") to show the clinic owner their own analytics dashboard. We never sell data. We never use patient data to train AI models, and we use our AI providers (such as Google Gemini) through paid enterprise APIs whose terms prohibit the provider from using submitted data to train their models.

---

## 4. Legal Basis Under the DPDP Act 2023

The Digital Personal Data Protection Act 2023 (DPDP Act) requires us to have a legal basis for processing your personal data.

- **Core booking functions** (collecting your name, phone, complaint, and assigning a token): We process this data as a Data Processor on documented instructions from the clinic (the Data Fiduciary). The clinic's legitimate business purpose is to manage patient appointments. This processing is necessary for the service you are actively requesting when you call the clinic's number.
- **Clinic staff login and access control**: Processed on the basis of the employment relationship between the clinic and its staff, and necessary for the legitimate business operation of the clinic.
- **Marketing communications** (if any, in future): Only with your separate, specific, freely-given consent. We will never bundle marketing consent with booking consent. You can withdraw marketing consent at any time without affecting your ability to book appointments.

---

## 5. Who Sees Your Data

Your data is visible only to people who need it to serve you.

| Who | What they see | Why |
|---|---|---|
| **The clinic you called** (owner and receptionists) | Your name, phone, complaint summary, token number, appointment date | To manage your visit and mark your attendance |
| **The specific doctor you are booked with** | Your name and token number (via calendar event showing first name + last 4 digits of phone) | To know who is coming and when |
| **Vachanam technical staff** | Access to backend systems for troubleshooting only; every access is recorded in an audit log | To fix technical issues if something goes wrong with your booking |

**Who does NOT see your data:**

- Other clinics on the Vachanam platform cannot see your data. Every clinic's data is strictly separated at the database level (enforced by branch_id isolation on every database query).
- We do not sell, rent, or share your data with advertisers, data brokers, or any third party not listed in Section 6 below.

---

## 6. Third-Party Data Processors

We use the following third-party services to operate Vachanam. Each service processes only the minimum data needed for its function. We have listed every service, what it does, where it operates, and a link to its own privacy policy.

| Service | What it processes | Where data is processed | Their privacy policy |
|---|---|---|---|
| **Soniox** | Converts your voice to text (speech-to-text) during your call. Audio is streamed in real time and not stored beyond the duration of the call. | United States | [soniox.com/privacy](https://soniox.com/legal/privacy-policy) |
| **Sarvam AI** | Backup speech-to-text, used only when Soniox is unavailable. Same real-time streaming, no storage beyond the call. | India | [sarvam.ai/privacy](https://sarvam.ai/privacy) |
| **smallest.ai (Waves)** | Converts the AI agent's responses (which include your name) back into voice (text-to-speech) during your call. Text is processed in real time and not stored after the call. | Global | [smallest.ai/privacy](https://smallest.ai) |
| **Google (Calendar API + OAuth)** | Creates a calendar event for your doctor with your first name and last 4 digits of your phone number. Also handles staff login via Google accounts. | Global (Google Cloud) | [policies.google.com/privacy](https://policies.google.com/privacy) |
| **Google (Gemini)** | Our AI language models (Gemini 3.1 Flash Lite primary, Gemini 2.5 Flash backup). Processes the conversation during your call to understand your request and route you to the right doctor. Subject to Google's data processing terms. | Global (Google Cloud) | [policies.google.com/privacy](https://policies.google.com/privacy) |
| **Razorpay** | Processes clinic subscription payments. Sees billing amount and clinic owner email for invoicing. Does NOT see any patient data. | India | [razorpay.com/privacy](https://razorpay.com/privacy) |
| **Resend** | Sends one-time verification codes to clinic staff by email during signup. Sees only the staff/owner email address. Does NOT see any patient data. | Global (US) | [resend.com/legal/privacy-policy](https://resend.com/legal/privacy-policy) |
| **Neon** | Hosts our PostgreSQL database where appointment and user records are stored. All data encrypted at rest (AES-256 disk encryption managed by Neon). | Singapore | [neon.tech/privacy](https://neon.tech/privacy) |
| **Upstash** | Hosts our Redis cache used for real-time token number assignment (preventing double-booking). Stores only temporary token counters that expire daily. | Mumbai, India | [upstash.com/privacy](https://upstash.com/privacy) |
| **LiveKit** | Voice call infrastructure that connects your phone call to our AI agent. Handles audio routing only; does not store call content. | Mumbai, India | [livekit.io/privacy](https://livekit.io/privacy) |
| **Fly.io** | Hosts the voice agent compute server that runs during your call. | Mumbai, India | [fly.io/legal/privacy-policy](https://fly.io/legal/privacy-policy) |
| **Render** | Hosts our backend API server that manages appointments, authentication, and clinic data. | Singapore | [render.com/privacy](https://render.com/privacy) |
| **Cloudflare** | Provides our CDN (content delivery network), DNS, and web application firewall. Processes HTTP request metadata (IP address, URL, headers) for security and routing. Does not see database contents. | Global edge network | [cloudflare.com/privacypolicy](https://www.cloudflare.com/privacypolicy/) |

**WhatsApp (Meta):** WhatsApp-based booking confirmations and doctor commands are planned for an upcoming release. When this feature launches, Meta will be added to this table and this policy will be updated with 30 days notice. WhatsApp is not active in the current version.

**If we add a new service:** We will update this table and notify you before the new service processes any data. No new data processor is added without updating this policy first.

---

## 7. How We Protect Your Data

Security is layered — no single control is trusted alone.

- **Encryption in transit:** every connection (calls' signalling, dashboard, API) uses TLS.
- **Encryption at rest:** the database is encrypted with AES-256 on SOC 2–audited infrastructure.
- **Tenant isolation:** every record carries the clinic's branch ID and every query is scoped to it — one clinic can never read another clinic's data. Automated tests that attempt cross-clinic access run on every code change and must fail.
- **Least-privilege access:** receptionists, doctors, and owners each see only what their role needs; even Vachanam's platform administrator is locked out of patient-data screens by role checks.
- **Authentication hardening:** login tokens expire after 8 hours (hard limit), are revoked immediately on logout, and sensitive endpoints are rate-limited against automated attacks.
- **Audit trail:** every significant action (bookings, access, failures) is written to an append-only audit log retained 7 years — using internal IDs, never names.
- **Data minimisation in telemetry:** logs show only the last 4 digits of any phone number; no health information ever appears in logs, notifications, or calendar events.
- **Backups and recovery:** the database keeps a continuous change history enabling point-in-time restore — recovery to any moment within the restore window, not just a nightly snapshot.
- **Secrets hygiene:** credentials are never stored in source code; production access is limited and audited.
- **Breach response:** a written, rehearsed runbook — affected clinics notified within 24 hours, the Data Protection Board within 72 hours (see our Data Processing Agreement §7).

---

## 8. How Long We Keep Your Data

We keep data only as long as it serves a clear purpose. Here are the specific retention periods for each type of data.

| Data type | How long we keep it | Why | What happens after |
|---|---|---|---|
| Active booking records (patient name, phone, complaint, token, appointment) | 2 years from last activity | Clinics need historical booking data for follow-ups and analytics | Permanently deleted from the database |
| Audit log (who accessed what, when, from where) | 7 years | Regulatory compliance and security investigation capability; aligns with Indian record-keeping norms | Permanently deleted |
| User accounts (staff email, name, role) | Until the clinic owner removes the user, or the user requests deletion + 30 days | Clinic needs active staff accounts; 30-day buffer allows recovery from accidental deletion | Personally identifiable information purged; anonymized audit records retained |
| Authentication tokens (login sessions) | 8 hours maximum (hard expiry) + immediate revocation on logout | Security: limits damage window if a device is stolen | Automatically expired; revocation records cleared from cache |
| Voice call audio | NOT STORED | We do not record calls. Audio is processed in real time by Sarvam AI for speech-to-text conversion, then discarded. | Not applicable |
| Treatment progress notes (doctor-entered) | Until the patient record is erased (2 years after last activity) | Doctors need continuity of care across visits | Deleted with the patient record |
| Follow-up question and answer summary | Until the patient record is erased | The doctor reads the patient's response | Question/answer text cleared with the patient record |
| Voice call transcripts (text only) | Up to 90 days | Call-quality monitoring and troubleshooting failed bookings. Phone numbers are masked before the transcript is saved; the transcript is visible only to your own clinic. | Transcript text automatically deleted by a daily job; the non-personal quality scores survive |
| Redis token counters (daily booking counts) | End of calendar day + 1 hour buffer | Prevents double-booking during the day | Automatically expired by Redis TTL |

**Retention enforcement:** We run automated jobs to delete data that has exceeded its retention period. This is not just a written policy -- it is enforced by software: a daily job erases patient personal data after 2 years of inactivity and deletes call transcripts after 90 days.

---

## 9. Your Rights Under the DPDP Act 2023

You have rights over your personal data. Here is what you can do and how to do it.

| Your right | What it means | How to exercise it |
|---|---|---|
| **Right to access** | You can request a copy of all personal data we hold about you | Email hello@vachanam.in |
| **Right to correction** | If your data is wrong (e.g., name misspelled), you can ask us to fix it | Email hello@vachanam.in |
| **Right to erasure** | You can ask us to delete your personal data | Email hello@vachanam.in |
| **Right to withdraw consent** | If you gave consent for something specific (e.g., follow-up calls), you can withdraw it anytime | Email hello@vachanam.in |
| **Right to grievance redressal** | If you are unhappy with how we handle your data, you can file a grievance | Email hello@vachanam.in (Vinay Rongala, Grievance Officer) |
| **Right to complain to the Data Protection Board** | If you are not satisfied with our response, you can approach the Data Protection Board of India | dpb.gov.in |

### How the process works

1. You email hello@vachanam.in with your request.
2. We verify your identity (we will ask you to confirm your phone number via OTP and may request a photo of a government-issued ID).
3. We acknowledge your request within 48 hours.
4. We complete your request within 7 calendar days.
5. We log every request in our audit system for compliance purposes.

Identity verification is necessary to prevent someone else from requesting your data. We will never ask for more identification than needed.

Withdrawing consent for a specific purpose (such as follow-up calls) does not affect the processing that already happened before withdrawal, and does not affect your ability to book future appointments.

---

## 10. Children's Data

Patients under 18 years of age may only book appointments through a parent or legal guardian. The parent or guardian must be the one speaking on the call or must have authorized the booking.

We do not separately collect age, date of birth, or any data specifically about minors beyond what is collected for any patient (name, phone, complaint summary, appointment). The phone number used for booking a minor's appointment will be the parent's or guardian's phone number.

If we become aware that we have collected personal data from a child without verifiable parental or guardian consent, we will delete that data within 7 days.

---

## 11. Cookies and Tracking

**We use only essential cookies.** Specifically:

- **Authentication token (JWT):** Stored in your browser's localStorage when a clinic staff member logs in. This is not technically a cookie, but it serves a similar purpose. It expires after 8 hours or 30 minutes of inactivity, whichever comes first.

**What we do NOT use:**

- No analytics cookies (no Google Analytics, no Mixpanel, no Hotjar)
- No advertising cookies or tracking pixels
- No third-party tracking scripts
- No fingerprinting

If we ever add analytics in the future, we will update this policy with 30 days notice, and any analytics tool will be listed in Section 6 above.

---

## 12. Changes to This Policy

If we make changes to this privacy policy:

- **Material changes** (new data collected, new processors, changed retention periods, changed rights): We will notify you at least 30 days before the change takes effect, via email (for clinic staff) and through the Vachanam platform.
- **Minor changes** (typo fixes, formatting, clarification without substance change): Updated immediately with a new "Last updated" date.

You can always find the current version of this policy at app.vachanam.in/privacy.

The previous version of this policy will be archived at docs/legal/privacy-policy-archive/ with its effective date range.

---

## 13. Effective Date

This privacy policy is effective as of **2026-06-04**.

---

## Additional Regulatory Notes

- **DPDP Rules:** The Digital Personal Data Protection Rules were notified on 14 November 2025. The full compliance deadline is 13 May 2027. Vachanam is on track to meet this deadline. This policy will be updated as additional guidance is published by the Data Protection Board or the Ministry of Electronics and Information Technology.
- **Data Fiduciary vs Data Processor:** Under DPDP Act 2023 Chapter II, the clinic is the Data Fiduciary (they decide why patient data is processed -- to manage appointments). Vachanam is the Data Processor (we process patient data on the clinic's documented instructions per our Data Processing Agreement). Both share responsibility for keeping your data safe.
- **Significant Data Fiduciary (SDF):** The SDF threshold and data localization requirements are pending a separate notification from the central government. Vachanam monitors these developments and will comply when applicable. As of this policy's effective date, Vachanam does not meet the expected SDF threshold.
- **Data residency:** Telephony (Vobiz), cache (Upstash), and voice compute (Fly.io, LiveKit) operate within India. Speech-to-text (Soniox, United States; Sarvam AI backup, India), text-to-speech (smallest.ai) and the AI language models (Google Gemini) operate globally. Database (Neon) and backend API (Render) operate in Singapore. The DPDP Act 2023 permits cross-border transfer of personal data except to countries specifically restricted by the central government (none of our vendors' countries are restricted as of this policy's date). We choose vendors with the strongest India or near-India data residency available for each function, every processor and its location is listed in Section 6, and each processor is bound by contractual data-protection terms (their enterprise terms of service and/or a data processing agreement) that restrict use of the data to providing the service to us.

---

**Contact us:**
- General: hello@vachanam.in
- Privacy and grievances: hello@vachanam.in (Vinay Rongala, Grievance Officer)
- Response time: 7 calendar days for data subject requests; 48-hour acknowledgment

*Vachanam -- "Healing starts with being heard."*

© 2026 Vachanam (Vinay Rongala), Hyderabad, India. All rights reserved.
