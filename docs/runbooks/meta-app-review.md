# Meta App Review and Tech Provider approval

This checklist matches Embedded Signup v4 and the implementation in
`backend/services/wa_connect.py`.

## Prerequisites

- Verified Vachanam Business Portfolio.
- Tech Provider approval.
- App connected to the verified portfolio.
- Privacy, terms, data deletion, and data-handling URLs are public.
- App Review Advanced Access for `whatsapp_business_management` and
  `whatsapp_business_messaging`.
- App in Live mode before onboarding real clinics.

## Review videos

Record two short, unbroken videos using demo data only.

1. **Management permission:** owner completes Embedded Signup, opens the
   templates page, creates a UTILITY appointment template, and shows the same
   pending template in WhatsApp Manager.
2. **Messaging permission:** send an approved appointment template from the
   connected clinic WABA and show it arrive on the test handset. Reply from the
   handset and show the response in Vachanam Conversations.

For Coexistence review, also show the clinic can keep using the WhatsApp
Business app and that an app-sent message is mirrored in Vachanam.

## Accurate permission justification

### `whatsapp_business_management`

Vachanam is a Tech Provider. Each clinic explicitly grants access to its own
WhatsApp Business Account through Embedded Signup. Vachanam uses the
permission only to verify granted WABA/phone assets, subscribe that WABA to
webhooks, register a new Cloud API number when required, initiate consented
Coexistence data synchronization, and create/list/delete the clinic's
appointment utility templates. Coexistence app numbers are not re-registered.

### `whatsapp_business_messaging`

Vachanam sends approved transactional appointment messages for bookings,
reschedules, cancellations, reminders, and follow-ups. It replies to patient
messages within Meta's customer-service rules. It sends no marketing and no
diagnosis, prescription, treatment notes, or other medical advice.

## Data handling disclosure

- Data: patient WhatsApp number/profile name and message text sent to the
  clinic.
- Purpose: clinic appointment operations and human handoff.
- Storage: clinic-scoped records in the configured database.
- Working conversation history: last 10 messages, and no imported history
  older than 30 days.
- Deduplication identifiers: Redis for 24 hours.
- No sale, advertising use, data brokers, or cross-clinic sharing.
- Deletion: patient erasure, clinic disconnect, Meta offboarding, and account
  lifecycle rules remove applicable data.

Never claim that Vachanam processes no personal data, reads no history, or
does not use Coexistence. Those statements would contradict the product.

## Webhook fields after approval

Subscribe to `messages`, `message_template_status_update`, `account_update`,
`history`, `smb_app_state_sync`, and `smb_message_echoes`. Every clinic WABA is
also subscribed programmatically during onboarding.

## Reviewer instructions

Give Meta a throwaway clinic-owner login containing demo data only. Tell the
reviewer exactly where to:

1. connect an existing Business app number or a new Cloud API number;
2. create and view a utility template;
3. trigger a booking confirmation;
4. open the patient conversation;
5. disconnect WhatsApp and observe that chats disappear.

Do not give a reviewer access to a real clinic or real patient data.
