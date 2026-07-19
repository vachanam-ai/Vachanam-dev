---
title: Data privacy, security and DPDP compliance
audience: both
category: technical
tags: privacy, dpdp, data, security, patient, encryption, breach, retention, delete, compliance
---
Every fact below comes from Vachanam's published Privacy Policy (vachanam.in/privacy), the plain-language data-handling guide (vachanam.in/data-handling) and the signable Data Processing Agreement (vachanam.in/dpa).

**Is patient data safe? Who can see it?** Each clinic's data is fully isolated — every record carries the clinic's branch ID and every query is scoped to it, so one clinic can never see another clinic's patients, calls, or bookings. Automated cross-clinic access tests run on every code change. Within a clinic, access is role-based: receptionists, doctors, and owners each see only what their role needs. Even Vachanam's own platform administrator is locked out of patient-data screens; production access is limited to the founder (acting Data Protection Officer) and every such access is audit-logged.

**Is Vachanam DPDP compliant?** Yes — Vachanam operates as a Data Processor under India's Digital Personal Data Protection (DPDP) Act 2023; the clinic is the Data Fiduciary. Vachanam processes patient data only to book and manage appointments on the clinic's documented instructions. A signable Data Processing Agreement is available at vachanam.in/dpa. Grievance/privacy contact: privacy@vachanam.in.

**What patient data is collected?** Only what booking needs: first name, phone number, and age/gender if given, plus the token, doctor, date and time. What a patient says about their health issue is used during the call only to route them to the right doctor — it is not saved on the booking record. Vachanam has no fields for diagnoses, prescriptions, test results, scans or documents — it is not a medical-records system. Optional treatment follow-up notes (what was done this visit, what comes next) are appointment-continuity notes visible only to the patient's own clinic.

**Are calls recorded?** No. Audio is processed in real time to understand the words and then discarded — no voice recording is ever stored. A text transcript (phone numbers masked before saving) may be kept up to 90 days for call quality, visible only to the clinic itself, and is auto-deleted by a daily job.

**Where is data stored and is it encrypted?** The database is hosted on SOC 2-audited infrastructure in Singapore, encrypted at rest with AES-256; every connection uses TLS in transit. Voice-call infrastructure and the token cache run in Mumbai, India. The temporary token cache stores only counters that expire the same day.

**Is data sold, shared or used to train AI?** Never. No selling, no ads, no training AI models on patient data. AI providers are used only via paid enterprise APIs whose terms prohibit training on submitted data. Razorpay (RBI-authorised) processes clinic subscription payments and never sees patient data; Vachanam never stores card details.

**What do patients see in notifications and the doctor's calendar?** The doctor's calendar event contains only the patient's first name, last 4 digits of their phone, and the token number — never the health concern. No notification ever contains health details.

**Do patients know they are talking to an AI?** Yes — the agent discloses at the start of every call that it is the clinic's AI assistant, and it never gives medical advice, diagnoses, or prescriptions. Emergencies surface the clinic's own emergency contact.

**How long is data kept, and can it be deleted?** Booking identity data: 2 years after the patient's last activity, then automatically anonymized (the clinic keeps anonymous statistics). Masked transcripts: 90 days. Audit log (IDs only, no names): 7 years for compliance. Patients can be erased earlier on request. If a clinic leaves Vachanam, the owner can delete the clinic and all its data from Settings at any time — deletion is permanent.

**What happens if there is a data breach?** Vachanam follows a written, rehearsed breach-response runbook: affected clinics are notified within 24 hours and the Data Protection Board within 72 hours, as committed in the DPA.

When contacting support, please describe issues without pasting patient names, phone numbers, or health details.
