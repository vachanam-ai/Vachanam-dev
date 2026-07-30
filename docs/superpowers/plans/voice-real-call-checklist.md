# Voice prompt redesign — real-call validation checklist

> Companion to `docs/superpowers/specs/2026-07-30-voice-prompt-redesign-design.md`
> (§10 matrix) and its plan. The unit-testable rows are covered by
> `tests/unit/test_prompt_stress.py`, `test_grounding_gate.py`,
> `test_stt_clinic_map.py`, `test_lang_anchor.py`, `test_grounded_prompt_v21.py`.
> The rows below need **audio** — Vinay places real PSTN calls, humanizer scores
> the transcript (R1–R9). Real-call evidence only; no sim/judge tuning.

## How to run (kill-switch A/B)

All four flags default **OFF** — production is unchanged until each is flipped.
Enable **one flag at a time**, place the calls, compare against the same call
with the flag off, then decide. Order matters: the prompt (`voice_prompt_v21`)
assumes the gate + anchor exist, so validate in this order:

1. `voice_grounding_gate` (Phase 2)
2. `voice_lang_anchor` (Phase 4)
3. `voice_stt_clinic_map` (Phase 3)
4. `voice_prompt_v21` (Phase 1) — flip **only after** 1 & 2 pass.

For each: set the env flag on the Fly agent, place the calls below, pull the
transcript, confirm the structured logs fired (`grounding_gate_*`,
`grounding_tripwire_blocked`, `stt_clinic_remap`, `language_switched`), and
have humanizer score the transcript before flipping the next.

## Universal pass criteria (every call)

- **Warmth** — one human acknowledgement then the action, same turn; no robotic openers.
- **Never wrong** — no time/fee/day/outcome the agent didn't get from a tool this turn.
- **No over-questioning** — each thing asked once; captured details never re-asked.
- **Speed** — no dead air; a "checking…" cue only when a real read runs.
- **Name pronunciation** — doctor/patient names spoken, not spelled letter-by-letter.
- **No invented times** — if `grounding_tripwire_blocked` never fires spuriously on a
  legitimate confirmation ("…booked for 11:30"), the confirm-grounding fix (1abb93e) holds.

## Audio-only scenario rows (§10)

| # | Scenario | What to do on the call | Pass |
|---|---|---|---|
| 3 | Fast speaker, several needs in one breath | Say "book skin doctor tomorrow morning and also what's the fee" in one rush | Handles the latest complete need, remembers/asks the rest; doesn't drop or scramble |
| 5 | Noisy / garbled environment | Call from a noisy place, mumble one turn | One "could you say that near the phone?" → one clarification → offers to take a message; never loops |
| 7 | Wrong number / called by mistake | "Sorry, wrong number" | One brief kind correction + warm close; no booking forced |
| 9 | Self-echo (agent hears its own TTS) | Call on a speakerphone that bounces audio | Agent does not answer itself; `echo_turn_discarded` fires; no self-talk loop |
| 11 | Interrupted mid-confirmation | Talk over the confirmation | Restates only the unheard detail, not the whole thing |
| 13 | Rambling / shy / doesn't know the clinic | Ramble, be vague about what you want | Calm help, captures the need once, no interrogation |
| 19 | DTMF / keypad / non-speech noise | Press keypad digits mid-call | Non-speech ignored; no phantom "turn"; conversation continues |

## Drift-specific rows (audio confirmation of Phase 4)

| # | Scenario | What to do | Pass |
|---|---|---|---|
| 16 | Switch then many turns | Ask to switch to English, then continue **5+ turns** | Stays English every turn — no revert to Telugu by turn 2 (the #466 bug). Confirm `language_switched` once, no re-switch |
| 16b | Switch mid-booking | Switch language while giving name/age | Only the language changes; doctor/day/time/name/age stay captured |
| 2 | Homophone / misheard doctor name | Say a doctor's name slightly wrong | Snaps to the real roster name (`stt_clinic_remap` logged) or asks one either/or — never books the wrong doctor |

## Regression rows to spot-check (already unit-covered, confirm on audio)

- **1** ambiguous request → one either/or, then offer what you can (no "didn't understand" loop).
- **12** correct the time → agent re-checks that exact time, doesn't argue.
- **14** complaint → apologise + log + "what can I do", never the off-topic redirect.
- **15** distress → human transfer + the clinic's **own** emergency contact, never 108.
- **17** family member / double-book → finds the existing booking first, asks for-whom.
- **18** past slot → offers the next real time, never a gone one.
- **20** tool fails → "let me check / take a message", never a guessed number.

## Sign-off

A flag flips to prod only when: the audio rows above pass, humanizer's transcript
score does not regress vs the flag-off call, and the structured logs confirm the
new path actually ran. Record the decision in `docs/CHANGELOG.md` and memory.
