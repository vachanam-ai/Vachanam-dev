"""Deterministic post-tool confirmation speech.

Successful booking mutations have no creative work left for the LLM. This
builder turns their verified result into a short native-script line so the
voice can answer immediately after the write, without a second model pass.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import time as time_cls

from agent.i18n.lines import LINES, get_lines
from agent.services.telugu_dates import telugu_date, telugu_time

_KIND_FIELD = {
    "booked_token": "confirm_booked_token",
    "booked_slot": "confirm_booked_slot",
    "resched_slot": "confirm_resched_slot",
    "resched_token": "confirm_resched_token",
    "cancelled": "confirm_cancelled",
}

_BOOKING_HELP = {
    'te': 'ఇంకేమైనా సహాయం కావాలా అండి?',
    'en': 'Is there anything else I can help you with?',
    'hi': 'और कुछ मदद चाहिए जी?',
    'ta': 'வேற ஏதாவது உதவி வேணுமாங்?',
    'kn': 'ಇನ್ನೇನಾದರೂ ಸಹಾಯ ಬೇಕಾ?',
    'ml': 'മറ്റെന്തെങ്കിലും സഹായം വേണമോ?',
    'mr': 'आणखी काही मदत हवी आहे का?',
    'bn': 'আর কোনো সাহায্য লাগবে?',
}

_BOOKING_PARTIES = {
    "en": "For {patient}, with {doctor}.",
    "te": "{patient} గారికి, {doctor} గారితో.",
    "hi": "{patient} के लिए, {doctor} के साथ।",
    "ta": "{patient}க்கு, {doctor} உடன்.",
    "kn": "{patient} ಅವರಿಗೆ, {doctor} ಅವರೊಂದಿಗೆ.",
    "ml": "{patient}യ്ക്ക്, {doctor} നോടൊപ്പം.",
    "mr": "{patient} यांच्यासाठी, {doctor} यांच्यासोबत.",
    "bn": "{patient}-এর জন্য, {doctor}-এর সঙ্গে।",
}

_BOOKING_CONFIRM_QUESTIONS = {
    "en": {
        "slot": "Should I book {patient} with {doctor} on {date} at {time}?",
        "token": "Should I book {patient} with {doctor} on {date}?",
    },
    "te": {
        "slot": "{patient} గారికి, {doctor} గారితో {date} నాడు {time} అపాయింట్‌మెంట్ బుక్ చేయనా అండి?",
        "token": "{patient} గారికి, {doctor} గారితో {date} నాడు అపాయింట్‌మెంట్ బుక్ చేయనా అండి?",
    },
    "hi": {
        "slot": "क्या मैं {patient} के लिए {doctor} के साथ {date} को {time} की अपॉइंटमेंट बुक कर दूँ?",
        "token": "क्या मैं {patient} के लिए {doctor} के साथ {date} को अपॉइंटमेंट बुक कर दूँ?",
    },
    "ta": {
        "slot": "{patient}க்கு, {doctor} உடன் {date} அன்று {time} அப்பாயின்ட்மென்ட்டை பதிவு செய்யவா?",
        "token": "{patient}க்கு, {doctor} உடன் {date} அன்று அப்பாயின்ட்மென்ட்டை பதிவு செய்யவா?",
    },
    "kn": {
        "slot": "{patient} ಅವರಿಗೆ, {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು {time} ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಬುಕ್ ಮಾಡಲೇ?",
        "token": "{patient} ಅವರಿಗೆ, {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಬುಕ್ ಮಾಡಲೇ?",
    },
    "ml": {
        "slot": "{patient}ക്ക്, {doctor} നോടൊപ്പം {date} ന് {time} അപ്പോയിന്റ്മെന്റ് ബുക്ക് ചെയ്യട്ടേ?",
        "token": "{patient}ക്ക്, {doctor} നോടൊപ്പം {date} ന് അപ്പോയിന്റ്മെന്റ് ബുക്ക് ചെയ്യട്ടേ?",
    },
    "mr": {
        "slot": "{patient} यांच्यासाठी, {doctor} यांच्यासोबत {date} रोजी {time} ची अपॉइंटमेंट बुक करू का?",
        "token": "{patient} यांच्यासाठी, {doctor} यांच्यासोबत {date} रोजी अपॉइंटमेंट बुक करू का?",
    },
    "bn": {
        "slot": "{patient}-এর জন্য, {doctor}-এর সঙ্গে {date} তারিখে {time} অ্যাপয়েন্টমেন্ট বুক করব?",
        "token": "{patient}-এর জন্য, {doctor}-এর সঙ্গে {date} তারিখে অ্যাপয়েন্টমেন্ট বুক করব?",
    },
}

_CANCELLATION_CONFIRM_QUESTIONS = {
    "en": {
        "slot": "Should I cancel {patient}'s appointment with {doctor} on {date} at {time}?",
        "token": "Should I cancel {patient}'s appointment with {doctor} on {date}, token number {token}?",
    },
    "te": {
        "slot": "{patient} గారి {doctor} గారితో {date} నాడు {time} అపాయింట్‌మెంట్‌ను రద్దు చేయనా అండి?",
        "token": "{patient} గారి {doctor} గారితో {date} నాటి టోకెన్ నంబర్ {token} అపాయింట్‌మెంట్‌ను రద్దు చేయనా అండి?",
    },
    "hi": {
        "slot": "क्या मैं {patient} की {doctor} के साथ {date} को {time} वाली अपॉइंटमेंट रद्द कर दूँ?",
        "token": "क्या मैं {patient} की {doctor} के साथ {date} की टोकन नंबर {token} वाली अपॉइंटमेंट रद्द कर दूँ?",
    },
    "ta": {
        "slot": "{patient}க்கு {doctor} உடன் {date} அன்று {time} உள்ள அப்பாயின்ட்மென்ட்டை ரத்து செய்யவா?",
        "token": "{patient}க்கு {doctor} உடன் {date} அன்று டோக்கன் எண் {token} உள்ள அப்பாயின்ட்மென்ட்டை ரத்து செய்யவா?",
    },
    "kn": {
        "slot": "{patient} ಅವರಿಗೆ {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು {time} ಇರುವ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ರದ್ದು ಮಾಡಲೇ?",
        "token": "{patient} ಅವರಿಗೆ {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು ಟೋಕನ್ ಸಂಖ್ಯೆ {token} ಇರುವ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ರದ್ದು ಮಾಡಲೇ?",
    },
    "ml": {
        "slot": "{patient}യുടെ {doctor} നോടൊപ്പമുള്ള {date} ന് {time} അപ്പോയിന്റ്മെന്റ് റദ്ദാക്കട്ടേ?",
        "token": "{patient}യുടെ {doctor} നോടൊപ്പമുള്ള {date} ലെ ടോക്കൺ നമ്പർ {token} അപ്പോയിന്റ്മെന്റ് റദ്ദാക്കട്ടേ?",
    },
    "mr": {
        "slot": "{patient} यांची {doctor} यांच्यासोबत {date} रोजी {time} ची अपॉइंटमेंट रद्द करू का?",
        "token": "{patient} यांची {doctor} यांच्यासोबत {date} रोजी टोकन क्रमांक {token} ची अपॉइंटमेंट रद्द करू का?",
    },
    "bn": {
        "slot": "{patient}-এর {doctor}-এর সঙ্গে {date} তারিখে {time} অ্যাপয়েন্টমেন্টটি বাতিল করব?",
        "token": "{patient}-এর {doctor}-এর সঙ্গে {date} তারিখের টোকেন নম্বর {token} অ্যাপয়েন্টমেন্টটি বাতিল করব?",
    },
}

_LOOKUP_PATIENT_PREFIX = {
    "en": "For {patient}.",
    "te": "{patient} గారి పేరుతో.",
    "hi": "{patient} के नाम पर।",
    "ta": "{patient} பெயரில்.",
    "kn": "{patient} ಅವರ ಹೆಸರಿನಲ್ಲಿ.",
    "ml": "{patient}യുടെ പേരിൽ.",
    "mr": "{patient} यांच्या नावावर.",
    "bn": "{patient}-এর নামে।",
}

_CLINIC_QUESTION_ACK = {
    'te': 'సరే అండి. ఈ ప్రశ్నను నమోదు చేశాను. క్లినిక్ డాక్టర్‌ని అడిగి మీకు కాల్ చేస్తారు.',
    'en': 'All right. I have noted this question. The clinic will check with the doctor and call you back.',
    'hi': 'ठीक है जी। मैंने यह सवाल दर्ज कर लिया है। क्लिनिक डॉक्टर से पूछकर आपको वापस कॉल करेगा।',
    'ta': 'சரி. இந்தக் கேள்வியை பதிவு செய்துவிட்டேன். கிளினிக் மருத்துவரிடம் கேட்டுவிட்டு உங்களைத் திரும்ப அழைக்கும்.',
    'kn': 'ಸರಿ. ಈ ಪ್ರಶ್ನೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ. ಕ್ಲಿನಿಕ್ ವೈದ್ಯರನ್ನು ಕೇಳಿ ನಿಮಗೆ ಮತ್ತೆ ಕರೆ ಮಾಡುತ್ತದೆ.',
    'mr': 'ठीक आहे. हा प्रश्न नोंदवला आहे. क्लिनिक डॉक्टरांना विचारून तुम्हाला परत कॉल करेल.',
    'bn': 'ঠিক আছে। প্রশ্নটি নথিভুক্ত করেছি। ক্লিনিক ডাক্তারকে জিজ্ঞেস করে আপনাকে আবার ফোন করবে।',
    'ml': 'ശരി. ഈ ചോദ്യം രേഖപ്പെടുത്തിയിട്ടുണ്ട്. ക്ലിനിക്ക് ഡോക്ടറോട് ചോദിച്ചിട്ട് നിങ്ങളെ തിരികെ വിളിക്കും.',
}

_CLINIC_MESSAGE_ACK = {
    'te': 'సరే అండి. మీ సందేశాన్ని క్లినిక్ కోసం నమోదు చేశాను.',
    'en': 'All right. I have recorded your message for the clinic.',
    'hi': 'ठीक है जी। मैंने आपका संदेश क्लिनिक के लिए दर्ज कर लिया है।',
    'ta': 'சரி. உங்கள் செய்தியை கிளினிக்கிற்காக பதிவு செய்துவிட்டேன்.',
    'kn': 'ಸರಿ. ನಿಮ್ಮ ಸಂದೇಶವನ್ನು ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ದಾಖಲಿಸಿದ್ದೇನೆ.',
    'mr': 'ठीक आहे. तुमचा संदेश क्लिनिकसाठी नोंदवला आहे.',
    'bn': 'ঠিক আছে। আপনার বার্তাটি ক্লিনিকের জন্য নথিভুক্ত করেছি।',
    'ml': 'ശരി. നിങ്ങളുടെ സന്ദേശം ക്ലിനിക്കിനായി രേഖപ്പെടുത്തിയിട്ടുണ്ട്.',
}


def build_clinic_question_ack(lang_code: str) -> str:
    """Verified acknowledgement after a clinic question is committed."""
    return _CLINIC_QUESTION_ACK.get(
        (lang_code or '').lower().strip(), _CLINIC_QUESTION_ACK['en']
    )


def build_clinic_message_ack(lang_code: str) -> str:
    """Verified acknowledgement after a caller message is committed."""
    return _CLINIC_MESSAGE_ACK.get(
        (lang_code or '').lower().strip(), _CLINIC_MESSAGE_ACK['en']
    )


_RELAY_CONTENT_REQUEST = {
    "question": {
        "en": "Please tell me the exact question you want me to record for the clinic.",
        "te": "క్లినిక్ కోసం నమోదు చేయాల్సిన కచ్చితమైన ప్రశ్నను చెప్పండి అండి.",
        "hi": "कृपया वह सही सवाल बताइए जिसे क्लिनिक के लिए दर्ज करना है।",
        "ta": "கிளினிக்கிற்காக பதிவு செய்ய வேண்டிய சரியான கேள்வியைச் சொல்லுங்கள்.",
        "kn": "ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ದಾಖಲಿಸಬೇಕಾದ ನಿಖರವಾದ ಪ್ರಶ್ನೆಯನ್ನು ಹೇಳಿ.",
        "ml": "ക്ലിനിക്കിനായി രേഖപ്പെടുത്തേണ്ട കൃത്യമായ ചോദ്യം പറയൂ.",
        "mr": "क्लिनिकसाठी नोंदवायचा नेमका प्रश्न सांगा.",
        "bn": "ক্লিনিকের জন্য যে সঠিক প্রশ্নটি নথিভুক্ত করতে হবে সেটি বলুন।",
    },
    "message": {
        "en": "Please tell me the exact message you want me to record for the clinic.",
        "te": "క్లినిక్ కోసం నమోదు చేయాల్సిన కచ్చితమైన సందేశాన్ని చెప్పండి అండి.",
        "hi": "कृपया वह सही संदेश बताइए जिसे क्लिनिक के लिए दर्ज करना है।",
        "ta": "கிளினிக்கிற்காக பதிவு செய்ய வேண்டிய சரியான செய்தியைச் சொல்லுங்கள்.",
        "kn": "ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ದಾಖಲಿಸಬೇಕಾದ ನಿಖರವಾದ ಸಂದೇಶವನ್ನು ಹೇಳಿ.",
        "ml": "ക്ലിനിക്കിനായി രേഖപ്പെടുത്തേണ്ട കൃത്യമായ സന്ദേശം പറയൂ.",
        "mr": "क्लिनिकसाठी नोंदवायचा नेमका संदेश सांगा.",
        "bn": "ক্লিনিকের জন্য যে সঠিক বার্তাটি নথিভুক্ত করতে হবে সেটি বলুন।",
    },
}


def build_relay_content_request_text(lang_code: str, kind: str) -> str:
    """Ask for missing caller-authored relay text without model invention."""
    content_kind = "question" if kind == "question" else "message"
    lines = _RELAY_CONTENT_REQUEST[content_kind]
    return lines.get((lang_code or "").lower().strip(), lines["en"])


_ACTION_CONTINUE = {
    "booking": {
        "en": "I can help with that booking. Please tell me the doctor, date, and preferred time.",
        "te": "ఆ బుకింగ్‌లో నేను సహాయం చేస్తాను అండి. డాక్టర్, తేదీ, కావాల్సిన టైమ్ చెప్పండి.",
        "hi": "मैं उस बुकिंग में मदद कर सकती हूँ। डॉक्टर, तारीख और पसंद का समय बताइए।",
        "ta": "அந்த புக்கிங்கில் நான் உதவுகிறேன். மருத்துவர், தேதி, விரும்பிய நேரத்தைச் சொல்லுங்கள்.",
        "kn": "ಆ ಬುಕಿಂಗ್‌ಗೆ ನಾನು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ವೈದ್ಯರು, ದಿನಾಂಕ ಮತ್ತು ಬೇಕಾದ ಸಮಯವನ್ನು ಹೇಳಿ.",
        "ml": "ആ ബുക്കിംഗിൽ ഞാൻ സഹായിക്കാം. ഡോക്ടർ, തീയതി, വേണ്ട സമയം പറയൂ.",
        "mr": "त्या बुकिंगसाठी मी मदत करू शकते. डॉक्टर, तारीख आणि हवी असलेली वेळ सांगा.",
        "bn": "ওই বুকিংয়ে আমি সাহায্য করতে পারি। ডাক্তার, তারিখ এবং পছন্দের সময় বলুন।",
    },
    "cancel": {
        "en": "I can help cancel it. Please tell me which appointment you mean.",
        "te": "దాన్ని రద్దు చేయడంలో సహాయం చేస్తాను అండి. ఏ అపాయింట్‌మెంట్ అనేది చెప్పండి.",
        "hi": "मैं उसे रद्द करने में मदद कर सकती हूँ। कौन-सी अपॉइंटमेंट है, बताइए।",
        "ta": "அதை ரத்து செய்ய உதவுகிறேன். எந்த அப்பாயின்ட்மென்ட் என்று சொல்லுங்கள்.",
        "kn": "ಅದನ್ನು ರದ್ದು ಮಾಡಲು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಯಾವ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಎಂದು ಹೇಳಿ.",
        "ml": "അത് റദ്ദാക്കാൻ ഞാൻ സഹായിക്കാം. ഏത് അപ്പോയിന്റ്മെന്റാണെന്ന് പറയൂ.",
        "mr": "ती रद्द करण्यासाठी मी मदत करू शकते. कोणती अपॉइंटमेंट आहे ते सांगा.",
        "bn": "সেটি বাতিল করতে আমি সাহায্য করতে পারি। কোন অ্যাপয়েন্টমেন্টটি বোঝাচ্ছেন বলুন।",
    },
    "reschedule": {
        "en": "I can help reschedule it. Please tell me which appointment you mean.",
        "te": "దాన్ని మార్చడంలో సహాయం చేస్తాను అండి. ఏ అపాయింట్‌మెంట్ అనేది చెప్పండి.",
        "hi": "मैं उसका समय बदलने में मदद कर सकती हूँ। कौन-सी अपॉइंटमेंट है, बताइए।",
        "ta": "அதன் நேரத்தை மாற்ற உதவுகிறேன். எந்த அப்பாயின்ட்மென்ட் என்று சொல்லுங்கள்.",
        "kn": "ಅದನ್ನು ಮರುನಿಗದಿಪಡಿಸಲು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಯಾವ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಎಂದು ಹೇಳಿ.",
        "ml": "അത് മാറ്റാൻ ഞാൻ സഹായിക്കാം. ഏത് അപ്പോയിന്റ്മെന്റാണെന്ന് പറയൂ.",
        "mr": "ती बदलण्यासाठी मी मदत करू शकते. कोणती अपॉइंटमेंट आहे ते सांगा.",
        "bn": "সেটির সময় বদলাতে আমি সাহায্য করতে পারি। কোন অ্যাপয়েন্টমেন্টটি বোঝাচ্ছেন বলুন।",
    },
}


def build_action_continue_text(lang_code: str, action: str) -> str:
    """Grounded recovery when the model refuses an in-scope pending action."""
    if action in {"message", "question"}:
        return build_relay_content_request_text(lang_code, action)
    normalized = action if action in _ACTION_CONTINUE else "booking"
    lines = _ACTION_CONTINUE[normalized]
    return lines.get((lang_code or "").lower().strip(), lines["en"])


_TRANSFER_FAILURE = {
    "en": (
        "I couldn't connect the call. Please call the clinic directly at {contact}. Would you like to tell me a message to record for the clinic?",
        "I couldn't connect the call. Please call or visit the clinic directly. Would you like to tell me a message to record for the clinic?",
    ),
    "te": (
        "కాల్ కనెక్ట్ కాలేదు అండి. దయచేసి {contact} నంబర్‌కు నేరుగా కాల్ చేయండి. క్లినిక్ కోసం నమోదు చేయాల్సిన సందేశం చెప్పాలా?",
        "కాల్ కనెక్ట్ కాలేదు అండి. దయచేసి క్లినిక్‌కు నేరుగా కాల్ చేయండి లేదా వెళ్లండి. క్లినిక్ కోసం నమోదు చేయాల్సిన సందేశం చెప్పాలా?",
    ),
    "hi": (
        "कॉल कनेक्ट नहीं हो पाया। कृपया क्लिनिक को {contact} पर सीधे कॉल करें। क्या आप क्लिनिक के लिए कोई संदेश दर्ज कराना चाहते हैं?",
        "कॉल कनेक्ट नहीं हो पाया। कृपया क्लिनिक को सीधे कॉल करें या वहाँ जाएँ। क्या आप क्लिनिक के लिए कोई संदेश दर्ज कराना चाहते हैं?",
    ),
    "ta": (
        "அழைப்பை இணைக்க முடியவில்லை. கிளினிக்கை {contact} என்ற எண்ணில் நேரடியாக அழையுங்கள். கிளினிக்கிற்காக ஒரு செய்தியை பதிவு செய்ய வேண்டுமா?",
        "அழைப்பை இணைக்க முடியவில்லை. கிளினிக்கை நேரடியாக அழையுங்கள் அல்லது செல்லுங்கள். கிளினிக்கிற்காக ஒரு செய்தியை பதிவு செய்ய வேண்டுமா?",
    ),
    "kn": (
        "ಕರೆಯನ್ನು ಸಂಪರ್ಕಿಸಲು ಆಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು {contact} ಸಂಖ್ಯೆಗೆ ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ. ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ಸಂದೇಶ ದಾಖಲಿಸಬೇಕೇ?",
        "ಕರೆಯನ್ನು ಸಂಪರ್ಕಿಸಲು ಆಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ ಅಥವಾ ಭೇಟಿ ನೀಡಿ. ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ಸಂದೇಶ ದಾಖಲಿಸಬೇಕೇ?",
    ),
    "ml": (
        "കോൾ ബന്ധിപ്പിക്കാനായില്ല. ദയവായി {contact} എന്ന നമ്പറിൽ ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കൂ. ക്ലിനിക്കിനായി ഒരു സന്ദേശം രേഖപ്പെടുത്തണോ?",
        "കോൾ ബന്ധിപ്പിക്കാനായില്ല. ദയവായി ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുകയോ അവിടെ പോകുകയോ ചെയ്യൂ. ക്ലിനിക്കിനായി ഒരു സന്ദേശം രേഖപ്പെടുത്തണോ?",
    ),
    "mr": (
        "कॉल जोडता आला नाही. कृपया क्लिनिकला {contact} या क्रमांकावर थेट कॉल करा. क्लिनिकसाठी संदेश नोंदवायचा आहे का?",
        "कॉल जोडता आला नाही. कृपया क्लिनिकला थेट कॉल करा किंवा तिथे जा. क्लिनिकसाठी संदेश नोंदवायचा आहे का?",
    ),
    "bn": (
        "কলটি সংযোগ করা যায়নি। অনুগ্রহ করে {contact} নম্বরে ক্লিনিকে সরাসরি কল করুন। ক্লিনিকের জন্য কোনো বার্তা নথিভুক্ত করতে চান?",
        "কলটি সংযোগ করা যায়নি। অনুগ্রহ করে ক্লিনিকে সরাসরি কল করুন বা সেখানে যান। ক্লিনিকের জন্য কোনো বার্তা নথিভুক্ত করতে চান?",
    ),
}


def build_transfer_failure_text(
    lang_code: str,
    contact: str | None = None,
    *,
    urgent: bool = False,
) -> str:
    """Actionable, non-claiming fallback after a failed human transfer."""
    del urgent  # Both variants already give the immediate direct-call path.
    lines = _TRANSFER_FAILURE.get(
        (lang_code or "").lower().strip(), _TRANSFER_FAILURE["en"]
    )
    clean_contact = (contact or "").strip()
    return lines[0].format(contact=clean_contact) if clean_contact else lines[1]


_BOOKING_FAILURE = {
    "en": "I couldn't complete the booking, so no appointment was created. Please state the exact date and time again.",
    "te": "బుకింగ్ పూర్తి కాలేదు అండి, కాబట్టి అపాయింట్‌మెంట్ నమోదు కాలేదు. కచ్చితమైన తేదీ, టైమ్ మళ్లీ చెప్పండి.",
    "hi": "बुकिंग पूरी नहीं हुई, इसलिए कोई अपॉइंटमेंट नहीं बना है। कृपया सही तारीख और समय फिर से बताइए।",
    "ta": "புக்கிங் நிறைவடையவில்லை, அதனால் அப்பாயின்ட்மென்ட் பதிவு ஆகவில்லை. சரியான தேதி மற்றும் நேரத்தை மீண்டும் சொல்லுங்கள்.",
    "kn": "ಬುಕಿಂಗ್ ಪೂರ್ಣವಾಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ದಾಖಲಾಗಿಲ್ಲ. ನಿಖರವಾದ ದಿನಾಂಕ ಮತ್ತು ಸಮಯವನ್ನು ಮತ್ತೆ ಹೇಳಿ.",
    "mr": "बुकिंग पूर्ण झाली नाही, त्यामुळे अपॉइंटमेंट नोंदवली गेलेली नाही. कृपया अचूक तारीख आणि वेळ पुन्हा सांगा.",
    "bn": "বুকিং সম্পূর্ণ হয়নি, তাই কোনো অ্যাপয়েন্টমেন্ট তৈরি হয়নি। সঠিক তারিখ ও সময় আবার বলুন।",
    "ml": "ബുക്കിംഗ് പൂർത്തിയായില്ല, അതിനാൽ അപ്പോയിന്റ്മെന്റ് രേഖപ്പെടുത്തിയിട്ടില്ല. കൃത്യമായ തീയതിയും സമയവും വീണ്ടും പറയൂ.",
}

_BOOKING_UNAVAILABLE = {
    "en": "Booking is temporarily unavailable, so no appointment was created. Would you like me to record this booking request for the clinic?",
    "te": "ఇప్పుడు బుకింగ్ తాత్కాలికంగా అందుబాటులో లేదండి, కాబట్టి అపాయింట్‌మెంట్ నమోదు కాలేదు. ఈ బుకింగ్ రిక్వెస్ట్‌ను క్లినిక్ కోసం నమోదు చేయనా?",
    "hi": "अभी बुकिंग अस्थायी रूप से उपलब्ध नहीं है, इसलिए कोई अपॉइंटमेंट नहीं बना। क्या मैं यह बुकिंग अनुरोध क्लिनिक के लिए दर्ज कर दूँ?",
    "ta": "இப்போது புக்கிங் தற்காலிகமாக கிடைக்கவில்லை, அதனால் அப்பாயின்ட்மென்ட் பதிவு ஆகவில்லை. இந்த புக்கிங் கோரிக்கையை கிளினிக்கிற்காக பதிவு செய்யவா?",
    "kn": "ಈಗ ಬುಕಿಂಗ್ ತಾತ್ಕಾಲಿಕವಾಗಿ ಲಭ್ಯವಿಲ್ಲ, ಆದ್ದರಿಂದ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ದಾಖಲಾಗಿಲ್ಲ. ಈ ಬುಕಿಂಗ್ ವಿನಂತಿಯನ್ನು ಕ್ಲಿನಿಕ್‌ಗಾಗಿ ದಾಖಲಿಸಲೇ?",
    "mr": "सध्या बुकिंग तात्पुरती उपलब्ध नाही, त्यामुळे अपॉइंटमेंट नोंदवली गेलेली नाही. ही बुकिंग विनंती क्लिनिकसाठी नोंदवू का?",
    "bn": "বুকিং সাময়িকভাবে পাওয়া যাচ্ছে না, তাই কোনো অ্যাপয়েন্টমেন্ট তৈরি হয়নি। এই বুকিং অনুরোধটি কি ক্লিনিকের জন্য নথিভুক্ত করব?",
    "ml": "ഇപ്പോൾ ബുക്കിംഗ് താൽക്കാലികമായി ലഭ്യമല്ല, അതിനാൽ അപ്പോയിന്റ്മെന്റ് രേഖപ്പെടുത്തിയിട്ടില്ല. ഈ ബുക്കിംഗ് അഭ്യർത്ഥന ക്ലിനിക്കിനായി രേഖപ്പെടുത്തട്ടേ?",
}


def build_booking_failure_text(lang_code: str) -> str:
    """Fail-closed speech used only when the booking transaction did not commit."""
    return _BOOKING_FAILURE.get((lang_code or "").lower().strip(), _BOOKING_FAILURE["en"])


def build_booking_unavailable_text(lang_code: str) -> str:
    """Truthful calendar/service outage speech with a concrete message offer."""
    return _BOOKING_UNAVAILABLE.get(
        (lang_code or "").lower().strip(), _BOOKING_UNAVAILABLE["en"]
    )


_READ_FAILURE = {
    "en": "I couldn't check that right now. Please try again, or call the clinic directly.",
    "te": "ఇప్పుడు అది చెక్ చేయలేకపోయాను అండి. మళ్లీ ప్రయత్నించండి లేదా క్లినిక్‌కు నేరుగా కాల్ చేయండి.",
    "hi": "मैं अभी यह जाँच नहीं कर पाई। कृपया फिर कोशिश करें या क्लिनिक को सीधे कॉल करें।",
    "ta": "இப்போது அதைச் சரிபார்க்க முடியவில்லை. மீண்டும் முயற்சி செய்யுங்கள் அல்லது கிளினிக்கை நேரடியாக அழையுங்கள்.",
    "kn": "ಈಗ ಅದನ್ನು ಪರಿಶೀಲಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ.",
    "ml": "ഇപ്പോൾ അത് പരിശോധിക്കാനായില്ല. വീണ്ടും ശ്രമിക്കുക അല്ലെങ്കിൽ ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുക.",
    "mr": "आत्ता ते तपासता आले नाही. पुन्हा प्रयत्न करा किंवा क्लिनिकला थेट कॉल करा.",
    "bn": "এখন এটি যাচাই করা যায়নি। আবার চেষ্টা করুন অথবা ক্লিনিকে সরাসরি ফোন করুন।",
}


def build_read_failure_text(lang_code: str) -> str:
    """Deterministic answer when a read dependency fails after a wait filler."""
    code = (lang_code or "").lower().strip()
    return _READ_FAILURE.get(code, _READ_FAILURE["en"])


_MUTATION_FAILURE = {
    "question": {
        "en": "I couldn't record that question, so it has not been logged. Please call the clinic directly.",
        "te": "ఆ ప్రశ్న నమోదు కాలేదు అండి. క్లినిక్‌కు నేరుగా కాల్ చేయండి.",
        "hi": "वह सवाल दर्ज नहीं हुआ। कृपया क्लिनिक को सीधे कॉल करें।",
        "ta": "அந்தக் கேள்வி பதிவு ஆகவில்லை. கிளினிக்கை நேரடியாக அழையுங்கள்.",
        "kn": "ಆ ಪ್ರಶ್ನೆ ದಾಖಲಾಗಲಿಲ್ಲ. ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ.",
        "ml": "ആ ചോദ്യം രേഖപ്പെടുത്തിയില്ല. ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുക.",
        "mr": "तो प्रश्न नोंदवला गेला नाही. कृपया क्लिनिकला थेट कॉल करा.",
        "bn": "প্রশ্নটি নথিভুক্ত হয়নি। অনুগ্রহ করে ক্লিনিকে সরাসরি ফোন করুন।",
    },
    "message": {
        "en": "I couldn't record that message, so it has not been sent. Please call the clinic directly.",
        "te": "ఆ మెసేజ్ నమోదు కాలేదు అండి, కాబట్టి క్లినిక్‌కు పంపలేదు. క్లినిక్‌కు నేరుగా కాల్ చేయండి.",
        "hi": "वह संदेश दर्ज नहीं हुआ, इसलिए क्लिनिक को नहीं भेजा गया। कृपया क्लिनिक को सीधे कॉल करें।",
        "ta": "அந்த மெசேஜ் பதிவு ஆகவில்லை, அதனால் கிளினிக்கிற்கு அனுப்பப்படவில்லை. கிளினிக்கை நேரடியாக அழையுங்கள்.",
        "kn": "ಆ ಸಂದೇಶ ದಾಖಲಾಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಕ್ಲಿನಿಕ್‌ಗೆ ಕಳುಹಿಸಲಾಗಿಲ್ಲ. ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ.",
        "ml": "ആ സന്ദേശം രേഖപ്പെടുത്തിയില്ല, അതിനാൽ ക്ലിനിക്കിലേക്ക് അയച്ചിട്ടില്ല. ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുക.",
        "mr": "तो संदेश नोंदवला गेला नाही, त्यामुळे क्लिनिकला पाठवलेला नाही. कृपया क्लिनिकला थेट कॉल करा.",
        "bn": "বার্তাটি নথিভুক্ত হয়নি, তাই ক্লিনিকে পাঠানো হয়নি। অনুগ্রহ করে ক্লিনিকে সরাসরি ফোন করুন।",
    },
    "cancel": {
        "en": "I couldn't complete the cancellation, so your appointment remains unchanged. Please call the clinic directly.",
        "te": "క్యాన్సిలేషన్ పూర్తి కాలేదు అండి, కాబట్టి మీ అపాయింట్‌మెంట్ మారలేదు. క్లినిక్‌కు నేరుగా కాల్ చేయండి.",
        "hi": "कैंसलेशन पूरा नहीं हुआ, इसलिए आपकी अपॉइंटमेंट नहीं बदली है। कृपया क्लिनिक को सीधे कॉल करें।",
        "ta": "கேன்சல் செய்ய முடியவில்லை, அதனால் உங்கள் அப்பாயின்ட்மென்ட் மாறவில்லை. கிளினிக்கை நேரடியாக அழையுங்கள்.",
        "kn": "ಕ್ಯಾನ್ಸಲೇಶನ್ ಪೂರ್ಣವಾಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ನಿಮ್ಮ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಬದಲಾಗಿಲ್ಲ. ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ.",
        "ml": "ക്യാൻസലേഷൻ പൂർത്തിയായില്ല, അതിനാൽ നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റിന് മാറ്റമില്ല. ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുക.",
        "mr": "कॅन्सलेशन पूर्ण झाले नाही, त्यामुळे तुमची अपॉइंटमेंट बदललेली नाही. कृपया क्लिनिकला थेट कॉल करा.",
        "bn": "ক্যানসেল সম্পূর্ণ হয়নি, তাই আপনার অ্যাপয়েন্টমেন্ট অপরিবর্তিত আছে। অনুগ্রহ করে ক্লিনিকে সরাসরি ফোন করুন।",
    },
    "reschedule": {
        "en": "I couldn't complete the reschedule, so your existing appointment remains unchanged. Please call the clinic directly.",
        "te": "రీషెడ్యూల్ పూర్తి కాలేదు అండి, కాబట్టి పాత అపాయింట్‌మెంట్ అలాగే ఉంది. క్లినిక్‌కు నేరుగా కాల్ చేయండి.",
        "hi": "रीशेड्यूल पूरा नहीं हुआ, इसलिए आपकी पुरानी अपॉइंटमेंट नहीं बदली है। कृपया क्लिनिक को सीधे कॉल करें।",
        "ta": "ரீஷெட்யூல் முடியவில்லை, அதனால் பழைய அப்பாயின்ட்மென்ட் மாறவில்லை. கிளினிக்கை நேரடியாக அழையுங்கள்.",
        "kn": "ರೀಶೆಡ್ಯೂಲ್ ಪೂರ್ಣವಾಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಹಳೆಯ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಬದಲಾಗಿಲ್ಲ. ಕ್ಲಿನಿಕ್‌ಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ.",
        "ml": "റീഷെഡ്യൂൾ പൂർത്തിയായില്ല, അതിനാൽ പഴയ അപ്പോയിന്റ്മെന്റിന് മാറ്റമില്ല. ക്ലിനിക്കിലേക്ക് നേരിട്ട് വിളിക്കുക.",
        "mr": "रीशेड्यूल पूर्ण झाले नाही, त्यामुळे जुनी अपॉइंटमेंट बदललेली नाही. कृपया क्लिनिकला थेट कॉल करा.",
        "bn": "রিশিডিউল সম্পূর্ণ হয়নি, তাই আগের অ্যাপয়েন্টমেন্ট অপরিবর্তিত আছে। অনুগ্রহ করে ক্লিনিকে সরাসরি ফোন করুন।",
    },
}


def build_mutation_failure_text(lang_code: str, action: str) -> str:
    """Fail-closed speech when a claimed write has no durable success state."""
    messages = _MUTATION_FAILURE.get(action, _MUTATION_FAILURE["message"])
    code = (lang_code or "").lower().strip()
    return messages.get(code, messages["en"])


def build_booking_lookup_text(lang_code: str, booking: dict) -> str:
    """Read one identity-verified database booking without an LLM paraphrase."""
    code = (lang_code or "").lower().strip()
    doctor = str(booking["doctor"])
    patient = " ".join(str(booking.get("patient_name") or "").split())

    def _with_patient(text: str) -> str:
        if not patient:
            return text
        prefix = _LOOKUP_PATIENT_PREFIX.get(code, _LOOKUP_PATIENT_PREFIX["en"])
        return f"{prefix.format(patient=patient)} {text}"

    date_value = date_cls.fromisoformat(str(booking["date"]))
    spoken_date = _spoken_date(date_value, code)
    if booking.get("status") == "cancelled_by_clinic":
        templates = {
            "en": "Your appointment with {doctor} on {date} was cancelled by the clinic.",
            "te": "{doctor} గారితో {date} నాటి మీ అపాయింట్‌మెంట్‌ను క్లినిక్ రద్దు చేసింది అండి.",
            "hi": "{doctor} के साथ {date} की आपकी अपॉइंटमेंट क्लिनिक ने रद्द कर दी थी।",
            "ta": "{doctor} உடன் {date} அன்று இருந்த உங்கள் அப்பாயின்ட்மென்ட்டை கிளினிக் ரத்து செய்தது.",
            "kn": "{doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು ಇದ್ದ ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಅನ್ನು ಕ್ಲಿನಿಕ್ ರದ್ದು ಮಾಡಿದೆ.",
            "mr": "{doctor} यांच्यासोबत {date} रोजी असलेली तुमची अपॉइंटमेंट क्लिनिकने रद्द केली होती.",
            "bn": "{doctor}-এর সঙ্গে {date} তারিখের আপনার অ্যাপয়েন্টমেন্ট ক্লিনিক বাতিল করেছে।",
            "ml": "{doctor} നോടൊപ്പം {date} ന് ഉണ്ടായിരുന്ന നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് ക്ലിനിക് റദ്ദാക്കി.",
        }
        return _with_patient(
            templates.get(code, templates["en"]).format(
                doctor=doctor, date=spoken_date
            )
        )
    if booking.get("booking_type") == "token":
        token = str(booking["token_number"])
        templates = {
            "en": "Your appointment with {doctor} is on {date}, token number {token}.",
            "te": "మీ అపాయింట్‌మెంట్ {doctor} గారితో {date} నాడు, టోకెన్ నంబర్ {token} అండి.",
            "hi": "आपकी अपॉइंटमेंट {doctor} के साथ {date} को है, टोकन नंबर {token}।",
            "ta": "உங்கள் அப்பாயின்ட்மென்ட் {doctor} உடன் {date} அன்று, டோக்கன் எண் {token}.",
            "kn": "ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು, ಟೋಕನ್ ಸಂಖ್ಯೆ {token}.",
            "mr": "तुमची अपॉइंटमेंट {doctor} यांच्यासोबत {date} रोजी आहे, टोकन क्रमांक {token}.",
            "bn": "আপনার অ্যাপয়েন্টমেন্ট {doctor}-এর সঙ্গে {date}, টোকেন নম্বর {token}।",
            "ml": "നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് {doctor} നോടൊപ്പം {date} നാണ്, ടോക്കൺ നമ്പർ {token}.",
        }
        return _with_patient(
            templates.get(code, templates["en"]).format(
                doctor=doctor, date=spoken_date, token=token
            )
        )
    time_value = time_cls.fromisoformat(str(booking["time"]))
    spoken_time = _spoken_time(time_value, code)
    templates = {
        "en": "Your appointment with {doctor} is on {date} at {time}.",
        "te": "మీ అపాయింట్‌మెంట్ {doctor} గారితో {date} నాడు {time} అండి.",
        "hi": "आपकी अपॉइंटमेंट {doctor} के साथ {date} को {time} है।",
        "ta": "உங்கள் அப்பாயின்ட்மென்ட் {doctor} உடன் {date} அன்று {time} உள்ளது.",
        "kn": "ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ {doctor} ಅವರೊಂದಿಗೆ {date} ರಂದು {time} ಇದೆ.",
        "mr": "तुमची अपॉइंटमेंट {doctor} यांच्यासोबत {date} रोजी {time} आहे.",
        "bn": "আপনার অ্যাপয়েন্টমেন্ট {doctor}-এর সঙ্গে {date} তারিখে {time}।",
        "ml": "നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് {doctor} നോടൊപ്പം {date} ന് {time} ആണ്.",
    }
    return _with_patient(
        templates.get(code, templates["en"]).format(
            doctor=doctor, date=spoken_date, time=spoken_time
        )
    )


_NO_BOOKING_FOUND = {
    "en": "I couldn't find a current appointment in the clinic records.",
    "te": "క్లినిక్ రికార్డుల్లో ప్రస్తుతం అపాయింట్‌మెంట్ కనిపించలేదు అండి.",
    "hi": "क्लिनिक के रिकॉर्ड में अभी कोई अपॉइंटमेंट नहीं मिली।",
    "ta": "கிளினிக் பதிவுகளில் தற்போது அப்பாயின்ட்மென்ட் எதுவும் இல்லை.",
    "kn": "ಕ್ಲಿನಿಕ್ ದಾಖಲೆಗಳಲ್ಲಿ ಈಗ ಯಾವುದೇ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಕಂಡುಬಂದಿಲ್ಲ.",
    "mr": "क्लिनिकच्या नोंदींमध्ये सध्या कोणतीही अपॉइंटमेंट सापडली नाही.",
    "bn": "ক্লিনিকের রেকর্ডে বর্তমানে কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।",
    "ml": "ക്ലിനിക് രേഖകളിൽ നിലവിൽ അപ്പോയിന്റ്മെന്റ് കണ്ടെത്താനായില്ല.",
}


def build_no_booking_found_text(lang_code: str) -> str:
    return _NO_BOOKING_FOUND.get(
        (lang_code or "").lower().strip(), _NO_BOOKING_FOUND["en"]
    )


_MONTHS = {
    "hi": ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"),
    "ta": ("ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"),
    "kn": ("ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"),
    "ml": ("ജനുവരി", "ഫെബ്രുവരി", "മാർച്ച്", "ഏപ്രിൽ", "മേയ്", "ജൂൺ", "ജൂലൈ", "ഓഗസ്റ്റ്", "സെപ്റ്റംബർ", "ഒക്ടോബർ", "നവംബർ", "ഡിസംബർ"),
    "mr": ("जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"),
    "bn": ("জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"),
}


def _spoken_date(value: date_cls, lang_code: str) -> str:
    if lang_code == "te":
        return telugu_date(value)
    months = _MONTHS.get(lang_code)
    if months:
        return f"{value.day} {months[value.month - 1]}"
    return value.strftime("%d %B").lstrip("0")


def _spoken_time(value: time_cls, lang_code: str) -> str:
    if lang_code == "te":
        return telugu_time(value)
    if lang_code == "en":
        return value.strftime("%I:%M %p").lstrip("0")
    hour = value.hour % 12 or 12
    clock = f"{hour}:{value.minute:02d}"
    period = 0 if value.hour < 12 else 1 if value.hour < 17 else 2
    parts = {
        "hi": (("सुबह", "दोपहर", "शाम"), "{part} {clock} बजे"),
        "ta": (("காலை", "மதியம்", "மாலை"), "{part} {clock} மணிக்கு"),
        "kn": (("ಬೆಳಿಗ್ಗೆ", "ಮಧ್ಯಾಹ್ನ", "ಸಂಜೆ"), "{part} {clock}ಕ್ಕೆ"),
        "ml": (("രാവിലെ", "ഉച്ചയ്ക്ക്", "വൈകുന്നേരം"), "{part} {clock} മണിക്ക്"),
        "mr": (("सकाळी", "दुपारी", "संध्याकाळी"), "{part} {clock} वाजता"),
        "bn": (("সকাল", "দুপুর", "সন্ধ্যা"), "{part} {clock}টায়"),
    }
    dayparts, template = parts.get(lang_code, parts["hi"])
    return template.format(part=dayparts[period], clock=clock)


def build_booking_confirmation_question(
    lang_code: str,
    *,
    booking_type: str,
    patient_name: str,
    doctor_name: str,
    date_: date_cls,
    time_: time_cls | None = None,
) -> str | None:
    """Ask for final consent using only caller/server-bound booking fields."""
    code = (lang_code or "").lower().strip()
    booking_type = (booking_type or "").lower().strip()
    if booking_type not in {"appointment", "slot", "token"}:
        return None
    kind = "token" if booking_type == "token" else "slot"
    patient = " ".join((patient_name or "").split())
    doctor = " ".join((doctor_name or "").split())
    if code not in LINES or not patient or not doctor or not isinstance(date_, date_cls):
        return None
    if kind == "slot" and not isinstance(time_, time_cls):
        return None
    return _BOOKING_CONFIRM_QUESTIONS[code][kind].format(
        patient=patient,
        doctor=doctor,
        date=_spoken_date(date_, code),
        time=_spoken_time(time_, code) if time_ is not None else "",
    )


def build_cancellation_confirmation_question(
    lang_code: str, booking: dict
) -> str | None:
    """Ask for final cancellation consent from one structured booking receipt."""
    code = (lang_code or "").lower().strip()
    if code not in LINES:
        return None
    patient = " ".join(str(booking.get("patient_name") or "").split())
    doctor = " ".join(
        str(booking.get("doctor") or booking.get("doctor_name") or "").split()
    )
    if not patient or not doctor:
        return None
    try:
        date_value = date_cls.fromisoformat(str(booking["date"]))
        if booking.get("booking_type") == "token":
            token = booking["token_number"]
            if token is None:
                return None
            return _CANCELLATION_CONFIRM_QUESTIONS[code]["token"].format(
                patient=patient,
                doctor=doctor,
                date=_spoken_date(date_value, code),
                token=token,
            )
        time_value = time_cls.fromisoformat(str(booking["time"]))
    except (KeyError, TypeError, ValueError):
        return None
    return _CANCELLATION_CONFIRM_QUESTIONS[code]["slot"].format(
        patient=patient,
        doctor=doctor,
        date=_spoken_date(date_value, code),
        time=_spoken_time(time_value, code),
    )


def build_confirm_text(
    lang_code: str,
    kind: str,
    *,
    token: int | None = None,
    date_: date_cls | None = None,
    time_: time_cls | None = None,
    patient_name: str | None = None,
    doctor_name: str | None = None,
) -> str | None:
    lang_code = (lang_code or "").lower().strip()
    if lang_code not in LINES:
        return None
    field = _KIND_FIELD.get(kind)
    if field is None:
        return None
    template = getattr(get_lines(lang_code), field, "")
    if not template:
        return None

    values: dict[str, str] = {}
    if "{token}" in template:
        if token is None:
            return None
        values["token"] = str(token)
    if "{date}" in template:
        if date_ is None:
            return None
        values["date"] = _spoken_date(date_, lang_code)
    if "{time}" in template:
        if time_ is None:
            return None
        values["time"] = _spoken_time(time_, lang_code)
    spoken = template.format(**values)
    if patient_name and doctor_name:
        parties = _BOOKING_PARTIES.get(lang_code, _BOOKING_PARTIES["en"])
        spoken = (
            f"{parties.format(patient=patient_name, doctor=doctor_name)} {spoken}"
        )
    if kind in {"booked_token", "booked_slot"}:
        help_line = _BOOKING_HELP.get(lang_code)
        if help_line:
            spoken = f"{spoken} {help_line}"
    return spoken
