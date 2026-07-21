# Prompt grounding and demo latency — 2026-07-21

## What the production calls proved

- “పంటి సమస్య” became “పని సమస్య” in the stored Soniox transcript. The LLM did
  not invent that word; it followed a bad STT final. The correct controls are
  healthcare context, clinic vocabulary, and explicit ambiguity repair.
- A new symptom could inherit the previous doctor because `doctor_id` was only
  overwritten after a successful single-doctor route. It is now cleared before
  routing begins.
- Reminder instructions included literal parameter names and function
  signatures. Those are removed, and the TTS boundary now blocks internal
  execution text independently of model compliance.
- Latest measured stages were approximately 0.41–0.44s STT final,
  0.58s end-of-turn, 0.57–1.05s LLM TTFT, and 0.17–0.59s TTS first audio.

## Why POML-like structure helps—but is not enforcement

Microsoft POML provides semantic sections such as role, task, examples, and
output format. Vachanam uses the same structural idea without adding a runtime
dependency. Markup improves hierarchy and maintainability; it does not guarantee
obedience. Therefore truth-critical behavior is also enforced in Python state,
tool boundaries, and the final speech stream.

Reference: https://github.com/microsoft/POML

## Soniox latency and accuracy

Soniox v5 supports endpoint latency levels 0–3. Higher levels finalize sooner
but can split long speech and slightly reduce recognition accuracy. Manual
finalization is appropriate with client VAD, but Soniox recommends about 200ms
of silence before finalize to balance latency and accuracy. Context supports
structured `general` keys and domain-specific `terms`; both are now used.

References:

- https://soniox.com/docs/stt/rt/endpoint-detection
- https://soniox.com/docs/stt/rt/manual-finalization
- https://soniox.com/docs/stt/concepts/context

“Sub-200ms” usually describes provisional streaming tokens or network/model
processing under controlled conditions. It is not the same as a stable,
semantically complete end-of-turn transcript. Vachanam targets the caller's
first audible response and logs every contributing stage.

## Pricing margin decision

The 10–20% first-three-month margin is customer acquisition spend, not a safe
steady-state margin. Standard plan prices retain roughly 40% at the existing
conservative full-usage cost model. For a voice-AI product with telephony and
per-minute inference cost, 40% is a reasonable early floor; target 60%+ as
volume, routing, and vendor pricing improve. Pure software benchmarks often sit
around 70–80%, but applying that immediately to a usage-heavy voice service
would overprice early clinics.
