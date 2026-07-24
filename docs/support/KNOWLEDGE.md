# Vachanam — Product Knowledge (chatbot grounding document)

This is the support assistant's single source of truth about the whole product.
Facts only. No vendor/tool names (stack confidentiality). Display prices only.
If something is not covered here, the assistant must NOT guess — it forwards
the question to the human support team.

## What Vachanam is

Vachanam is an AI phone receptionist for Indian clinics. Tagline: "Healing
starts with being heard." A patient calls the clinic's normal phone number and
an AI agent answers in the patient's language (Telugu first), understands what
they need, matches the right doctor, books an appointment with a token number,
confirms it on the call, puts it on the doctor's Google Calendar, and the
clinic manages the day's queue in a web app. Built for dental clinics, skin
clinics, and diagnostic centres. Not for hospitals or emergency care.

Why clinics use it: a busy receptionist misses 20–30% of calls; each missed
call is a lost consultation (₹300–500). Vachanam answers every call, 24×7,
including lunch hours, evenings, and holidays.

## How a patient call works, end to end

1. Patient dials the clinic's number (a dedicated business number Vachanam
   provisions, or the clinic's existing number forwarded to it).
2. The AI answers within about a second, in the clinic's chosen voice, greets
   returning patients by name, and speaks the clinic's name.
3. The patient says what they need in natural speech — no keypad menus.
4. The AI matches the health need to the right doctor (never gives medical
   advice), checks that doctor's availability, and offers a time.
5. On confirmation it assigns a token number atomically — double-booking is
   impossible by design — and repeats the token and time back to the patient.
6. A calendar event is created for the doctor (patient first name + last 4
   phone digits + token only, never health details).
7. The whole call typically finishes in under 4 minutes.
8. If the patient asks for a human, or clearly keeps wanting one, the AI
   transfers to the clinic's own contact number. Vachanam is not an emergency
   service and never handles emergencies.

Patients can call again to cancel or reschedule; the token and calendar update
automatically. A booking is only held while the call confirms it — if a call
drops before confirmation, the slot is freed immediately for others.

## Languages

Seven Indian languages plus English: Telugu, Hindi, English, Tamil, Kannada,
Malayalam, Marathi, Bengali — included on EVERY plan (Odia removed 2026-07-24).
Each patient's
language is remembered for their next call. A caller can ask mid-call to
switch language and the agent continues in the new language.

## Plans and pricing (GST currently waived)

| Plan | Price | Included calling | Doctors | Languages | Extras |
|---|---|---|---|---|---|
| Lite | ₹1,999/month | 150 minutes (≈55 calls) | up to 3 | all 7 | treatment follow-up calls; AI calls capped at 10 minutes |
| Starter | ₹5,999/month | 700 minutes (≈250 calls) | up to 3 | all 7 | treatment follow-up calls; AI calls capped at 10 minutes |
| Clinic (most popular) | ₹9,999/month | 1,500 minutes (≈540 calls) | up to 5 | all 7 | treatment follow-up calls |
| Multi | ₹17,999/month | 3,000 minutes (≈1,080 calls) | unlimited | all 7 | WhatsApp confirmations + reminders |

- Overage on every plan: ₹5 per minute beyond included minutes, billed with
  the next invoice.
- Extra phone number: ₹1,999/month. Extra branch: ₹7,999/month (a branch is a
  fully separate clinic setup — own number, doctors, staff; data never mixes).
- Included minutes reset monthly and do not carry over.
- GST is currently waived, so invoices do not add a GST charge.

## Free trial

14 days, no card required, 300 included minutes (≈100 calls). When the trial
ends or the minutes run out, calls pause until a plan is activated. Around day
12 the owner receives a payment link. Trial clinics get the full feature set
of the Clinic plan to evaluate.

## Getting started (onboarding)

1. Register on the website with clinic name, owner email, and password; verify
   the email with a one-time code.
2. Add doctors: name, specialization, working days and hours, and booking
   style — token queue (numbered walk-in line, high volume) or fixed time
   slots. Set a daily token limit per doctor.
