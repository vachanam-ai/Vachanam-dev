"""Hardcoded spoken lines, per language.

These strings bypass the LLM and go straight to TTS, so they must be exact,
natural, and in the correct script (Rule 6: Telugu/target language in its own
script, never romanized). Placeholders {clinic}/{patient}/{doctor}/{time}/{date}
are filled at the call site.

LANGUAGE STATUS:
  - te (Telugu): REFERENCE — Vinay's hand-validated natural phrasing (the live
    clinic). Do NOT change without re-validation.
  - hi (Hindi): first-pass, reasonable everyday phrasing.
  - ta/kn/ml/mr/bn/or: FIRST-PASS, ⚠ NOT yet native-validated (Vinay 2026-06-15
    chose to scaffold all 7 now and refine per language, same flag-and-refine
    flow Telugu went through). Send each to a native speaker before that clinic
    goes live. See docs/telugu_static_lines.md for the review workflow.

`brevity` is an INSTRUCTION to the LLM (not spoken), so non-Telugu languages use
a plain-English directive — the model obeys it and still SPEAKS the target
language. Telugu keeps its original Telugu wording to leave the live path byte-
for-byte unchanged.
"""
from dataclasses import dataclass

from .languages import DEFAULT_LANG


@dataclass(frozen=True)
class Lines:
    service_blocked: str
    fillers: tuple[str, ...]
    disclosure_greeting: str   # {clinic}
    known_caller_greeting: str  # {patient} {clinic}
    reminder_greeting: str     # {patient} {clinic} {time} {doctor}
    rebook_greeting: str       # {patient} {clinic} {date} {doctor}
    cap_warning: str
    cap_goodbye: str
    brevity: str
    # Treatment follow-up call openings (default "" → agent falls back). _q asks the
    # doctor's question {message}; _noq is a generic post-treatment check-in.
    followup_greeting_q: str = ""    # {patient} {clinic} {message}
    followup_greeting_noq: str = ""  # {patient} {clinic}
    inbound_followup_greeting: str = ""  # {message} — disclosure + doctor's question
    # Honorific name prefix for greeting a recognized caller on the inbound
    # follow-up path (lifted verbatim from the validated known_caller_greeting
    # pattern — not new hand-written copy).
    followup_name_prefix: str = ""  # {patient}
    # Trimmed ONE-sentence inbound intros (Vinay 2026-07-10, verbatim): replace
    # the welcome+disclosure two-segment opening on the plain inbound path.
    # Optional — languages without them keep the two-segment composition.
    inbound_intro: str = ""        # {clinic}
    inbound_intro_known: str = ""  # {clinic} {patient}
    # Successful mutation confirmations. Empty keeps that language on the
    # normal LLM reply path; only native-reviewed templates should be filled.
    confirm_booked_token: str = ""   # {token} {date}
    confirm_booked_slot: str = ""    # {date} {time}
    confirm_resched_slot: str = ""   # {date} {time}
    confirm_resched_token: str = ""  # {token} {date}
    confirm_cancelled: str = ""


# Shared English brevity directive for non-Telugu languages (LLM instruction).
_BREVITY_EN = (
    "\n\nVOICE BREVITY — OVERRIDES EVERYTHING ABOVE: every spoken reply must be "
    "very short, one or two phrases. Do not repeat the disclosure. Ask only one "
    "question at a time."
)


