# Meta App Review + publishing — Vachanam

Owner: Vinay. Everything here happens in Meta's consoles; nothing in this file
needs a code change or a deploy.

Written 2026-08-10 after verifying the app-side preconditions against the live
Render host (results below). The spec this executes is
`docs/superpowers/specs/2026-08-02-whatsapp-tech-provider-design.md` §6.

## 0. What is already done

Verified live 2026-08-10 — re-check with `curl -o /dev/null -w "%{http_code}"`
if a deploy changes the backend:

| URL | Status | Meta needs it for |
|---|---|---|
| `/privacy` | 200 HTML | App settings → Privacy Policy URL (mandatory to publish) |
| `/terms` | 200 HTML | App settings → Terms of Service URL |
| `/data-deletion` | 200 HTML | App settings → Data Deletion Instructions URL |
| `/data-handling` | 200 HTML | Reviewer context on what we store |
| `/dpa` | 200 HTML | Clinic-facing processor agreement |
| `/webhooks/whatsapp` | 403 on a bad verify token | Webhook verification handshake |

Base host is `https://vachanam-backend.onrender.com`. **Not**
`api.vachanam.in` — that name is still NXDOMAIN, and a reviewer hitting a dead
host is an instant rejection. Use the Render host everywhere until DNS lands.

The 403 on `/webhooks/whatsapp` is correct behaviour, not a fault: the endpoint
is deployed and refusing a wrong `hub.verify_token`. With the right token it
returns the challenge.

Product-side, the flows a reviewer will ask to see are built and shipped to
master: Embedded Signup connect, manual connect, template create/list/delete,
and the system-template installer.

## 1. Order of operations

These are gated on each other. Doing them out of order wastes review cycles.

```
Business verification  ──►  App Review (2 screencasts)  ──►  App Mode: Live
        ▲
   needs GST certificate / incorporation proof  (TD-038: GSTIN not yet issued)
```

**Business verification is the real blocker.** Until the portfolio is verified,
the WABA is capped at 2 phone numbers and 250 business-initiated conversations
per day, and App Review for the two WhatsApp permissions cannot be submitted.

Start it at business.facebook.com → Settings → Security Centre → Start
verification. Takes 2–10 business days. If the GST certificate has not arrived,
incorporation proof plus a utility bill in the business name is usually
accepted — try that before waiting on GST.

**While you wait, bridge mode still works.** The pilot number runs on
Vachanam's own WABA with the platform token. `wa_service.token_for()` already
resolves per-branch, so switching a clinic to its own WABA later is a flag
flip, not a rewrite. You are not blocked from demoing or from onboarding the
first clinic by hand.

## 2. The two screencasts

This is the part you were stuck on. You said we had nothing to record — we do.
Two videos, one per permission. No narration required; Meta reads the actions,
not the audio. Screen-record at 1080p, keep each under ~3 minutes, and make
every click legible.

Meta also accepts a recording of the **API Setup page's cURL** or of WhatsApp
Manager for both of these. Use the product UI if you want the app to look real;
use cURL if you want it done in ten minutes. Either passes.

### Video A — `whatsapp_business_management` (template creation)

Record, in one unbroken take:

1. Log in to the Vachanam dashboard as a clinic owner.
2. Sidebar → **WhatsApp**. Show the connected card: the verified name, the
   WABA ID, the phone number ID.
3. Top bar → **+ New template**.
4. Fill it in on camera — name, category UTILITY, body with a `{{1}}`
   placeholder, an example value, one button. Let the live phone preview render.
5. Submit. Show the success toast and the new row appearing with a
   **pending** status chip.
6. Cut to WhatsApp Manager → Message templates. Show the same template name
   sitting there in review.

Step 6 is what actually proves the permission. Do not skip it.

### Video B — `whatsapp_business_messaging` (sending)

1. Show the recipient's phone, WhatsApp open, no message from the clinic.
2. In the dashboard, take a booking through to confirmation — or run
   `python scripts/wa_smoke.py <PHONE_NUMBER_ID> <TO_NUMBER>`, showing the
   terminal and the `messages` response with the returned message ID.
