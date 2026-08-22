# Official Meta WhatsApp onboarding runbook

Verified against Meta's Embedded Signup v4 documentation on 2026-08-16.

Authoritative references:

- [Onboard customers as a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider)
- [Onboard WhatsApp Business app users (Coexistence)](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)
- [Embedded Signup version 4](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4)
- [Implement Embedded Signup](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation)

Embedded Signup v2 is deprecated on 2026-10-15. Vachanam uses v4 and Graph
API `v25.0` by default.

## 1. Meta account prerequisites

Before real clinic self-onboarding:

1. Vachanam's Meta Business Portfolio must be verified.
2. Vachanam must be approved as a Tech Provider or Solution Partner.
3. The Meta app must have Advanced Access for:
   - `whatsapp_business_management`
   - `whatsapp_business_messaging`
4. The app must be in Live mode.
5. The app must have a working WhatsApp webhook and session logging.
6. App Review must contain one video proving template management and another
   proving message sending.

Do not use a pasted permanent access token to onboard a customer. The clinic
must grant access through Embedded Signup, and the resulting one-time code is
exchanged server-to-server.

## 2. Create the Embedded Signup v4 configuration

In Meta for Developers:

1. Open the Vachanam app.
2. Add **Facebook Login for Business** and the **WhatsApp** product.
3. Create a new Facebook Login for Business configuration.
4. Choose the **WhatsApp Embedded Signup** variation and **Cloud API** product.
5. Access token type must be **System-user access token** with
   `response_type=code` exchanged server-side. Either expiry Meta offers is
   fine: a 60-day business integration token, or never-expire (verified
   2026-08-22). `wa_connect` stores `token_expires_at: null` when Meta
   returns no `expires_in`, and both `wa_service.token_for` and
   `WaConnectCard` skip the expiry gate on a null - a never-expiring token
   never trips reauthorization.
6. Request only the two permissions listed above.
7. Save the configuration ID as `META_CONFIG_ID`.

Facebook Login for Business settings:

- Client OAuth login: enabled
- Web OAuth login: enabled
- Enforce HTTPS: enabled
- Embedded Browser OAuth Login: enabled
- Strict Mode for redirect URIs: enabled
- Login with JavaScript SDK: enabled
- Allowed domain: `vachanam.in`
- Valid OAuth redirect URI: the exact HTTPS URI Meta shows for the v4
  configuration; never use `workers.dev` as the Vachanam product origin.

The JavaScript SDK must use the configured Graph version. The browser logs the
session event and sends the short-lived code plus session asset IDs to the
backend immediately. Meta's authorization code expires in about 30 seconds.

## 3. Configure the webhook

Use the API custom domain (verified live 2026-08-21 — `/health` 200, the
webhook route answers a bad `hub.verify_token` with 403):

`https://api.vachanam.in/webhooks/whatsapp`

`https://vachanam-backend.onrender.com/webhooks/whatsapp` is the same service
and remains a valid fallback. `https://vachanam.in` is the clinic-facing
product origin, not the webhook. Do not use
`vachanam.vinayrongala.workers.dev`.

Set the callback verify token to the same random secret stored as
`META_WEBHOOK_VERIFY_TOKEN`. Subscribe the app to:

- `messages`
- `message_template_status_update`
- `account_update`
- `history`
- `smb_app_state_sync`
- `smb_message_echoes`

Vachanam also calls `POST /{WABA_ID}/subscribed_apps` for every newly connected
clinic. App-level field subscription and per-WABA app subscription are both
required.

## 4. Production environment

Set these only in the backend secret store:

```text
META_APP_ID=<Meta app ID>
META_APP_SECRET=<Meta app secret>
META_CONFIG_ID=<Embedded Signup v4 configuration ID>
META_GRAPH_VERSION=v25.0
WHATSAPP_SELF_SERVE_LIVE=true
META_WEBHOOK_VERIFY_TOKEN=<random webhook verification secret>
```

`META_APP_ID`, `META_CONFIG_ID`, and the graph version are public configuration
and may be returned to the browser. `META_APP_SECRET`, clinic tokens,
registration PINs, and the webhook verify token must never leave the backend.

