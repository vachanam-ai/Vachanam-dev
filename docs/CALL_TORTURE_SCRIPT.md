# Vachanam agent — manual call torture script

Audio-layer chaos the pytest suite CANNOT reach (Sarvam STT + Silero VAD +
smallest.ai TTS only exist on a real call). The tool/state layer is covered by
`tests/integration/test_torture_reschedule.py` + `test_torture_conversation.py`
(FIXLOG #286/#287). Run this by phone after each agent deploy.

For every call, afterwards pull the transcript:
`python <scratch>/txscript.py` (latest 3 `call_quality.transcript` rows) — the
truth is the transcript + `flyctl logs` (`lat_*`, tool `reason`/`instruction`),
never memory.

Pass = the ONE bad outcome never happens: dead air, a crash, a wrong/duplicate
booking, a "technical issue" line, or a repeated confirmation.

---

## A. Timing / speech reality

| # | Do this on the call | PASS looks like |
|---|---|---|
| A1 | Book, but **pause 3-4s mid-sentence** ("నాకు… … రేపు… … పదింటికి") | Agent waits, does not restart the question or talk over you |
| A2 | Trail off with hesitation ("పది గంటలకి… కుదరదేమో…") then finish | Agent gives a short listening cue, lets you finish, no flow restart |
| A3 | Speak very fast, whole request in one breath | Books correctly, one confirmation |
| A4 | Speak very slowly with gaps between every word | No premature turn-end; waits for the real end |

## B. Interruption / barge-in

| # | Do this | PASS |
|---|---|---|
| B1 | While the agent speaks the confirmation, **cut in with a new time** | Stops within ~0.4s, takes the new time |
| B2 | Backchannel only ("హా", "mm", "సరే") while it talks | Does NOT cut itself off; keeps speaking |
| B3 | Interrupt, then go silent | Recovers, re-asks once, no dead air |
| B4 | Rapid-fire interrupt 3× in a row | Never loops, never freezes |

## C. Background noise / multiple voices

| # | Do this | PASS |
|---|---|---|
| C1 | TV / traffic behind you the whole call | Books; may ask once to come closer, never twice |
| C2 | A second person talks over you mid-call | Follows the primary speaker; no wrong data booked |
| C3 | Someone else answers a question for you | Confirms detail with you before booking |

## D. Ambiguous / indirect asks (exploratory ≠ command — #287)

| # | Say exactly | PASS |
|---|---|---|
| D1 | "గురువారం 12కి వస్తే ఎలా ఉంటుంది?" (what if I come Thu 12?) | Checks, ANSWERS, then asks "shall I book?" — does NOT book silently |
| D2 | "అప్పుడు డాక్టర్ ఉంటారా?" (will the doctor be there then?) | Availability answer + offer, no booking yet |
| D3 | "at 3" (no AM/PM) | Reads as 3 PM (daytime), never 3 AM |
| D4 | "morning sometime" (no exact time) | Offers a morning slot to pick; no timetable dump |

## E. Contradictions / repeats (state recovery — #286/#287)

| # | Sequence in ONE call | PASS |
|---|---|---|
| E1 | Book 10:00 → "actually 11:00" → "no, back to 10:00" | Ends at 10:00, exactly one booking |
| E2 | "reschedule to 11" → "no, cancel it entirely" | Cancels; one clean line; nothing booked |
| E3 | "cancel it" → (agent cancels) → "cancel it" again | Second: "already cancelled", never "technical issue" |
| E4 | "cancel it" → "no wait, move it to Friday 12" | Offers to book Fri 12 fresh; no bare error |
| E5 | Reschedule the SAME time it's already at | "already confirmed for that time", no failure |
| E6 | Change the time 5× quickly | Follows every change; final one wins; no loop |
| E7 | Immediately after "booked", say "change it to 3pm" | Reschedules; never "you already have an appointment" |

## F. Existing-booking / identity

| # | Do this | PASS |
|---|---|---|
| F1 | Already have a booking that day → try to book again | "you already have an appointment at X" up front, not after full flow |
| F2 | Ask "what appointments do I have?" after rescheduling | Only the CURRENT time shows; the old slot is gone |
| F3 | Book for a family member (different person, same phone) | Takes their name/age; both bookings coexist |

## G. Language

| # | Do this | PASS |
|---|---|---|
| G1 | Start Telugu, switch fully to English mid-call | Follows to English (switch tool), voice stays the clinic voice |
| G2 | Tenglish ("flat, time, ok" mixed in Telugu) | Stays in Telugu, does not flip to English |
| G3 | Speak an unsupported language 2-3 turns | Asks ONCE which language, does not loop |

## H. Latency (report the numbers, don't tune blindly)

- H1 First call after a deploy: agent speaks within ~2s (Neon keepalive, #285).
- H2 Every later call: first word ~1.5-2s; interrupt-to-stop ~0.4s (#280).
- H3 "one moment / okay అండి" filler plays instantly on a slot check (#282).
- After the call, grab `lat_first_word`, `lat_eou`, `lat_llm ttft`, `lat_tts`
  from `flyctl logs -a vachanam-agent`.

---

**Regression rule:** any failure here → reproduce it in the tool/state suite if
it lives there, add the test, fix, redeploy. If it is purely audio (VAD/STT
timing), log the transcript evidence and tune ONE parameter with a re-measured
call (per `voice-latency-optimized` — never blind-tune).