LINES: dict[str, Lines] = {
    # ── Telugu — REFERENCE (Vinay-validated, matches the live agent) ──────────
    "te": Lines(
        service_blocked=(
            "నమస్కారం అండి! క్షమించాలి, ఈ సర్వీస్ ప్రస్తుతానికి ఆగిపోయింది. "
            "దయచేసి క్లినిక్‌కి డైరెక్ట్‌గా కాల్ చేయండి. థాంక్యూ."
        ),
        # Vinay 2026-06-25: minimal "okay" fillers only — no verbose "ఒక్క నిమిషం చెక్
        # చేస్తాను" variants. A few short variants so it isn't robotic repetition.
        fillers=("ఓకే,", "ఓకే అండి,", "సరే,"),
        # The welcome clip already said "నమస్కారం, {clinic} క్లినిక్‌కి స్వాగతం" — so
        # this does NOT repeat namaskaram/clinic; it discloses the AI (legal) and
        # goes straight to "how can I help". Minimal అండి (Vinay 2026-06-24).
        # Trimmed 2026-07-04 (Vinay: persona-sim R1 "greeting a bit long"), wording
        # corrected by Vinay same day: keep "మీకు", drop only the redundant "నేను".
        disclosure_greeting=(
            "నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని. చెప్పండి, మీకు ఎలా సహాయం చేయగలను?"
        ),
        # Leading namaskaram dropped from these three OUTBOUND bodies — the welcome
        # clip already said "నమస్కారం, {clinic} క్లినిక్‌కి స్వాగతం" (Vinay 2026-06-24:
        # reminder said namaskaram twice).
        known_caller_greeting=(
            "{patient} గారు! మళ్ళీ కాల్ చేశారు, సంతోషం అండి. {clinic} నుంచి AI "
            "అసిస్టెంట్‌ని మాట్లాడుతున్నాను. చెప్పండి, ఈసారి ఏం కావాలి అండి?"
        ),
        # Vinay 2026-07-10 (post-Soniox test call: "intro trim it") — his exact
        # wording, romanized→Telugu script. One sentence, no "క్లినిక్‌కి స్వాగతం".
        # AI disclosure (DPDP) stays: "AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను".
        inbound_intro=(
            "నమస్కారం, {clinic} నుంచి AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను. "
            "చెప్పండి, నేను మీకు ఎలా హెల్ప్ చేయగలను?"
        ),
        inbound_intro_known=(
            "నమస్కారం, {clinic} నుంచి AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను. "
            "చెప్పండి {patient} గారు, నేను మీకు ఎలా హెల్ప్ చేయగలను?"
        ),
        # Gemini-generated (2026-06-24): avoids the loanword "రిమైండర్" (TTS mangled
        # it — "reminmirainder") via గుర్తు చేయడానికి; minimal అండి; no namaskaram
        # (welcome clip says it).
        reminder_greeting=(
            "{patient} గారు, ఇది {clinic} క్లినిక్ నుంచి చిన్న కాల్. {doctor} గారితో ఈరోజు "
            "{time}కి ఉన్న అపాయింట్‌మెంట్ గుర్తు చేయడానికి ఫోన్ చేశానండి, మీరు వస్తున్నారా?"
        ),
        rebook_greeting=(
            "{patient} గారు, ఇది {clinic} క్లినిక్ నుంచి చిన్న కాల్. {date} రోజున {doctor} గారు "
            "అందుబాటులో లేరు, అందుకే మీ అపాయింట్‌మెంట్ క్యాన్సల్ అయ్యింది, సారీ అండి. "
            "మీరు వేరే రోజు బుక్ చేసుకుంటారా?"
        ),
        cap_warning="ఆగండండి, టైమ్ అయిపోతోంది. మీ బుకింగ్ త్వరగా కన్ఫర్మ్ చేద్దామా?",
        cap_goodbye="థాంక్యూ అండి, ఉంటాను మరి!",
        # Treatment follow-up openings (Gemini-generated 2026-06-25). No namaskaram
        # (welcome clip says it). _q asks the doctor's question {message}.
        followup_greeting_q=(
            "{patient} గారు, ఇది {clinic} క్లినిక్ నుంచి చేస్తున్న చిన్న ఫాలో-అప్ కాల్. "
            "డాక్టర్ గారు మిమ్మల్ని ఒక విషయం అడగమన్నారు. {message}"
        ),
        followup_greeting_noq=(
            "{patient} గారు, ఇది {clinic} క్లినిక్ నుండి చిన్న కాల్ అండి. "
            "ట్రీట్‌మెంట్ తర్వాత ఇప్పుడు మీకు ఎలా అనిపిస్తుందో చెప్పగలరా అండి?"
        ),
        # Missed-call callback: the patient rang back; disclose the AI (inbound legal
        # notice) + deliver the doctor's question. {message} = the doctor's question.
        inbound_followup_greeting=(
            "నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని. డాక్టర్ గారు మిమ్మల్ని ఒక విషయం అడగమన్నారు. {message}"
        ),
        # Verbatim honorific pattern from known_caller_greeting ("{patient} గారు").
        followup_name_prefix="{patient} గారు, ",
        brevity=(
            "\n\nVOICE BREVITY — OVERRIDES EVERYTHING ABOVE: ప్రతి ఆన్సర్ చాలా చిన్నగా, "
            "ఒకటి లేదా రెండు ముక్కల్లో ఉండాలి. డిస్క్లోజర్ మళ్ళీ చెప్పొద్దు. "
            "ఒకసారి ఒకే ఒక్క ప్రశ్న అడుగు."
        ),
        confirm_booked_token=(
            "[happily] బుక్ అయిపోయిందండి. {date}కి, మీ టోకెన్ నంబర్ {token}. "
            "టైంకి రండి."
        ),
        confirm_booked_slot=(
            "[happily] బుక్ అయిపోయిందండి. {date}, {time}కి. టైంకి రండి."
        ),
        confirm_resched_slot=(
            "[happily] అపాయింట్‌మెంట్ మార్చేశానండి. ఇప్పుడు {date}, {time}కి. "
            "పాతది క్యాన్సిల్ అయింది. టైంకి రండి."
        ),
        confirm_resched_token=(
            "[happily] అపాయింట్‌మెంట్ {date}కి మార్చేశానండి. కొత్త టోకెన్ "
            "నంబర్ {token}. పాతది క్యాన్సిల్ అయింది. టైంకి రండి."
        ),
        confirm_cancelled="[softly] మీ అపాయింట్‌మెంట్ క్యాన్సిల్ అయిందండి.",
    ),

    # ── English (Indian) — for per-caller language mapping (2026-07-03) ──────
    "en": Lines(
        service_blocked=(
            "Hello! Sorry, this service is currently unavailable. "
            "Please call the clinic directly. Thank you."
        ),
        fillers=("Okay,", "Sure,", "Alright,"),
        disclosure_greeting=(
            "I am this clinic's AI assistant. How can I help you today?"
        ),
        known_caller_greeting=(
            "Hello {patient}! Nice to hear from you again. I'm the AI assistant "
            "from {clinic}. How can I help you this time?"
        ),
        reminder_greeting=(
            "Hello {patient}, this is a quick call from {clinic}. Just a reminder "
            "about your appointment today at {time} with {doctor}. Will you be coming?"
        ),
        rebook_greeting=(
            "Hello {patient}, this is a quick call from {clinic}. {doctor} is not "
            "available on {date}, so your appointment was cancelled — sorry about "
            "that. Would you like to book another day?"
        ),
        cap_warning="We're almost out of time — shall we quickly confirm your booking?",
        cap_goodbye="Thank you, have a good day!",
        followup_greeting_q=(
            "Hello {patient}, this is a quick follow-up call from {clinic}. "
            "The doctor asked me to check one thing with you. {message}"
        ),
        followup_greeting_noq=(
            "Hello {patient}, this is a quick call from {clinic}. "
            "How are you feeling after the treatment?"
        ),
        inbound_followup_greeting=(
            "I am this clinic's AI assistant. The doctor asked me to check one "
            "thing with you. {message}"
        ),
        followup_name_prefix="{patient}, ",
        # Vinay 2026-07-14: SAME short-intro rule as Telugu, across ALL
        # languages — one sentence, AI disclosure, "how can I help", no
        # "welcome to the clinic" (the intro replaces the welcome+greeting
        # pair entirely; greeting.py returns it as the single segment).
        inbound_intro=(
            "Hello, I'm the AI assistant from {clinic}. How can I help you?"
        ),
        inbound_intro_known=(
            "Hello, I'm the AI assistant from {clinic}. How can I help you, {patient}?"
        ),
        brevity=_BREVITY_EN,
        confirm_booked_token=(
            "[happily] Done. Your booking is confirmed for {date}. Your token "
            "number is {token}. Please come on time."
        ),
        confirm_booked_slot=(
            "[happily] Done. Your appointment is confirmed for {date} at {time}. "
            "Please come on time."
        ),
        confirm_resched_slot=(
            "[happily] Done. Your appointment is moved to {date} at {time}. "
            "The earlier one is cancelled. Please come on time."
        ),
        confirm_resched_token=(
            "[happily] Done. Your appointment is moved to {date}. Your new token "
            "number is {token}. The earlier one is cancelled. Please come on time."
        ),
        confirm_cancelled="[softly] Your appointment is cancelled.",
    ),

    # ── Hindi — first-pass ────────────────────────────────────────────────────
    "hi": Lines(
        service_blocked=(
            "नमस्ते! माफ़ कीजिए, यह सेवा अभी बंद है। "
            "कृपया क्लिनिक को सीधे कॉल करें। धन्यवाद।"
        ),
        fillers=(
            "एक मिनट, मैं चेक करती हूँ।",
            "एक सेकंड रुकिए, देख रही हूँ।",
            "देखकर बताती हूँ, एक मिनट।",
            "ठीक है, सिस्टम में देखती हूँ।",
        ),
        disclosure_greeting=(
            "नमस्ते, {clinic} में आपका स्वागत है। मैं क्लिनिक की AI असिस्टेंट हूँ। "
            "बताइए, मैं आपकी क्या मदद करूँ?"
        ),
        known_caller_greeting=(
            "नमस्ते {patient} जी! {clinic} में आपका फिर से स्वागत है। मैं क्लिनिक की AI "
            "असिस्टेंट हूँ। बताइए, क्या मदद चाहिए?"
        ),
        reminder_greeting=(
            "नमस्ते {patient} जी! यह {clinic} क्लिनिक से अपॉइंटमेंट रिमाइंडर कॉल है। "
            "आज {time} बजे {doctor} जी के साथ आपकी बुकिंग है। आप आ रहे हैं ना?"
        ),
        rebook_greeting=(
            "नमस्ते {patient} जी, {clinic} क्लिनिक से कॉल कर रहे हैं। एक छोटी सी बात — "
            "{date} को {doctor} जी उपलब्ध नहीं हैं, इसलिए आपका अपॉइंटमेंट कैंसिल हो गया है, "
            "माफ़ कीजिए। क्या किसी और दिन के लिए बुक कर दूँ?"
        ),
        cap_warning="थोड़ा रुकिए, समय खत्म हो रहा है। चलिए आपकी बुकिंग जल्दी कन्फर्म कर दें?",
        cap_goodbye="धन्यवाद, चलती हूँ फिर!",
        # Short single-sentence intro (Vinay 2026-07-14 — "Hindi intro is too
        # large and repeating itself"; same rule as Telugu). ⚠ first-pass.
        inbound_intro=(
            "नमस्ते, मैं {clinic} की AI असिस्टेंट बोल रही हूँ। बताइए, मैं आपकी क्या मदद करूँ?"
        ),
        inbound_intro_known=(
            "नमस्ते, मैं {clinic} की AI असिस्टेंट बोल रही हूँ। बताइए {patient} जी, क्या मदद करूँ?"
        ),
        brevity=_BREVITY_EN,
        confirm_booked_token=(
            "[happily] बुकिंग हो गई है। {date} के लिए आपका टोकन नंबर {token} है। "
            "कृपया समय पर आइए।"
        ),
        confirm_booked_slot=(
            "[happily] अपॉइंटमेंट कन्फ़र्म हो गया है। {date} को {time} बजे। "
            "कृपया समय पर आइए।"
        ),
        confirm_resched_slot=(
            "[happily] अपॉइंटमेंट बदल दिया है। अब {date} को {time} बजे। "
            "पुराना कैंसिल हो गया है। कृपया समय पर आइए।"
        ),
        confirm_resched_token=(
            "[happily] अपॉइंटमेंट {date} के लिए बदल दिया है। नया टोकन नंबर "
            "{token} है। पुराना कैंसिल हो गया है। कृपया समय पर आइए।"
        ),
        confirm_cancelled="[softly] आपका अपॉइंटमेंट कैंसिल हो गया है।",
    ),

    # ── Tamil — FIRST-PASS ⚠ needs native validation ─────────────────────────
    "ta": Lines(
        service_blocked=(
            "வணக்கம்! மன்னிக்கவும், இந்த சேவை இப்போது நிறுத்தப்பட்டுள்ளது. "
            "தயவுசெய்து கிளினிக்கை நேரடியாக கூப்பிடுங்கள். நன்றி."
        ),
        fillers=(
            "ஒரு நிமிஷம், செக் பண்றேன்.",
            "ஒரு செகண்ட் இருங்க, பார்க்கறேன்.",
            "பார்த்து சொல்றேன், ஒரு நிமிஷம்.",
            "சரி, சிஸ்டத்துல பார்க்கறேன்.",
        ),
        disclosure_greeting=(
            "வணக்கம், {clinic}-க்கு வரவேற்கிறேன். நான் கிளினிக் AI அசிஸ்டென்ட். "
            "சொல்லுங்க, என்ன உதவி வேணும்?"
        ),
        known_caller_greeting=(
            "வணக்கம் {patient}! {clinic}-க்கு மீண்டும் வரவேற்கிறேன். நான் கிளினிக் AI "
            "அசிஸ்டென்ட். சொல்லுங்க, என்ன உதவி வேணும்?"
        ),
        reminder_greeting=(
            "வணக்கம் {patient}! இது {clinic} கிளினிக்கிலிருந்து அப்பாயிண்மென்ட் ரிமைண்டர் "
            "கால். இன்று {time} மணிக்கு {doctor} அவர்களுடன் உங்க புக்கிங் இருக்கு. "
            "வர்றீங்க இல்லையா?"
        ),
        rebook_greeting=(
            "வணக்கம் {patient}, {clinic} கிளினிக்கிலிருந்து கால் பண்றோம். ஒரு சின்ன "
            "விஷயம் — {date} அன்று {doctor} கிடைக்கல, அதனால உங்க அப்பாயிண்மென்ட் "
            "கேன்சல் ஆயிடுச்சு, மன்னிக்கவும். வேற நாள் பார்த்து புக் பண்ணட்டுமா?"
        ),
        cap_warning="கொஞ்சம் இருங்க, டைம் முடியப் போகுது. உங்க புக்கிங்கை சீக்கிரம் கன்ஃபர்ம் பண்ணலாமா?",
        cap_goodbye="நன்றி, வர்றேன்!",
        # Short single-sentence intro (Vinay 2026-07-14, all languages). ⚠ first-pass.
        inbound_intro=(
            "வணக்கம், {clinic} கிளினிக்கின் AI அசிஸ்டெண்ட் பேசுறேன். சொல்லுங்க, என்ன உதவி வேணும்?"
        ),
        inbound_intro_known=(
            "வணக்கம், {clinic} கிளினிக்கின் AI அசிஸ்டெண்ட் பேசுறேன். சொல்லுங்க {patient}, என்ன உதவி வேணும்?"
        ),
        brevity=_BREVITY_EN,
    ),

    # ── Kannada — FIRST-PASS ⚠ needs native validation ───────────────────────
    "kn": Lines(
        service_blocked=(
            "ನಮಸ್ಕಾರ! ಕ್ಷಮಿಸಿ, ಈ ಸೇವೆ ಸದ್ಯಕ್ಕೆ ನಿಂತಿದೆ. "
            "ದಯವಿಟ್ಟು ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕಾಲ್ ಮಾಡಿ. ಧನ್ಯವಾದ."
        ),
        fillers=(
            "ಒಂದು ನಿಮಿಷ, ಚೆಕ್ ಮಾಡ್ತೀನಿ.",
            "ಒಂದು ಸೆಕೆಂಡ್ ಇರಿ, ನೋಡ್ತಿದೀನಿ.",
            "ನೋಡಿ ಹೇಳ್ತೀನಿ, ಒಂದು ನಿಮಿಷ.",
            "ಸರಿ, ಸಿಸ್ಟಮ್‌ನಲ್ಲಿ ನೋಡ್ತೀನಿ.",
        ),
        disclosure_greeting=(
            "ನಮಸ್ಕಾರ, {clinic}ಗೆ ಸ್ವಾಗತ. ನಾನು ಕ್ಲಿನಿಕ್ AI ಅಸಿಸ್ಟೆಂಟ್. "
            "ಹೇಳಿ, ನಿಮಗೆ ಏನು ಸಹಾಯ ಬೇಕು?"
        ),
        known_caller_greeting=(
            "ನಮಸ್ಕಾರ {patient} ಅವರೇ! {clinic}ಗೆ ಮತ್ತೆ ಸ್ವಾಗತ. ನಾನು ಕ್ಲಿನಿಕ್ AI "
            "ಅಸಿಸ್ಟೆಂಟ್. ಹೇಳಿ, ಏನು ಸಹಾಯ ಬೇಕು?"
        ),
        reminder_greeting=(
            "ನಮಸ್ಕಾರ {patient} ಅವರೇ! ಇದು {clinic} ಕ್ಲಿನಿಕ್‌ನಿಂದ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ರಿಮೈಂಡರ್ "
            "ಕಾಲ್. ಇವತ್ತು {time}ಗೆ {doctor} ಅವರ ಜೊತೆ ನಿಮ್ಮ ಬುಕಿಂಗ್ ಇದೆ. ಬರ್ತಿದೀರಾ?"
        ),
        rebook_greeting=(
            "ನಮಸ್ಕಾರ {patient} ಅವರೇ, {clinic} ಕ್ಲಿನಿಕ್‌ನಿಂದ ಕಾಲ್ ಮಾಡ್ತಿದೀವಿ. ಒಂದು ಚಿಕ್ಕ "
            "ವಿಷಯ — {date}ರಂದು {doctor} ಲಭ್ಯ ಇಲ್ಲ, ಅದಕ್ಕೆ ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಕ್ಯಾನ್ಸಲ್ "
            "ಆಗಿದೆ, ಕ್ಷಮಿಸಿ. ಬೇರೆ ದಿನ ಬುಕ್ ಮಾಡಲಾ?"
        ),
        cap_warning="ಸ್ವಲ್ಪ ಇರಿ, ಟೈಮ್ ಮುಗಿಯುತ್ತಿದೆ. ನಿಮ್ಮ ಬುಕಿಂಗ್ ಬೇಗ ಕನ್ಫರ್ಮ್ ಮಾಡೋಣವಾ?",
        cap_goodbye="ಧನ್ಯವಾದ, ಬರ್ತೀನಿ!",
        # Short single-sentence intro (Vinay 2026-07-14, all languages). ⚠ first-pass.
        inbound_intro=(
            "ನಮಸ್ಕಾರ, {clinic} ಕ್ಲಿನಿಕ್‌ನ AI ಅಸಿಸ್ಟೆಂಟ್ ಮಾತಾಡ್ತಿದ್ದೀನಿ. ಹೇಳಿ, ಏನು ಸಹಾಯ ಬೇಕು?"
        ),
        inbound_intro_known=(
            "ನಮಸ್ಕಾರ, {clinic} ಕ್ಲಿನಿಕ್‌ನ AI ಅಸಿಸ್ಟೆಂಟ್ ಮಾತಾಡ್ತಿದ್ದೀನಿ. ಹೇಳಿ {patient}, ಏನು ಸಹಾಯ ಬೇಕು?"
        ),
        brevity=_BREVITY_EN,
    ),

    # ── Malayalam — FIRST-PASS ⚠ needs native validation ─────────────────────
    "ml": Lines(
        service_blocked=(
            "നമസ്കാരം! ക്ഷമിക്കണം, ഈ സേവനം ഇപ്പോൾ നിർത്തിയിരിക്കുന്നു. "
            "ദയവായി ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കൂ. നന്ദി."
        ),
        fillers=(
            "ഒരു മിനിറ്റ്, ഞാൻ ചെക്ക് ചെയ്യാം.",
            "ഒരു സെക്കൻഡ് നിൽക്കൂ, നോക്കുകയാണ്.",
            "നോക്കി പറയാം, ഒരു മിനിറ്റ്.",
            "ശരി, സിസ്റ്റത്തിൽ നോക്കാം.",
        ),
        disclosure_greeting=(
            "നമസ്കാരം, {clinic}ലേക്ക് സ്വാഗതം. ഞാൻ ക്ലിനിക് AI അസിസ്റ്റന്റ് ആണ്. "
            "പറയൂ, എന്ത് സഹായം വേണം?"
        ),
        known_caller_greeting=(
            "നമസ്കാരം {patient}! {clinic}ലേക്ക് വീണ്ടും സ്വാഗതം. ഞാൻ ക്ലിനിക് AI "
            "അസിസ്റ്റന്റ് ആണ്. പറയൂ, എന്ത് സഹായം വേണം?"
        ),
        reminder_greeting=(
            "നമസ്കാരം {patient}! ഇത് {clinic} ക്ലിനിക്കിൽ നിന്നുള്ള അപ്പോയിന്റ്മെന്റ് "
            "റിമൈൻഡർ കോൾ ആണ്. ഇന്ന് {time}ന് {doctor}ന്റെ കൂടെ നിങ്ങളുടെ ബുക്കിംഗ് ഉണ്ട്. "
            "വരുന്നില്ലേ?"
        ),
        rebook_greeting=(
            "നമസ്കാരം {patient}, {clinic} ക്ലിനിക്കിൽ നിന്ന് വിളിക്കുകയാണ്. ഒരു ചെറിയ "
            "കാര്യം — {date}ന് {doctor} ലഭ്യമല്ല, അതുകൊണ്ട് നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് "
            "ക്യാൻസൽ ആയി, ക്ഷമിക്കണം. വേറെ ദിവസം ബുക്ക് ചെയ്യട്ടെ?"
        ),
        cap_warning="കുറച്ച് നിൽക്കൂ, സമയം കഴിയുകയാണ്. നിങ്ങളുടെ ബുക്കിംഗ് വേഗം കൺഫേം ചെയ്യാമോ?",
        cap_goodbye="നന്ദി, ഞാൻ പോകട്ടെ!",
        # Short single-sentence intro (Vinay 2026-07-14, all languages). ⚠ first-pass.
        inbound_intro=(
            "നമസ്കാരം, {clinic} ക്ലിനിക്കിലെ AI അസിസ്റ്റന്റാണ്. പറയൂ, എന്ത് സഹായം വേണം?"
        ),
        inbound_intro_known=(
            "നമസ്കാരം, {clinic} ക്ലിനിക്കിലെ AI അസിസ്റ്റന്റാണ്. പറയൂ {patient}, എന്ത് സഹായം വേണം?"
        ),
        brevity=_BREVITY_EN,
    ),

    # ── Marathi — FIRST-PASS ⚠ needs native validation ───────────────────────
    "mr": Lines(
        service_blocked=(
            "नमस्कार! माफ करा, ही सेवा सध्या बंद आहे. "
            "कृपया क्लिनिकला थेट कॉल करा. धन्यवाद."
        ),
        fillers=(
            "एक मिनिट, मी चेक करते.",
            "एक सेकंद थांबा, बघते आहे.",
            "बघून सांगते, एक मिनिट.",
            "ठीक आहे, सिस्टममध्ये बघते.",
        ),
        disclosure_greeting=(
            "नमस्कार, {clinic} मध्ये आपले स्वागत आहे. मी क्लिनिकची AI असिस्टंट आहे. "
            "सांगा, मी आपली काय मदत करू?"
        ),
        known_caller_greeting=(
            "नमस्कार {patient}! {clinic} मध्ये पुन्हा स्वागत आहे. मी क्लिनिकची AI "
            "असिस्टंट आहे. सांगा, काय मदत हवी?"
        ),
        reminder_greeting=(
            "नमस्कार {patient}! हा {clinic} क्लिनिककडून अपॉइंटमेंट रिमाइंडर कॉल आहे. "
            "आज {time} वाजता {doctor} यांच्यासोबत तुमची बुकिंग आहे. तुम्ही येताय ना?"
        ),
        rebook_greeting=(
            "नमस्कार {patient}, {clinic} क्लिनिककडून कॉल करतोय. एक छोटीशी गोष्ट — "
            "{date} ला {doctor} उपलब्ध नाहीत, त्यामुळे तुमची अपॉइंटमेंट कॅन्सल झाली आहे, "
            "माफ करा. दुसऱ्या दिवशी बुक करू का?"
        ),
        cap_warning="जरा थांबा, वेळ संपत आली आहे. तुमची बुकिंग लवकर कन्फर्म करूया का?",
        cap_goodbye="धन्यवाद, येते मी!",
        # Short single-sentence intro (Vinay 2026-07-14, all languages). ⚠ first-pass.
        inbound_intro=(
            "नमस्कार, मी {clinic} क्लिनिकची AI असिस्टंट बोलत आहे. सांगा, काय मदत करू?"
        ),
        inbound_intro_known=(
            "नमस्कार, मी {clinic} क्लिनिकची AI असिस्टंट बोलत आहे. सांगा {patient}, काय मदत करू?"
        ),
        brevity=_BREVITY_EN,
    ),

    # ── Bengali — FIRST-PASS ⚠ needs native validation ───────────────────────
    "bn": Lines(
        service_blocked=(
            "নমস্কার! দুঃখিত, এই পরিষেবাটি এখন বন্ধ আছে। "
            "দয়া করে ক্লিনিকে সরাসরি কল করুন। ধন্যবাদ।"
        ),
        fillers=(
            "এক মিনিট, আমি চেক করছি।",
            "এক সেকেন্ড দাঁড়ান, দেখছি।",
            "দেখে বলছি, এক মিনিট।",
            "ঠিক আছে, সিস্টেমে দেখছি।",
        ),
        disclosure_greeting=(
            "নমস্কার, {clinic}-এ স্বাগতম। আমি ক্লিনিকের AI অ্যাসিস্ট্যান্ট। "
            "বলুন, আপনাকে কী সাহায্য করতে পারি?"
        ),
        known_caller_greeting=(
            "নমস্কার {patient}! {clinic}-এ আবার স্বাগতম। আমি ক্লিনিকের AI "
            "অ্যাসিস্ট্যান্ট। বলুন, কী সাহায্য লাগবে?"
        ),
        reminder_greeting=(
            "নমস্কার {patient}! এটা {clinic} ক্লিনিক থেকে অ্যাপয়েন্টমেন্ট রিমাইন্ডার কল। "
            "আজ {time}টায় {doctor}-এর সঙ্গে আপনার বুকিং আছে। আপনি আসছেন তো?"
        ),
        rebook_greeting=(
            "নমস্কার {patient}, {clinic} ক্লিনিক থেকে কল করছি। একটা ছোট ব্যাপার — "
            "{date} তারিখে {doctor} উপলব্ধ নেই, তাই আপনার অ্যাপয়েন্টমেন্ট ক্যানসেল হয়ে গেছে, "
            "দুঃখিত। অন্য দিন বুক করে দেব?"
        ),
        cap_warning="একটু দাঁড়ান, সময় শেষ হয়ে আসছে। আপনার বুকিংটা তাড়াতাড়ি কনফার্ম করি?",
        cap_goodbye="ধন্যবাদ, আসি তাহলে!",
        # Short single-sentence intro (Vinay 2026-07-14, all languages). ⚠ first-pass.
        inbound_intro=(
            "নমস্কার, আমি {clinic} ক্লিনিকের AI অ্যাসিস্ট্যান্ট বলছি। বলুন, কী সাহায্য করতে পারি?"
        ),
        inbound_intro_known=(
            "নমস্কার, আমি {clinic} ক্লিনিকের AI অ্যাসিস্ট্যান্ট বলছি। বলুন {patient}, কী সাহায্য করতে পারি?"
        ),
        brevity=_BREVITY_EN,
    ),
}


