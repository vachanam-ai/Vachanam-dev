# Telugu lines review — flag & rewrite

> **STATUS: Vinay's versions APPLIED 2026-06-15** (A1–A13 + B1–B23). Two copy-paste
> corruptions were corrected on the way in: **B6** `समस्या` (Devanagari) → `సమస్య`;
> **B7** `検మించాలండి` (Japanese `検`) → `క్షమించాలండి`. The tables below are the
> ORIGINAL prompts for reference — to change a line again, just say which # + new text.

Every Telugu line the agent speaks. **Fill the "Your natural version" column** for any
that sound robotic; leave blank to keep. I'll apply your versions verbatim at the exact
`file:line`. `{clinic}` / `{patient}` / `{doctor}` / `{time}` / `{date}` are filled at runtime — keep them.

Two groups:
- **A. Hardcoded** — spoken verbatim (highest priority; these are 100% under your control).
- **B. Prompt templates** — examples the AI mirrors; rewording these steers the AI's style.

---

## A. Hardcoded utterances — `agent/livekit_minimal/agent.py`

| # | line | Current Telugu | Meaning | Your natural version |
|---|------|----------------|---------|----------------------|
| A1 | 144 | నమస్కారం! {clinic} కి స్వాగతం. నేను క్లినిక్ AI అసిస్టెంట్‌ని. మీకు ఏ విధంగా సహాయపడగలను? | New-caller greeting ("how may I assist you" — formal) | |
| A2 | 151 | నమస్కారం {patient} గారు! {clinic} కి తిరిగి స్వాగతం. నేను క్లినిక్ AI అసిస్టెంట్‌ని. ఏం సహాయం కావాలి అండి? | Returning-patient greeting ("what help do you need" — casual) | |
| A3 | 120 | ఒక్క నిమిషం, చూస్తాను అండి. | Filler: "one minute, I'll check" | |
| A4 | 121 | ఒక్క క్షణం ఆగండి, చూస్తున్నాను. | Filler: "hold a moment, I'm checking" | |
| A5 | 122 | చూస్తాను అండి, ఒక్క సెకను. | Filler: "I'll check, one second" | |
| A6 | 123 | సరే అండి, ఒక్కసారి చూస్తాను. | Filler: "okay, let me have a look" | |
| A7 | 106 | నమస్కారం! క్షమించండి, ఈ సేవ ప్రస్తుతం తాత్కాలికంగా అందుబాటులో లేదు. దయచేసి క్లినిక్‌ని నేరుగా సంప్రదించండి. ధన్యవాదాలు. | Service-blocked (paused/expired clinic) | |
| A8 | 157 | నమస్కారం {patient} గారు! ఇది {clinic} క్లినిక్ నుండి రిమైండర్ కాల్. ఈరోజు {time}కి {doctor} గారితో మీ అపాయింట్‌మెంట్ ఉంది. మీరు వస్తున్నారా? | Outbound reminder call | |
| A9 | 163 | నమస్కారం {patient} గారు! {clinic} క్లినిక్ నుండి కాల్ చేస్తున్నాము. {date}న {doctor} గారు సెలవులో ఉండటం వల్ల మీ అపాయింట్‌మెంట్ క్యాన్సిల్ అయింది. క్షమించండి. వేరే రోజు బుక్ చేయమంటారా? | Outbound rebook (doctor on leave) | |
| A10 | 1718 | క్షమించండి, మన సమయం అయిపోతోంది. మీ బుకింగ్ ఖరారు చేద్దాం. | Solo-plan time-almost-up warning | |
| A11 | 1724 | ధన్యవాదాలు అండి, ఉంటాను! | Solo-plan call-end goodbye | |
| A12 | 95 | ఈ కాల్ నాణ్యత మెరుగుదల కోసం రికార్డ్ చేయబడుతుంది. | Recording notice (only if recording on — off in prod) | |
| A13 | 277 | ప్రతి రిప్లై గరిష్టంగా రెండు చిన్న వాక్యాలు… డిస్క్లోజర్ మళ్ళీ చెప్పవద్దు. ఒక ప్రశ్న మాత్రమే ఒకసారి అడగండి. | Brevity instruction to the AI (not spoken to patient) | |