Build the frontend with `VITE_WHATSAPP_LIVE=true` at the same release. The
frontend and backend gates must be enabled together; the backend remains the
authoritative check.

The old platform `META_ACCESS_TOKEN`, `META_WABA_ID`, and
`META_PHONE_NUMBER_ID` may remain only for an explicitly controlled test
number. They are not the clinic onboarding mechanism.

## 5. Clinic onboarding paths

The dashboard presents two explicit choices.

### A. Existing WhatsApp Business app number (Coexistence)

Requirements:

- WhatsApp Business app version 2.24.17 or newer.
- The clinic completes Embedded Signup from its own Meta account.
- The clinic consents to contacts/history sharing if it wants those imported.

The browser launches signup with:

```js
extras: {
  setup: {},
  featureType: "whatsapp_business_app_onboarding",
  sessionInfoVersion: "3"
}
```

Expected finish event:

`FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`

Server actions, in order:

1. Exchange the code with app ID and app secret.
2. Verify the selected phone belongs to the granted WABA.
3. Subscribe the WABA to the Vachanam app.
4. **Skip** `/{PHONE_ID}/register`; Meta already registered the app number.
5. Start contacts and history synchronization within 24 hours.
6. Encrypt the clinic-specific business integration token and store it on that
   clinic branch only.

Contacts and history sync are one-shot operations. History can contain up to
180 days and thousands of messages. Vachanam intentionally retains only the
last 10 messages in a thread and ignores messages older than 30 days. Error
`2593109` means the clinic declined history sharing and is shown as declined,
not as a failure.

Coexistence has a fixed throughput of 20 messages/second. Messages sent in the
mobile app are free; Cloud API messages follow Meta's pricing. A message sent
to the app does not itself open the Cloud API 24-hour customer-service window.

### B. New Cloud API number

The browser launches standard Embedded Signup without the Coexistence feature
extras. Expected finish event: `FINISH`.

Server actions, in order:

1. Exchange the code server-to-server.
2. Verify the WABA/phone relationship.
3. Subscribe the WABA to the app.
4. Generate a cryptographically random six-digit PIN.
5. Call `POST /{PHONE_ID}/register` with
   `{"messaging_product":"whatsapp","pin":"......"}`.
6. Encrypt the token and PIN at rest.

A connection is not reported as successful if asset verification, WABA
subscription, or required registration fails.

## 6. Billing ownership

After Embedded Signup, the clinic must add a payment method to its own WABA in
WhatsApp Manager. Meta charges the clinic for Cloud API messaging. Vachanam
does not collect or proxy the clinic's Meta card details. The dashboard links
to WhatsApp Manager and records the clinic owner's acknowledgement; Meta does
not provide this integration with a public billing-verification result that
would make the acknowledgement authoritative.

## 7. Required lifecycle behavior

- `smb_message_echoes`: mirror receptionist messages sent from the Business
  app; never feed them back to the bot as patient messages.
- edit/revoke: update or remove the matching stored message.
- `ACCOUNT_OFFBOARDED` or `PARTNER_REMOVED`: immediately clear the clinic token,
  asset IDs, queued WhatsApp deliveries, and stored WhatsApp conversations.
- `ACCOUNT_RECONNECTED`: require the owner to complete Embedded Signup again.
- Dashboard disconnect: unsubscribe the app from the WABA when Meta permits,
  then clear local credentials and conversations even if the remote call fails.

Every webhook is routed by the receiving `phone_number_id`; patient numbers
are never used to choose a clinic.

## 8. Acceptance checklist

For one test WABA of each type:

1. Finish Embedded Signup and confirm no secret appears in browser responses.
2. Confirm the selected phone is visible under the granted WABA.
3. Confirm `subscribed_apps` contains Vachanam.
4. Standard flow: confirm registration succeeded.
5. Coexistence flow: confirm no registration request was made and both sync
   requests were started before the 24-hour deadline.
6. Send a patient message and verify it reaches only the matching clinic.
7. Send from the Business app and verify one echo appears without a bot reply.
8. Disconnect/offboard and verify chats, token, IDs, and queued deliveries are
   removed.
9. Add the clinic's payment method and send one approved utility template.