def get_lines(code: str | None) -> Lines:
    """Resolve spoken lines for a Branch.language code, falling back to Telugu so
    a None / unknown / legacy value can never break a live call."""
    return LINES.get((code or "").lower().strip(), LINES[DEFAULT_LANG])


# ── Instant pre-session welcome (played before the main session connects, to
# kill start-of-call silence — see welcome_audio.play_welcome). Short and warm;
# the full disclosure greeting follows. Kept OUT of the Lines dataclass so it can
# be added without touching every language entry. te is Vinay-validated
# ("namaskaram <clinic> clinic ki swagatham"); the rest are first-pass.
WELCOME: dict[str, str] = {
    "te": "నమస్కారం, {clinic} క్లినిక్‌కి స్వాగతం.",
    "en": "Hello, welcome to {clinic} clinic.",
    "hi": "नमस्ते, {clinic} क्लिनिक में आपका स्वागत है।",
    "ta": "வணக்கம், {clinic} கிளினிக்கிற்கு வரவேற்கிறோம்.",
    "kn": "ನಮಸ್ಕಾರ, {clinic} ಕ್ಲಿನಿಕ್‌ಗೆ ಸ್ವಾಗತ.",
    "ml": "നമസ്കാരം, {clinic} ക്ലിനിക്കിലേക്ക് സ്വാഗതം.",
    "mr": "नमस्कार, {clinic} क्लिनिकमध्ये आपले स्वागत आहे.",
    "bn": "নমস্কার, {clinic} ক্লিনিকে আপনাকে স্বাগতম।",
}


