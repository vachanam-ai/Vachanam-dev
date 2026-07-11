# Vachanam Terms of Service

**Effective date:** 2026-06-04
**Last updated:** 2026-06-04

These terms govern the relationship between Vachanam and the clinic ("you") that subscribes to our service. They are written in plain English so that a clinic owner without a lawyer can understand them.

By subscribing to Vachanam, you agree to these terms.

---

## 1. What Vachanam Does

Vachanam is an AI-powered appointment booking service for clinics in India. When a patient calls your clinic's number, the call is forwarded to our AI agent. The AI answers in Telugu, Hindi, or English, understands the patient's health concern, matches them to the correct doctor, checks availability, assigns a token number (with no double-booking), and creates a calendar event for the doctor.

Your receptionists manage the daily queue through a mobile-friendly web app (Progressive Web App). You, the clinic owner, see analytics on a dashboard.

**What Vachanam does NOT do:**

- We do not give medical advice, diagnoses, prescriptions, or treatment recommendations.
- We do not store electronic medical records (EMR/EHR) or clinical notes.
- We do not process insurance claims.
- We do not collect payments from patients.
- We do not provide video consultations.
- We are not a replacement for the doctor-patient relationship.

---

## 2. Your Obligations as a Clinic

### 2.1 You are the Data Fiduciary

Under the Digital Personal Data Protection (DPDP) Act 2023, your clinic is the "Data Fiduciary" for your patients' personal data. You determine the purpose of data processing (managing patient appointments). Vachanam acts as your "Data Processor" -- we process patient data only on your documented instructions as set out in the Data Processing Agreement (DPA) signed during onboarding.

As the Data Fiduciary, you are responsible for:

- Informing your patients that their calls are handled by an AI assistant and that their name and phone number will be used for booking.
- Responding to patient data requests that come directly to you (we will assist you; see Section 3.3).
- Ensuring your use of Vachanam complies with applicable law.

### 2.2 Account security

- Each staff member (owner, receptionist) must have their own Google account for login. Sharing login credentials between staff members is not permitted.
- You are responsible for removing staff members' access promptly when they leave your clinic.
- You must notify us at hello@vachanam.in within 24 hours if you suspect any unauthorized access to your Vachanam account.

### 2.3 Acceptable use

You agree NOT to use Vachanam to:

- Provide medical advice to patients through the AI agent.
- Store patient clinical records, test results, or prescriptions in the Vachanam system.
- Share patient personal information obtained through Vachanam outside the platform for purposes unrelated to the patient's appointment.
- Attempt to access another clinic's data on the Vachanam platform.
- Interfere with or disrupt the service for other clinics.

### 2.4 Emergency handling

Vachanam's AI agent detects emergency keywords (e.g., "chest pain," "unconscious," "breathing difficulty") and provides your clinic's emergency contact number to the caller. The AI does NOT provide emergency medical advice, does NOT call ambulances, and does NOT triage emergencies. You must ensure your clinic's emergency contact number is accurate and updated in your Vachanam settings.

---

## 3. Vachanam's Obligations

### 3.1 Service availability

We target 99.4% uptime for the overall service. This is not a guaranteed SLA for MVP -- it is our engineering target. We will notify you via email if we experience planned downtime (at least 24 hours notice) or unplanned outages (as soon as we become aware).

### 3.2 Data security

We implement reasonable security safeguards as required by DPDP Act 2023 Section 8, including:

- Encryption in transit (TLS 1.2+) for all data
- Encryption at rest (AES-256 disk encryption via our database provider)
- Strict data isolation between clinics at the database level (every query is scoped to your clinic only)
- Role-based access control (owner sees analytics; receptionists see only the queue)
- Append-only audit logging of all sensitive actions with 7-year retention
- Rate limiting and bot protection

Our full security measures are documented in our Data Processing Agreement.

### 3.3 Breach notification

If we discover a breach of personal data that affects your clinic:

- We will notify you within 24 hours of confirming the breach (email + phone call to your registered owner email/phone).
- We will notify the Data Protection Board of India within 72 hours, as required by DPDP Act 2023 Section 11.
- We will provide you with a written incident report within 14 days, including: what happened, what data was affected, what we did to contain it, and what we changed to prevent recurrence.

### 3.4 Data subject request support

When a patient contacts us or you with a data access, correction, or deletion request:

- We will complete the request within 7 calendar days.
- We can provide you with an extract of all data we hold for a specific patient in your clinic (audit-logged, identity-verified).
- We will not process a patient data request without verifying the requester's identity.

