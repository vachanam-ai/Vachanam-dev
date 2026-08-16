# Meta Embedded Signup v4 implementation audit

Date: 2026-08-16

## Result

The Vachanam code path now follows Meta's Tech Provider Embedded Signup v4
sequence for both standard Cloud API onboarding and WhatsApp Business app
Coexistence. No production deployment was performed as part of this audit.

## Implemented

| Official requirement | Implementation | Proof |
|---|---|---|
| Use Embedded Signup v4 | Config endpoint reports v4; frontend SDK uses the configured Graph version | `test_wa_signup_config.py`, `useEmbeddedSignup.test.jsx` |
| Code exchange is server-to-server | App secret is read only by `wa_connect._exchange_code` | response secret-absence tests |
| Join code and session event | Hook waits for both results and accepts the two documented finish events | hook tests |
| Do not trust browser asset IDs | Backend lists WABA phone numbers and verifies the selected ID | `test_asset_ids_are_verified_server_side` |
| Subscribe every WABA | `POST /{WABA_ID}/subscribed_apps` is mandatory | `test_webhook_subscription_is_mandatory` |
| Register standard numbers with PIN | Six-digit random PIN, encrypted at rest | `test_cloud_api_flow_registers_with_encrypted_six_digit_pin` |
| Never re-register Coexistence number | Registration is skipped for the Coexistence finish event | `test_coexistence_skips_registration_and_starts_both_syncs` |
| Start Coexistence sync within 24h | Contacts/history requests and deadline are stored; retry is deadline-gated | connect service/router tests |
| Mirror app messages | `smb_message_echoes` enters the clinic thread and does not trigger the bot | webhook integration test |
| Handle history consent decline | Error 2593109 is recorded as declined | webhook integration test |
| Minimize imported history | Older than 30 days discarded; last 10 retained; IDs deduplicated | webhook integration test |
| Handle Meta offboarding | Token, asset IDs, pending deliveries, and WhatsApp chats are removed | webhook integration test |
| Retire manual token paste | Endpoint is hidden and returns HTTP 410; UI contains no token form | router and component tests |
| Clinic pays Meta directly | Dashboard links to WhatsApp Manager; no card data enters Vachanam | component test |
| Token expiry | Exchange expiry is recorded; expired credentials fail closed and UI requests reauthorization | token/component tests |
| Graph version is centralized | All WhatsApp Graph calls use `services/meta_graph.py` | repository search |

## External account work still required

The repository cannot create or approve these Meta assets. At audit time the
local `.env` has no usable values for:

- `META_APP_ID`
- `META_APP_SECRET`
- `META_CONFIG_ID`
- `META_GRAPH_VERSION`
- `META_WEBHOOK_VERIFY_TOKEN`

After Tech Provider approval, the account owner must:

1. create the v4 Facebook Login for Business configuration;
2. obtain Advanced Access for both WhatsApp permissions;
3. set the exact allowed domain/redirect URI and publish the app Live;
4. configure and verify the webhook;
5. subscribe all six documented webhook fields;
6. store the five values above in the backend secret store;
7. run one real standard-number and one real Coexistence acceptance test;
8. have each clinic add its own WABA payment method.

Until these steps are complete, the clinic dashboard intentionally reports
WhatsApp signup as unconfigured.

## Sources

- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider>
- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users>
- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4>
- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation>