def get_welcome(code: str | None) -> str:
    """Pre-session welcome line for a Branch.language code (falls back to Telugu).
    Takes a {clinic} placeholder."""
    return WELCOME.get((code or "").lower().strip(), WELCOME[DEFAULT_LANG])


# Temporary admin-test recording notice. This is always the first spoken
# segment and finishes before audio capture starts. Telugu is the existing
# validated legal line; the remaining languages are first-pass translations.
RECORDING_NOTICE: dict[str, str] = {
    "te": "ఈ కాల్ నాణ్యత మెరుగుదల కోసం రికార్డ్ చేయబడుతుంది.",
    "en": "This call will be recorded for quality testing.",
    "hi": "गुणवत्ता परीक्षण के लिए यह कॉल रिकॉर्ड की जाएगी।",
    "ta": "தரப் பரிசோதனைக்காக இந்த அழைப்பு பதிவு செய்யப்படும்.",
    "kn": "ಗುಣಮಟ್ಟ ಪರೀಕ್ಷೆಗಾಗಿ ಈ ಕರೆಯನ್ನು ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುತ್ತದೆ.",
    "ml": "ഗുണനിലവാര പരിശോധനയ്ക്കായി ഈ കോൾ റെക്കോർഡ് ചെയ്യും.",
    "mr": "गुणवत्ता तपासणीसाठी हा कॉल रेकॉर्ड केला जाईल.",
    "bn": "গুণমান পরীক্ষার জন্য এই কলটি রেকর্ড করা হবে।",
}


