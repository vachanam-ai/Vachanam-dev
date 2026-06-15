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
        fillers=(
            "ఒక్క నిమిషం అండి, చెక్ చేస్తాను.",
            "ఒక్క సెకండ్ అండి, చూస్తున్నాను.",
            "చూసి చెప్తానండి, ఒక్క నిమిషం.",
            "సరేనండి, ఒక్కసారి సిస్టమ్‌లో చూస్తాను.",
        ),
        disclosure_greeting=(
            "నమస్కారం అండి, {clinic} కి స్వాగతం. నేను క్లినిక్ AI అసిస్టెంట్‌ని. "
            "మీకు ఎలా హెల్ప్ చేయాలండి?"
        ),
        known_caller_greeting=(
            "నమస్కారం {patient} గారు! {clinic} కి వెల్‌కమ్ బ్యాక్ అండి. నేను క్లినిక్ AI "
            "అసిస్టెంట్‌ని. చెప్పండి, ఏం హెల్ప్ కావాలండి?"
        ),
        reminder_greeting=(
            "నమస్కారం {patient} గారు! {clinic} క్లినిక్ నుంచి అపాయింట్‌మెంట్ రిమైండర్ కాల్ అండి. "
            "ఈరోజు {time}కి {doctor} గారితో మీ బుకింగ్ ఉంది. వస్తున్నారు కదండీ?"
        ),
        rebook_greeting=(
            "నమస్కారం {patient} గారు, {clinic} క్లినిక్ నుంచి కాల్ చేస్తున్నామండి. "
            "చిన్న రిక్వెస్ట్, {date}న {doctor} గారు అవైలబుల్‌గా లేరు. అందుకని మీ "
            "అపాయింట్‌మెంట్ కాన్సిల్ అయింది, ఏమనుకోవద్దు. వేరే డేట్ చూసి బుక్ చేయమంటారా?"
        ),
        cap_warning="ఆగండండి, టైమ్ అయిపోతోంది. మీ బుకింగ్ త్వరగా కన్ఫర్మ్ చేద్దామా?",
        cap_goodbye="థాంక్యూ అండి, ఉంటాను మరి!",
        brevity=(
            "\n\nVOICE BREVITY — OVERRIDES EVERYTHING ABOVE: ప్రతి ఆన్సర్ చాలా చిన్నగా, "
            "ఒకటి లేదా రెండు ముక్కల్లో ఉండాలి. డిస్క్లోజర్ మళ్ళీ చెప్పొద్దు. "
            "ఒకసారి ఒకే ఒక్క ప్రశ్న అడుగు."
        ),
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
        brevity=_BREVITY_EN,
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
        brevity=_BREVITY_EN,
    ),

    # ── Odia — FIRST-PASS ⚠ needs native validation ──────────────────────────
    "or": Lines(
        service_blocked=(
            "ନମସ୍କାର! କ୍ଷମା କରନ୍ତୁ, ଏହି ସେବା ବର୍ତ୍ତମାନ ବନ୍ଦ ଅଛି। "
            "ଦୟାକରି କ୍ଲିନିକ୍‌କୁ ସିଧାସଳଖ କଲ୍ କରନ୍ତୁ। ଧନ୍ୟବାଦ।"
        ),
        fillers=(
            "ଗୋଟିଏ ମିନିଟ୍, ମୁଁ ଚେକ୍ କରୁଛି।",
            "ଗୋଟିଏ ସେକେଣ୍ଡ ରୁହନ୍ତୁ, ଦେଖୁଛି।",
            "ଦେଖି କହୁଛି, ଗୋଟିଏ ମିନିଟ୍।",
            "ଠିକ୍ ଅଛି, ସିଷ୍ଟମରେ ଦେଖୁଛି।",
        ),
        disclosure_greeting=(
            "ନମସ୍କାର, {clinic}କୁ ସ୍ୱାଗତ। ମୁଁ କ୍ଲିନିକ୍ AI ଆସିଷ୍ଟାଣ୍ଟ। "
            "କୁହନ୍ତୁ, ଆପଣଙ୍କୁ କଣ ସାହାଯ୍ୟ ଦରକାର?"
        ),
        known_caller_greeting=(
            "ନମସ୍କାର {patient}! {clinic}କୁ ପୁଣି ସ୍ୱାଗତ। ମୁଁ କ୍ଲିନିକ୍ AI ଆସିଷ୍ଟାଣ୍ଟ। "
            "କୁହନ୍ତୁ, କଣ ସାହାଯ୍ୟ ଦରକାର?"
        ),
        reminder_greeting=(
            "ନମସ୍କାର {patient}! ଏହା {clinic} କ୍ଲିନିକ୍‌ରୁ ଆପଏଣ୍ଟମେଣ୍ଟ ରିମାଇଣ୍ଡର କଲ୍। "
            "ଆଜି {time}ଟାରେ {doctor}ଙ୍କ ସହିତ ଆପଣଙ୍କ ବୁକିଂ ଅଛି। ଆପଣ ଆସୁଛନ୍ତି ତ?"
        ),
        rebook_greeting=(
            "ନମସ୍କାର {patient}, {clinic} କ୍ଲିନିକ୍‌ରୁ କଲ୍ କରୁଛୁ। ଗୋଟିଏ ଛୋଟ କଥା — "
            "{date}ରେ {doctor} ଉପଲବ୍ଧ ନାହାନ୍ତି, ତେଣୁ ଆପଣଙ୍କ ଆପଏଣ୍ଟମେଣ୍ଟ କ୍ୟାନ୍ସଲ ହୋଇଯାଇଛି, "
            "କ୍ଷମା କରନ୍ତୁ। ଅନ୍ୟ ଦିନ ବୁକ୍ କରିଦେବି?"
        ),
        cap_warning="ଟିକେ ରୁହନ୍ତୁ, ସମୟ ସରିଯାଉଛି। ଆପଣଙ୍କ ବୁକିଂ ଶୀଘ୍ର କନଫର୍ମ କରିଦେବା?",
        cap_goodbye="ଧନ୍ୟବାଦ, ଯାଉଛି!",
        brevity=_BREVITY_EN,
    ),
}


def get_lines(code: str | None) -> Lines:
    """Resolve spoken lines for a Branch.language code, falling back to Telugu so
    a None / unknown / legacy value can never break a live call."""
    return LINES.get((code or "").lower().strip(), LINES[DEFAULT_LANG])
