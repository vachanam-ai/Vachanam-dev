# How Vachanam Keeps Your Patients' Data Safe

*A plain-language answer for doctors and clinic owners — every claim here describes what our software actually does, and is backed by our public [Privacy Policy](https://api.vachanam.in/privacy), [Data Processing Agreement](https://api.vachanam.in/dpa), and [Data Handling document](https://api.vachanam.in/data-handling).*

---

## The one-paragraph answer

Your clinic's data belongs to your clinic. Vachanam stores the minimum needed to book appointments — a first name, a phone number, a one-line reason for visit, a token — encrypted at rest and in transit, in a database partition that only your clinic can read. We never record calls, never store medical records, never sell or share data with advertisers, and never use patient data to train AI. Data that stops being needed is erased automatically by software, not by promise. Under India's DPDP Act 2023, **you** remain the owner (Data Fiduciary); we are your processor, bound by a signed Data Processing Agreement.

---

## 1. What we store — and what we refuse to store

| We store (per booking) | We NEVER store |
|---|---|
| Patient first name | Call recordings — audio is converted to text in real time and discarded |
| Phone number | Medical history, diagnoses, prescriptions, test results |
| One-line reason for visit ("tooth pain") | Aadhaar, PAN, or any government ID |
| If you use treatment follow-ups: your own short visit notes + the patient's follow-up answer | Documents, scans, lab reports, prescriptions — we are not an EMR |
| Token number, doctor, date, time | Payment details of patients (we never collect patient payments) |
| Age/gender if the patient volunteers it | Anything about a patient who called but did not confirm a booking |

Less data stored = less data that can ever leak. This is deliberate.

## 2. Where the data lives

- **Database:** Neon PostgreSQL (Singapore region), encrypted at rest with AES-256, running on SOC 2–audited infrastructure.
- **In transit:** every connection — patient call signalling, dashboard, API — is TLS-encrypted.
- **Voice processing:** happens in real time in Mumbai (our voice servers run in India); audio is never written to disk.
- Every vendor we use, what it sees, and where it operates is listed publicly in our Privacy Policy §6. No vendor is added without updating that list first.

## 3. Your clinic's data is walled off from every other clinic

This is our **Rule 1**, enforced in code on every single database query, cache key, calendar event, and log line:

- Every record carries your clinic's ID; every read and write is filtered by it. Clinic A can never see clinic B's patients — there is no code path that allows it.
- Our automated test suite (700+ tests, run on every change) includes tests that deliberately try to cross clinic boundaries and must fail.
- **Even Vachanam's own founder is locked out** of patient-data screens by role checks. Platform administration does not include browsing your patients.

## 4. Who can see what, inside your clinic

| Role | Sees |
|---|---|
| Receptionist | Today's queue, patient names/phones for their own branch |
| Doctor | Their own calendar events: first name + last-4 digits of phone + token only |
| Clinic owner | Everything above + analytics for their own clinic |
| Vachanam staff | Backend systems for troubleshooting only — every access lands in an audit log kept 7 years |

Logins use short-lived tokens (8-hour hard expiry, revoked instantly on logout), rate limiting protects against password attacks, and every significant action is written to an append-only audit log.

## 5. Backups — your data survives failures

- The database keeps a **continuous change history** (every write is journalled), giving **point-in-time restore**: if something goes wrong, we can restore the database to any moment within the restore window — not just "last night's backup."
- Storage is redundant at the infrastructure level (cloud-grade replication), separate from the restore history.
- Booking integrity has a second, independent guarantee: token numbers are assigned atomically through a locking layer, so even a mid-failure retry can never produce a double booking.

## 6. Data leaves when its purpose ends — automatically

A daily software job (not a policy PDF) enforces retention:

| Data | Lifetime | What happens |
|---|---|---|
| Patient identity | 2 years after last visit | Name/phone/age erased, record anonymised — your aggregate statistics survive |
| Call transcripts (text only, phone numbers masked before saving) | 90 days | Deleted |
| Temporary booking counters | Same day | Expire automatically |
| Voice audio | Never stored | — |
| Audit log (IDs only, no names) | 7 years | Deleted |

## 7. If something ever goes wrong

We maintain a written, rehearsed breach-response runbook:

- **You are notified within 24 hours** of a confirmed breach affecting your clinic — by email and phone.
- The Data Protection Board of India is notified within 72 hours, as the DPDP Act requires.
- Patients exercising their legal rights (access / correction / erasure / complaint) get an acknowledgement within 48 hours and completion within 7 days — the process is published in our Privacy Policy, with a named Grievance Officer.

## 8. The legal frame — in your favour

- **DPDP Act 2023:** your clinic is the Data Fiduciary (the data is yours); Vachanam is your Data Processor, acting only on your documented instructions.
- We sign a **Data Processing Agreement** with every clinic — it binds us to everything on this page contractually, not just as marketing.
- We are not an EMR and never become one: no clinical records, no insurance data, no patient billing. If a feature would require them, it doesn't get built.

## 9. Treatment follow-ups — the same discipline applies

If your clinic uses the follow-up feature, a little more data exists — all of it yours:

- **Doctor's visit notes** (what was done, what's next): entered by your doctor, visible only inside your clinic, deleted when the patient record is erased.
- **Follow-up calls are consent-gated in code:** if the patient declined follow-up calls at booking (or withdraws later), the dispatch job skips them — the phone simply never rings. This is enforced by software, with an automated test proving it.
- **The patient's answer** comes back as a short summary for the doctor — it never appears in logs, notifications, or calendar events, and is cleared with the patient record.
- Nothing about follow-ups changes the ban list: still no diagnoses fields, no prescriptions, no documents, no lab data.

## 10. How this compares to the big health-tech platforms

Doctors often benchmark against Practo — a fair bar. Structural comparison:

| Dimension | Big platforms (e.g., Practo) | Vachanam |
|---|---|---|
| Data collected | Full health profiles, consultation records, medicine orders, payments | First name, phone, complaint line, token — booking only |
| Business model risk | Consumer app monetising engagement across clinics | B2B tool; your data has zero value to us beyond serving your clinic |
| Certifications | ISO 27001 (organisational certification) | Runs entirely on SOC 2 / ISO-certified infrastructure (Neon, Google Cloud, AWS-backed vendors); Vachanam's own ISO certification is on our roadmap as we grow |
| Call recordings | Varies by product | Never — audio is not stored, full stop |
| Cross-clinic visibility | Platform-wide patient accounts | Impossible by design — no shared patient identity across clinics |
| Retention | Policy-based | Enforced by daily software job, publicly documented |
| Data selling / ads | "We don't sell your data" | Same commitment — and we hold ~1% of the data they do, so the promise is cheaper to keep |

The honest one-liner for a doctor: *"Practo protects a mountain of health data with a big security team. Vachanam's approach is to never build the mountain — we hold only what a receptionist's register holds, protect it with the same grade of encryption and isolation, and delete it on a timer."*

## 11. Verify us — don't take our word

- Privacy Policy: **api.vachanam.in/privacy**
- How we handle data (full lifecycle): **api.vachanam.in/data-handling**
- Data Processing Agreement: **api.vachanam.in/dpa**
- Questions or a security review before signing: **hello@vachanam.in** — we'll walk your IT person through anything on this page.

---

*Vachanam — "Healing starts with being heard."*
© 2026 Vachanam (Vinay Rongala), Hyderabad, India.