def get_recording_notice(code: str | None) -> str:
    """Recording notice for a language code (falls back to Telugu)."""
    return RECORDING_NOTICE.get(
        (code or "").lower().strip(), RECORDING_NOTICE[DEFAULT_LANG]
    )


# ── Silence line-check (Vinay 2026-07-20): "if user doesn't speak for 10 secs
# straight, say 'hello, are you there? hello, line lo unnara?' every 10 secs
# until 30 and end the call." te is Vinay's dictated wording in script; the
# rest are first-pass (same status as WELCOME) — humanizer can refine later.
# No {placeholders} — spoken as-is.
LINE_CHECK: dict[str, str] = {
    "te": "హలో, మీరు ఉన్నారా? హలో, లైన్‌లో ఉన్నారా?",
    "en": "Hello, are you there? Hello, are you still on the line?",
    "hi": "हैलो, आप हैं क्या? हैलो, आप लाइन पर हैं?",
    "ta": "ஹலோ, நீங்கள் இருக்கிறீர்களா? ஹலோ, லைனில் இருக்கிறீர்களா?",
    "kn": "ಹಲೋ, ನೀವು ಇದ್ದೀರಾ? ಹಲೋ, ಲೈನ್‌ನಲ್ಲಿ ಇದ್ದೀರಾ?",
    "ml": "ഹലോ, നിങ്ങൾ ഉണ്ടോ? ഹലോ, ലൈനിൽ ഉണ്ടോ?",
    "mr": "हॅलो, तुम्ही आहात का? हॅलो, तुम्ही लाईनवर आहात का?",
    "bn": "হ্যালো, আপনি আছেন? হ্যালো, আপনি কি লাইনে আছেন?",
}