3. Cut back to the handset and show the message arriving.
4. Open **Conversations** in the dashboard and show the same message logged
   against the patient thread.

Both videos must show the SAME app that is under review, and the business name
on screen must match the portfolio name (`Vachanam`).

## 3. Permission justifications

App Review asks for a written reason per permission. Reviewers reject vague
answers. Paste these, edited only if something below stops being true.

**`whatsapp_business_management`**

> Vachanam is an appointment-booking platform for clinics in India. Each clinic
> connects its own WhatsApp Business Account through Embedded Signup. We use
> this permission solely to manage message templates on the connecting clinic's
> own WABA: creating the appointment-confirmation, reschedule, cancellation and
> reminder templates that clinic sends to its own patients, listing their
> approval status in our dashboard, and deleting templates the clinic no longer
> wants. We never read or modify templates on any WABA other than the one the
> clinic explicitly connected.

**`whatsapp_business_messaging`**

> We send transactional appointment messages on behalf of the connecting
> clinic, to that clinic's own patients, using approved utility templates:
> booking confirmation, reschedule, cancellation, and appointment reminders.
> Patients reply in the same thread to reschedule or cancel, and we handle
> those replies within the 24-hour customer service window. We send no
> marketing messages and no health information — templates carry appointment
> logistics only (name, doctor, date, time, clinic).

The "no health information" sentence is load-bearing for a medical-category
business. It is also true of our templates — keep it that way.

## 3b. The three submission sections

The submission page gates on Allowed usage, Data handling, and Reviewer
instructions. Every answer below is checked against what
`https://vachanam-backend.onrender.com/privacy` and `/data-handling` already
publish. Meta compares the two. Do not improve the wording in one place only.

### Allowed usage

A certification, not an essay: read each permission's allowed-usage statement
and tick it. For the two WhatsApp permissions the statements forbid using
Platform Data for advertising or ad targeting, selling or licensing it,
building profiles for anything other than the integration, and sharing it with
data brokers. None of that describes us, so certify truthfully.

The one to read slowly is the clause about using data only to provide the
integration the user expects. Ours is appointment booking for the clinic the
patient messaged — that is the whole of it.

### Data handling

| Their question | Our answer |
|---|---|
| Which Platform Data does the app access? | The patient's WhatsApp phone number, their WhatsApp profile name, and the content of messages they send to the clinic. |
| Do you store it? | Yes, minimally. Last 10 messages of the thread plus any in-progress booking in `whatsapp_sessions`, clinic-scoped. The WhatsApp message ID (identifier only, never text) cached 24h for delivery de-duplication. An unanswered patient question with name and number in `clinic_questions` so a human can reply. |
| How long? | Sessions: 30 days without a new message, or until the patient record is erased, whichever comes first. Message IDs: 24 hours. Questions: until the patient record is erased. Patient records: erased after 2 years of inactivity or on request. |
| Where? | Supabase Postgres in `ap-south-1` (Mumbai, India). AES-256 at rest, TLS in transit, SOC 2–audited infrastructure. |
| Do you transfer it to third parties? | No sale, no licensing, no data brokers, no advertising use. Infrastructure sub-processors only (hosting, database, cache), each listed in our published privacy policy, each contractually bound. |
| Purpose | To book, reschedule, cancel and remind patients about appointments at the clinic they messaged. Nothing else. |
| Access controls | Every row carries the clinic's `branch_id` and every query is scoped to it. Cross-clinic access attempts are covered by automated tests that run on every change. Vachanam's own platform administrator is locked out of clinic patient-data routes by role checks. |
| Deletion | `https://vachanam-backend.onrender.com/data-deletion` |

If Meta triggers a Data Protection Assessment, it is the same content at
greater length — answer from `/data-handling`, which is the authoritative
version, and never invent a control we do not have.

### Reviewer instructions

Paste this, with the real credentials filled in:

> Vachanam is an appointment-booking platform for clinics in India. Clinics
> connect their own WhatsApp Business Account and we manage message templates
> and send appointment messages on their behalf.
>
> Sign in at https://vachanam.in/login
> Email: <throwaway owner email>
> Password: <password>
>
> To review `whatsapp_business_management` (template management):
> 1. Sign in. In the left sidebar, click **WhatsApp**.
> 2. The card at the top shows the connected WhatsApp Business Account —
>    verified name, WABA ID and phone number ID.
> 3. Click **+ New template** in the top bar.
> 4. Enter a name, leave the category as UTILITY, type a message body using
>    {{1}} as a placeholder, supply an example value, and add a button.
> 5. Click Submit. The template is created on the connected WABA via the
>    Graph API and appears in the list with status "pending", which is the
>    review status read back from Meta.
> 6. The same template is visible in WhatsApp Manager under Message
>    templates for that WABA.
>
> To review `whatsapp_business_messaging` (sending):
> 1. From the same account, open **Conversations** in the left sidebar.
> 2. Appointment messages sent to a patient appear in the patient's thread.
> 3. A send is triggered whenever a booking is confirmed, rescheduled or
>    cancelled, and by the appointment reminder job. Each send uses an
>    approved UTILITY template on the clinic's own WABA.
>
> We send no marketing messages. Template content is appointment logistics
> only — patient first name, doctor, date, time, clinic name and token
> number. No health information is ever sent.

Attach Video A to the management permission and Video B to the messaging
permission, not both to one.

## 4. Test credentials for the reviewer

App Review requires a working login. Create a throwaway clinic-owner account
seeded with demo data, and put the email and password in the submission's test
credentials field. Do not give a reviewer a real clinic's account — that is
patient data under DPDP.

## 5. Publish: App Mode → Live

App dashboard → the App Mode toggle at the top → **Live**.

Before the toggle will flip, App settings → Basic needs: privacy policy URL,
terms URL, data deletion URL (all three verified in §0), app icon, category,
and a business portfolio linked.

**An unpublished app receives test webhooks only.** No real clinic message will
ever arrive while the app is in Development mode — this is the single most
common reason a "finished" WhatsApp integration receives nothing.

## 6. After publishing — do not skip

- WhatsApp → Configuration → Webhook fields: subscribe **`messages`**,
  **`message_template_status_update`**, **`account_update`**. Missing the
  second one means template approvals never update in our dashboard.
- **Each WABA must be subscribed to the app individually.** Connecting a clinic
  via Embedded Signup does this automatically (`_subscribe_app` in
  `backend/services/wa_connect.py` is a mandatory step of the connect flow, not
  best-effort). A WABA linked by hand in the console is NOT subscribed and will
  silently deliver nothing.
- Confirm `META_APP_ID`, `META_APP_SECRET`, `META_CONFIG_ID`,
  `META_WEBHOOK_VERIFY_TOKEN` are all set in Render. Missing values make the
  WhatsApp features no-op rather than error, so nothing will look broken.

## 7. Rejections we should expect, and the fix

| Rejection | Cause | Fix |
|---|---|---|
| "Unable to log in" | Test credentials expired or 2FA on the account | Fresh throwaway owner account, no 2FA |
| "Could not reproduce the permission use" | Video shows our UI but never Meta's side | Add the WhatsApp Manager / handset shot |
| "Privacy policy inaccessible" | Reviewer used `api.vachanam.in` | Every URL in the submission must be the Render host |
| "Business not verified" | §1 not finished | Nothing to fix — finish verification first |
| Template rejected as MARKETING | Category left at default in the console | Our API sends UTILITY; only hand-created templates drift |

## 8. What is genuinely blocked on Meta, and what is not

Blocked until verification + review + Live: real clinic numbers at any scale,
clinic self-onboarding through Embedded Signup, inbound patient messages.

Not blocked, available today: the pilot number on our own WABA in bridge mode,
template creation on that WABA, the full booking flow, and every voice feature.