### 3.5 Data return and deletion on termination

When you cancel your subscription (see Section 4.4):

- We will provide you with a full export of your clinic's data in a standard format (JSON) within 14 days of your request.
- We will permanently delete all your clinic's data from our systems within 30 days of cancellation, except:
  - Audit log entries (retained for 7 years per regulatory requirements)
  - Billing records (retained per Indian tax law requirements)
- We will confirm deletion in writing to your registered email.

---

## 4. Subscription and Payment

### 4.1 Plans

Vachanam offers three subscription plans:

| Plan | Monthly price | Included minutes | Max doctors |
|---|---|---|---|
| **Solo** | INR 1,999/month + INR 3/min overage | First 100 minutes free | 1 |
| **Clinic** | INR 7,999/month flat | 2,100 minutes included | 3 |
| **Multi** | INR 16,999/month flat | 4,200 minutes included | 6 |

Overage charges (minutes beyond the included amount) are billed at the end of each billing cycle. Solo plan overage: INR 3/min. Multi plan overage: INR 2.50/min.

Full pricing details, including per-call cost breakdowns and what each plan includes, are available at vachanam.in.

### 4.2 Free trial

Every new clinic gets a 14-day free trial with up to 1,000 minutes of AI call handling. No credit card is required to start the trial. On day 12, we will send a payment link to your registered email. If payment is not completed by end of day 14, the service pauses until payment is received.

### 4.3 Payment

All payments are processed through Razorpay, a Reserve Bank of India (RBI) authorized payment aggregator. We accept UPI, credit cards, debit cards, and net banking. Vachanam does not directly store your payment card details -- Razorpay handles all payment data per PCI-DSS standards.

### 4.4 Cancellation

You can cancel your subscription at any time by emailing hello@vachanam.in. Upon cancellation:

- Your service continues until the end of the current paid billing period.
- No refund is issued for the remaining days of the current billing period.
- Your data is handled per Section 3.5 above (export available for 14 days; deletion within 30 days).

---

## 5. Intellectual Property

Vachanam's software, AI models (as configured for the service), documentation, branding, and user interface are owned by Vachanam. Your subscription gives you a non-exclusive, non-transferable right to use the service for the duration of your subscription.

Your clinic's data (patient records, doctor schedules, booking history) remains your property. Vachanam claims no ownership over your data.

---

## 6. Limitation of Liability

To the maximum extent permitted by applicable Indian law:

- Vachanam's total liability to you for any claims arising from or related to the service is limited to the amount you paid to Vachanam in the 3 months immediately preceding the claim.
- Vachanam is not liable for indirect, incidental, special, consequential, or punitive damages, including but not limited to lost revenue, lost patients, or business interruption.
- Vachanam is not liable for any harm resulting from a patient relying on the AI agent for medical advice (the AI is explicitly instructed not to give medical advice; see Section 1).
- Vachanam is not liable for missed or incorrect bookings caused by factors outside our control (e.g., incorrect doctor schedule entered by the clinic owner, patient providing wrong information, telephony network failure).

Nothing in these terms excludes liability for fraud, willful misconduct, or death or personal injury caused by our negligence.

---

## 7. Governing Law and Jurisdiction

These terms are governed by the laws of India. Any dispute arising from these terms or your use of Vachanam will be subject to the exclusive jurisdiction of the courts in Hyderabad, Telangana, India.

Before filing a legal claim, both parties agree to attempt good-faith resolution via email correspondence for at least 30 days.

---

## 8. Termination by Vachanam

We may suspend or terminate your access to Vachanam if:

- You breach these terms and do not remedy the breach within 14 days of our written notice.
- You use the service for illegal purposes.
- You fail to pay subscription fees for more than 30 days past the due date.
- You attempt to access another clinic's data or interfere with the service.

In case of termination, your data is handled per Section 3.5 (export available for 14 days, deletion within 30 days).

---

## 9. Changes to These Terms

We will notify you at least 30 days before any material change to these terms, via email to your registered clinic owner email address. If you do not agree with the changes, you may cancel your subscription before the changes take effect.

Continued use of the service after the change takes effect constitutes acceptance of the updated terms.

---

## 10. Contact

- **General inquiries:** hello@vachanam.in
- **Privacy and data requests:** privacy@vachanam.in
- **Security concerns:** security@vachanam.in
- **Billing questions:** hello@vachanam.in

---

*Vachanam -- "Healing starts with being heard."*