# Lost-connection notice (Vinay 2026-07-20): spoken when the caller repeats
# "hello" 3 times in a row — they likely cannot hear us (one-way audio) or the
# line dropped. Acknowledge, tell them to call back, then the agent hangs up
# so a dead line doesn't burn minutes.
RECONNECT: dict[str, str] = {
    "te": "నేను మీ మాట వినగలుగుతున్నాను, కానీ మీకు నా మాట సరిగ్గా వినిపించడం లేదేమో. దయచేసి ఫోన్ పెట్టేసి మళ్ళీ కాల్ చేయండి. థాంక్యూ అండి.",
    "en": "I can hear you, but it seems you may not be able to hear me clearly. Please hang up and call again. Thank you.",
    "hi": "मैं आपकी आवाज़ सुन पा रही हूँ, लेकिन शायद आपको मेरी आवाज़ ठीक से नहीं सुनाई दे रही। कृपया फ़ोन रखकर दोबारा कॉल करें। धन्यवाद।",
    "ta": "உங்கள் குரல் எனக்குக் கேட்கிறது, ஆனால் என் குரல் உங்களுக்குச் சரியாகக் கேட்கவில்லை போலும். தயவுசெய்து துண்டித்து மீண்டும் அழைக்கவும். நன்றி.",
    "kn": "ನಿಮ್ಮ ಧ್ವನಿ ನನಗೆ ಕೇಳಿಸುತ್ತಿದೆ, ಆದರೆ ನನ್ನ ಧ್ವನಿ ನಿಮಗೆ ಸರಿಯಾಗಿ ಕೇಳಿಸುತ್ತಿಲ್ಲವೇನೋ. ದಯವಿಟ್ಟು ಫೋನ್ ಇಟ್ಟು ಮತ್ತೆ ಕರೆ ಮಾಡಿ. ಧನ್ಯವಾದ.",
    "ml": "എനിക്ക് നിങ്ങളുടെ ശബ്ദം കേൾക്കാം, പക്ഷേ എന്റെ ശബ്ദം നിങ്ങൾക്ക് ശരിയായി കേൾക്കുന്നില്ലായിരിക്കാം. ദയവായി ഫോൺ വെച്ച് വീണ്ടും വിളിക്കൂ. നന്ദി.",
    "mr": "मला तुमचा आवाज ऐकू येतोय, पण कदाचित तुम्हाला माझा आवाज नीट ऐकू येत नसेल. कृपया फोन ठेवून पुन्हा कॉल करा. धन्यवाद.",
    "bn": "আমি আপনার কথা শুনতে পাচ্ছি, কিন্তু হয়তো আপনি আমার কথা ঠিকমতো শুনতে পাচ্ছেন না। অনুগ্রহ করে ফোন রেখে আবার কল করুন। ধন্যবাদ।",
}


