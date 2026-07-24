# Temporary admin-only call recording

## Active scope

`RECORDING_ENABLED=true` permits audio capture only when the inbound caller or
outbound callee matches `ADMIN_PHONE` after phone-number normalization. It does
not record a clinic's ordinary patient calls. Blocked-service calls and every
non-admin call explicitly start with `record=False`.

For an allowed test call, the first spoken segment says that the call will be
recorded for quality testing. The entire pre-session opening finishes before
capture begins. If that playout fails, recording fails closed for the call. The
LiveKit recording request enables audio and explicitly disables transcript,
trace, and log capture. The consent ledger writes `consent_type=recording` with
notice version `admin-test-audio-1.0`.

## LiveKit prerequisite and retention

In the LiveKit Cloud project, enable **Project settings → Data and privacy →
Agent observability**. Agent recordings upload after the session and appear in
Agent Insights. LiveKit documents 30-day retention and automatic deletion.
Their Build plan may retain anonymized data longer for service improvement;
paid plans fully delete data after 30 days. This mode must therefore be used
only by the configured admin test participant—not with real patients.

References:

- https://docs.livekit.io/deploy/observability/insights/
- https://docs.livekit.io/deploy/observability/data/

## Enable

```powershell
flyctl secrets set RECORDING_ENABLED=true -a vachanam-agent
```

Verify the restarted worker logs contain:

```text
recording_test_mode=True recording_scope=admin_only
```

On an admin test call, verify these ordered events:

```text
recording_scope active=True scope=admin_only
recording_notice_completed before_capture=True
```

Then confirm an audio artifact appears in LiveKit Agent Insights after the call.
Make one non-admin test call and confirm `recording_scope active=False`; it must
not create an Insights recording.

## Disable when Vinay says to stop

```powershell
flyctl secrets set RECORDING_ENABLED=false -a vachanam-agent
```

Verify the restarted worker reports:

```text
recording_test_mode=False recording_scope=admin_only
```

Disabling stops new captures immediately. Existing LiveKit artifacts follow the
provider's retention schedule; the flag does not retroactively delete them.