3. Vachanam provisions the clinic's dedicated phone number (the team assists;
   this includes standard telecom KYC which can take up to a day).
4. Connect the doctor's Google Calendar in Settings (optional but
   recommended).
5. Optionally record a 5–15 second voice sample per language in Settings so
   the AI speaks in the clinic's own voice (Clinic and Multi plans).
6. Test-call the number; go live.

## Doctors

- Each doctor has working days, start/end hours, specialization, a booking
  style (token queue or time slots), and a daily token limit (default 50).
- Doctor caps by plan: Lite 1, Starter 3, Clinic 5, Multi unlimited. Adding a doctor
  beyond the cap prompts an upgrade.
- Doctor leave: mark leave dates in the app under Doctor leave. Vachanam then
  automatically CALLS the affected booked patients and rebooks them onto
  another suitable time or doctor, so nobody shows up to a closed door.

## Queue, walk-ins, attendance (the clinic web app)

- The Queue page shows today's bookings per doctor in token order with live
  status. Reception marks each patient Arrived, Seen, or No-show with one tap.
- Walk-in patients are added from the Walk-in page and get the next token in
  the same queue — phone bookings and walk-ins never collide.
- A TV display mode shows "Now serving" token numbers for the waiting room
  (open the TV link on any screen).
- The app works on any phone, tablet, or computer through the browser; no
  install from an app store is needed (it can be added to the home screen).

## Patients

- Vachanam keeps one record per patient phone number: name, language, visit
  history. Returning callers are greeted by name and booked faster.
- A caller can book for someone else (parent, child); the AI asks who the
  appointment is for.
- The Patients page lets staff search patients and see their booking history.
- Patient personal data is NEVER shared across clinics. Each clinic sees only
  its own patients.

## Treatments and follow-up calls (Clinic and Multi plans)

- After a visit, the doctor or reception can record a visit note: what was
  done, what is next, and the next reporting date.
- If a next visit is due, Vachanam automatically calls the patient near that
  date, asks the doctor's follow-up question (e.g. "is the pain reducing?"),
  relays the answer back to the doctor in the app, and helps the patient book
  the next visit.
- The doctor can type a reply in the app and Vachanam speaks it to the
  patient on the next call — a two-way loop without the doctor dialing anyone.
- One-time visitors don't need any of this: select one or many patients in
  the treatment list and use End treatment — they leave the list and any
  pending follow-up calls stop. Ending a treatment never deletes patient
  details; permanent erasure is done separately with the Delete button on
  the Patients page (with a confirmation, and it cannot be undone).

## Reminders and calendar

- Booked patients get an automatic reminder call about 30 minutes before
  their appointment.
- Every booking lands on the doctor's Google Calendar (first name + last 4
  digits + token only). If the calendar write fails the booking itself fails
  cleanly — the calendar and the queue never disagree.
- Notifications never contain health details.

## Dashboard and analytics (owner)

- Today and recent-period bookings, calls answered, minutes used and
  remaining, show-rate, cancellations.
- Lifetime totals and this-month counts; a peak-hours heatmap showing the
  busiest weekday/hour blocks over the last 14 days.
- Minutes are shown as REMAINING for the month. No revenue estimates are
  shown.

## Billing and payments

- Payments are processed by Razorpay (RBI-authorised): UPI, credit/debit
  cards, net banking. Vachanam never stores card details.
- Activate or change a plan from Settings → Plan & billing. Upgrades take
  effect immediately; the price difference is adjusted on the next invoice.
- Overage minutes (₹5/min) appear on the next month's invoice.
- Refunds and cancellation terms are published at the website's Refunds page;
  subscription can be cancelled anytime and stays active till the period ends.

## Data safety, security and DPDP compliance (clinics' due-diligence questions — answer these confidently)

All of this is published at vachanam.in/privacy, vachanam.in/data-handling,
and the signable Data Processing Agreement at vachanam.in/dpa.

- DPDP: Vachanam operates as a Data Processor under India's Digital Personal
  Data Protection (DPDP) Act 2023; the clinic is the Data Fiduciary. Patient
  data is processed only to book and manage appointments on the clinic's
  instructions. A signable DPA is at vachanam.in/dpa. Grievance/privacy
  contact: privacy@vachanam.in.