# ── Slow-tool hold (Vinay 2026-07-24): spoken ONLY while a genuinely slow
# tool runs (availability / booking lookup / book / reschedule / cancel), never
# for quick ones. Soniox renders the trailing [long pause] as intentional
# thinking time while the tool continues in parallel. Two variants keep later
# flows natural; the runtime cooldown prevents back-to-back repetition.
WAIT_FILLERS: dict[str, tuple[str, ...]] = {
    "te": (
        "ఒక్క నిమిషం అండి... చూస్తున్నాను. [long pause]",
        "చూస్తున్నాను అండి... [long pause]",
    ),
    "en": (
        "One moment, please... I’m checking. [long pause]",
        "Let me check that... [long pause]",
    ),
    "hi": (
        "एक मिनट कृपया... [long pause]",
        "ज़रा देख लेते हैं... [long pause]",
    ),
    "ta": (
        "ஒரு நிமிடம்... பார்க்கிறேன். [long pause]",
        "சற்று பார்க்கிறேன்... [long pause]",
    ),
    "kn": (
        "ಒಂದು ನಿಮಿಷ... ನೋಡುತ್ತಿದ್ದೇನೆ. [long pause]",
        "ಸ್ವಲ್ಪ ನೋಡುತ್ತೇನೆ... [long pause]",
    ),
    "ml": (
        "ഒരു നിമിഷം... നോക്കുകയാണ്. [long pause]",
        "ഒന്ന് നോക്കട്ടೆ... [long pause]",
    ),
    "mr": (
        "एक मिनिट... पाहत आहे. [long pause]",
        "जरा पाहूया... [long pause]",
    ),
    "bn": (
        "এক মিনিট... দেখছি। [long pause]",
        "একটু দেখে নিই... [long pause]",
    ),
}


