# Government and Public-Authority Data Request Policy

**Effective date:** 2026-08-10
**Owner:** Vachanam Grievance Officer — privacy@vachanam.in
**Applies to:** every request from any public authority — police, regulator,
court, tax authority, or agency of any government — for personal data held by
Vachanam.

Vachanam is a **Data Processor** under the Digital Personal Data Protection
Act 2023. The clinic is the **Data Fiduciary**. We hold patient data on the
clinic's instructions, not our own. That single fact drives most of what
follows: in almost every case the right recipient of a request for patient
data is the clinic, not us.

This policy is short on purpose. A policy we would not actually follow is
worse than none, because it is a promise made to regulators and to Meta.

---

## 1. Route every request to one place

No engineer, contractor, or support agent answers a public-authority request.
Anyone who receives one — by email, phone, in person, or served in writing —
forwards it unanswered to **privacy@vachanam.in** the same day and tells the
requester that Vachanam responds through that address only.

Do not confirm or deny whether a person is in our records. Confirming that a
named individual is a patient of a named clinic is itself a disclosure.

## 2. Review the legality of every request before responding

No data is disclosed until the Grievance Officer has confirmed all of:

- **The requester is who they claim to be.** Verified through an official
  channel, not a phone number or email supplied in the request itself.
- **The request is in writing** and cites the specific legal provision that
  compels disclosure.
- **The authority has jurisdiction** over Vachanam and over the data sought.
- **The request is specific.** A named individual and a defined time period.
  Bulk requests, standing access, and open-ended requests are refused.
- **The legal instrument actually compels us.** An informal request creates no
  obligation. We do not disclose voluntarily.

If any of these fail, the request is refused in writing with the reason.

## 3. Challenge requests we believe are unlawful

Where a request is overbroad, lacks a legal basis, is outside the authority's
jurisdiction, or would compel disclosure beyond what the law requires, we:

1. Push back in writing first, asking the authority to narrow it or state its
   legal basis more precisely.
2. Where the request remains unlawful and the amounts at stake justify it,
   obtain external legal counsel and challenge it through the available legal
   process before disclosing anything.
3. Comply only to the extent a valid order actually compels, and no further.

We do not treat pushback as optional politeness. It is the default first step.

## 4. Disclose the minimum, always

When disclosure is legally required:

- Only the specific records named in the order. Never a database export,
  never a whole table, never "everything about this person".
- Only the fields the order requires. If a token number answers the question,
  the phone number is not disclosed.
- Only the named individual's records. Other patients' data appearing in the
  same table is excluded before anything leaves.
- Never another clinic's data. Every record we hold is scoped to one clinic
  by `branch_id`; a request naming clinic A can never return clinic B's rows.
- Never voice recordings — we do not store call audio at all.

## 5. Notify the clinic, and the patient where we lawfully can

Because the clinic is the Data Fiduciary, we notify the clinic of any request
concerning its patients before disclosing, unless a valid order legally
prohibits us from doing so. Where the clinic is the correct recipient, we
redirect the authority to the clinic and tell the clinic we have done so.

Where we are not legally barred from doing so, the affected individual is
notified.

## 6. Document every request

The Grievance Officer records, for every request received — including those
refused and those withdrawn:

- date received, the authority, and the individual officer named
- the legal provision cited and a copy of the instrument
- what was requested and what, if anything, was disclosed
- the legality assessment and who made it
- whether the request was challenged, and the outcome
- whether the clinic and the individual were notified, and if not, why not

Records are retained for seven years. They are the evidence base for the
transparency reporting in §7 and for any later regulatory inquiry.

## 7. Transparency reporting

Once Vachanam serves live clinics, we publish an annual count of
public-authority requests received, refused, challenged, and complied with,
in aggregate and without identifying any individual. As of the effective date
of this policy, **we have received no such request**.

## 8. Meta Platform Data specifically

Data obtained through the WhatsApp Business Platform — a patient's WhatsApp
number, profile name, or message content — is treated exactly as above, with
one addition: where a request seeks Platform Data and we are not legally
prohibited from doing so, we notify Meta, because Meta's Platform Terms
require it and because Meta may have standing to challenge a request we
cannot challenge alone.

## 9. Review

Reviewed annually by the Grievance Officer, and immediately after any request
is received, so the first real request improves the policy rather than merely
testing it.