---

## B. Prompt example lines the AI mirrors — `agent/prompts/system_prompt.py`

| # | line | Current Telugu | Meaning | Your natural version |
|---|------|----------------|---------|----------------------|
| B1 | 158 | డాక్టర్ గారు రేపు ఉదయం ఖాళీగా ఉన్నారు. పది గంటలకి వస్తారా? | Availability offer | |
| B2 | 160 | సరే అండి, రేపు పది గంటలకి మీ అపాయింట్‌మెంట్ ఫిక్స్ అయింది. టోకెన్ నంబర్ మూడు. | Confirming a booking | |
| B3 | 162 | మీకు ఏం ఇబ్బందిగా ఉంది అండి? | Asking the problem | |
| B4 | 163 | అయ్యో, ఆ టైంకి కుదరదు అండి. సాయంత్రం నాలుగు గంటలకి అయితే ఖాళీ ఉంది, వస్తారా? | Slot not available | |
| B5 | 165 | ధన్యవాదాలు అండి, రేపు కలుద్దాం! | Closing | |
| B6 | 213 | మీకు ఏం ఇబ్బందిగా ఉంది అండి? | Asking problem (vague request) | |
| B7 | 216 | క్షమించండి అండి, మా క్లినిక్‌లో అది చూడరు. మేము పంటి, స్కిన్, షుగర్ సమస్యలు మాత్రమే చూస్తాము. | Out-of-scope reply | |
| B8 | 220 | దానికి ఇషితా గారు చూస్తారు, ఆవిడ షుగర్ స్పెషలిస్ట్ | Naming the doctor | |
| B9 | 226 | ఏ రోజు, ఏ టైంకి రాగలరు అండి? | Asking preferred day/time | |
| B10 | 239 | మీ టోకెన్ నంబర్ ఎనిమిది అండి. | Token number announce | |
| B11 | 243 | రేపు మూడున్నరకి మీ అపాయింట్‌మెంట్ ఫిక్స్ అయింది. | Appointment time confirm | |
| B12 | 255 | పేషెంట్ పేరు చెప్పండి. | Ask patient name | |
| B13 | 256 | వయసు ఎంత? | Ask age | |
| B14 | 263 | పేషెంట్ పేరు వినయ్, వయసు ఇరవై ఎనిమిది — ఈ details confirm చేయమంటారా? | Name+age read-back | |
| B15 | 268 | మీరు కాల్ చేస్తున్న నంబర్‌కే బుకింగ్ సేవ్ చేస్తాను, సరేనా? | Confirm caller phone | |
| B16 | 296 | మీ అపాయింట్‌మెంట్ బుక్ అయింది. టైంకి వచ్చేయండి. ధన్యవాదాలు, ఉంటాను అండి! | Success + close | |
| B17 | 305 | మీకు ___ గారితో ___న అపాయింట్‌మెంట్ ఉంది. | Reschedule/cancel read-back | |
| B18 | 323 | క్యాన్సిల్ చేయమంటారా? | Confirm cancel | |
| B19 | 329 | ఇంకేమైనా కావాలా అండి? | Anything else? | |
| B20 | 336 | ఆ టైంకి Y గారు అందుబాటులో లేరు, కానీ X గారు ఉన్నారు | Named doctor busy | |
| B21 | 350 | సరే, మీ కోసం wait చేస్తాను | Wait acknowledgement | |
| B22 | 355 | క్షమించండి, మళ్ళీ చెప్పగలరా? | Garbled-input re-ask | |
| B23 | 201 | కొత్త అపాయింట్‌మెంట్ కావాలా, లేదా ఉన్నదాన్ని మార్చాలా అండి? | New-vs-existing intent question | |

---

**Notes:**
- A1 vs A2 are inconsistent — A1 is formal ("సహాయపడగలను"), A2 is casual ("ఏం సహాయం కావాలి అండి"). Likely you'll want both casual.
- Part of "robotic" is the **voice itself** (Sarvam vs smallest.ai padmaja) + pace, not just words — judge that separately from the WAVs.