def get_wait_fillers(code: str | None) -> tuple[str, ...]:
    """Natural Soniox hold lines for slow tools (falls back to Telugu)."""
    return WAIT_FILLERS.get((code or "").lower().strip(), WAIT_FILLERS[DEFAULT_LANG])


def get_line_check(code: str | None) -> str:
    """Silence line-check line for a language code (falls back to Telugu)."""
    return LINE_CHECK.get((code or "").lower().strip(), LINE_CHECK[DEFAULT_LANG])


def get_reconnect(code: str | None) -> str:
    """Lost-connection notice for a language code (falls back to Telugu)."""
    return RECONNECT.get((code or "").lower().strip(), RECONNECT[DEFAULT_LANG])


# ── Mid-call language-switch acknowledgement (spoken deterministically by the
# NEW agent's on_enter right after the caller explicitly asks to switch, so
# there is never dead air while the STT/TTS pipelines are swapped). Short,
# spoken in the TARGET language. te/en natural; others first-pass.
# Wording per Vinay 2026-07-03: the switched voice says ONLY "I can speak X.
# How can I help you?" — nothing more (the LLM reply after the handoff is
# suppressed mechanically; this line is the entire intro).
SWITCH_ACK: dict[str, str] = {
    "te": "నేను తెలుగులో మాట్లాడగలనండి. చెప్పండి, మీకు ఎలా సహాయం చేయగలను?",
    "en": "I can speak English. How can I help you?",
    "hi": "मैं हिंदी में बात कर सकती हूँ। बताइए, मैं आपकी क्या मदद करूँ?",
    "ta": "நான் தமிழில் பேச முடியும். சொல்லுங்க, என்ன உதவி வேணும்?",
    "kn": "ನಾನು ಕನ್ನಡದಲ್ಲಿ ಮಾತಾಡಬಲ್ಲೆ. ಹೇಳಿ, ಏನು ಸಹಾಯ ಬೇಕು?",
    "ml": "എനിക്ക് മലയാളത്തിൽ സംസാരിക്കാം. പറയൂ, എന്ത് സഹായം വേണം?",
    "mr": "मी मराठीत बोलू शकते. सांगा, काय मदत हवी?",
    "bn": "আমি বাংলায় কথা বলতে পারি। বলুন, কী সাহায্য লাগবে?",
}


def get_switch_ack(code: str | None) -> str:
    """Spoken confirmation for a just-switched call language (falls back to Telugu)."""
    return SWITCH_ACK.get((code or "").lower().strip(), SWITCH_ACK[DEFAULT_LANG])