- Isolation: every record carries the clinic's branch ID and every query is
  scoped to it — one clinic can never see another clinic's patients, calls,
  or bookings. Automated cross-clinic access tests run on every code change.
- Who can see data: role-based within the clinic (receptionist, doctor,
  owner each see only what their role needs). Even Vachanam's platform
  administrator is locked out of patient-data screens; production access is
  limited to the founder (acting Data Protection Officer) and every such
  access is audit-logged.
- What is collected: first name, phone, age/gender if given, plus token,
  doctor, date, time. The spoken health concern is used during the call only
  to route to the right doctor — it is not saved on the booking record.
- NOT a medical records system: no fields exist for diagnoses,
  prescriptions, test results, scans, or documents. Optional treatment
  follow-up notes are appointment-continuity text visible only to the
  patient's own clinic.
- Calls are NOT recorded. Voice is processed in real time and discarded;
  only a text transcript is kept, phone-masked before saving, for up to 90
  days, visible only to the patient's own clinic, then auto-deleted.
- Storage & encryption: the database runs on SOC 2-audited infrastructure in
  Singapore, encrypted at rest with AES-256; every connection uses TLS.
  Voice-call infrastructure and the temporary token cache (counters that
  expire the same day) run in Mumbai, India.
- Never sold, never used to train AI: no ads, no data sales, no training AI
  models on patient data — AI providers are used only via paid enterprise
  APIs whose terms prohibit training on submitted data.
- Payments: Razorpay (RBI-authorised aggregator) processes clinic
  subscription payments; it never sees patient data and Vachanam never
  stores card details.
- Calendar & notifications: the doctor's calendar event carries only first
  name + last-4 of phone + token number; no notification ever contains
  health details.
- AI disclosure: the agent says at the start of every call that it is the
  clinic's AI assistant; it never gives medical advice; emergencies surface
  the clinic's own emergency contact.
- Retention: booking identity data 2 years after last activity, then
  anonymized (anonymous statistics remain for the clinic); masked
  transcripts 90 days; audit log (IDs only, no names) 7 years. Clinics can
  erase a patient on demand (Patients page → Delete), and a clinic owner can
  delete the whole clinic and all its data from Settings — permanent.
- Breach response: a written, rehearsed runbook — affected clinics notified
  within 24 hours, the Data Protection Board within 72 hours (committed in
  the DPA).
- Account security: login tokens expire after 8 hours and are revoked on
  logout; sensitive endpoints are rate-limited; every significant action is
  written to an append-only audit log.

## What Vachanam does NOT do

- No medical advice, diagnosis, triage, or prescriptions — ever. The AI books
  appointments only.
- Not an emergency service; it never handles 108-style emergencies.
- No electronic medical records (EMR/EHR), no insurance claims, no video
  consultations, no patient payment collection.
- WhatsApp booking confirmations are planned but not live yet.

## Troubleshooting quick answers

- "Calls are not being answered": check the dashboard Monitoring page for
  system status; if the number was just provisioned, telecom activation can
  take up to a day; otherwise raise a ticket — the team responds quickly.
- "Can't log in / forgot password": use Forgot password on the sign-in page;
  a reset code goes to the owner email.
- "Didn't get the signup code": check spam; codes expire in 10 minutes;
  request a new one.
- "Minutes ran out": calls pause on trial; on paid plans calls continue at
  ₹5/min overage. Upgrade any time from Settings.
- "AI spoke the wrong language": each caller's language preference is
  remembered; the caller can say, in their language, "speak in Hindi" (etc.)
  and the agent switches if the plan includes that language.
- "Patient says they cancelled but the slot looks booked": cancellations by
  phone update the queue immediately; refresh the Queue page.

## Support

- This chat: every conversation is logged as a ticket automatically; if the
  assistant cannot answer, the human team is notified and replies in the app
  (Support → My tickets) and by email.
- Email: support@vachanam.in.
- Typical first response within a few business hours; urgent call-affecting
  issues are prioritised.
