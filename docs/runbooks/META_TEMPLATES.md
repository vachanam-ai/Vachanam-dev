# WhatsApp lifecycle templates

Vachanam discovers approved templates per clinic WABA. The owner dashboard can
submit the canonical English templates below with **Install required
templates**. Template variables are positional, so their order is a runtime
contract.

Do not create translated copies. Lifecycle templates are deliberately English
only; free-form WhatsApp chat may still follow the patient's language.

| Purpose | Canonical name | Variables, in order | Quick replies |
| --- | --- | --- | --- |
| Confirmation | `vachanam_booking_confirm` | patient, clinic, doctor, date, time, Google Maps link | Reschedule, Cancel |
| Reschedule | `vachanam_booking_reschedule` | patient, doctor, date, time | Reschedule, Cancel |
| Cancellation | `vachanam_booking_cancel` | patient, doctor, date, time | none |
| Reminder | `vachanam_appt_reminder` | patient, doctor, date, time, Google Maps link | Reschedule, Cancel |
| Follow-up | `vachanam_followup` | patient, doctor, clinic-approved message | none |
| Clinic location | `vachanam_clinic_location` | clinic, address, Google Maps link | none |
| Post-visit review | `vachanam_feedback` | Google review link | none |
| In-chat rating | `vachanam_rating_ask` | clinic | 1, 2, 3, 4, 5 |
| Doctor leave | `vachanam_leave_rebook` | doctor, date | Reschedule |

Meta rejects a template whose first or last content is a variable. Keep text
after the final `{{n}}`. The source of truth for exact submitted copy is
`backend/services/wa_template_admin.py::SYSTEM_TEMPLATE_DEFINITIONS`.

Existing clinic templates may use different names. The registry discovers
those by purpose and fits the values to the approved body parameter count. In
particular, Venkateshwara's existing `confirm` and `remainder` templates are
supported; the spelling `remainder` is treated as a reminder.

After Meta approves or rejects a submitted template, the
`message_template_status_update` webhook invalidates that clinic's template
cache. An unapproved or missing template disables only that notification; it
never causes a fake booking or changes appointment state.
