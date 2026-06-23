"""Seed the humanizer example bank with Vinay's approved lines (Gemini-generated,
Vinay-reviewed). De-id gate runs on each write. Idempotent (dedup)."""
import sys

from agent.eval.example_bank import ExampleBank

# Approved final set (Gemini spoken-generation → Vinay review). Telugu script only.
APPROVED = {
    "greeting": "నమస్తే అండి, {clinic} నుంచి మాట్లాడుతున్నాను. చెప్పండి, మీకు నేను ఎలా సహాయం చేయగలను?",
    "backchannel_yes": "అవునండి.",
    "backchannel_ok": "ఓకే అండి.",
    "backchannel_wait": "ఒక్క నిమిషం అండి.",
    "please_tell": "చెప్పండి.",
    "are_you_coming": "అపాయింట్‌మెంట్ కి వస్తున్నారు కదండీ?",
    "restate_issue": "అర్థమైంది అండి — మీకు {issue} కోసం అపాయింట్‌మెంట్ కావాలి, కదండీ?",
    "thinking_filler": "ఒక్క నిమిషం అండి, చూస్తున్నాను.",
    "spoken_appt": "ఈ రోజు {time} కి డాక్టర్ {doctor} గారితో మీకు అపాయింట్‌మెంట్ ఉంది అండి.",
    "offer_slots": "రేపు ఉదయం {time} కి, లేదా మధ్యాహ్నం {time} కి స్లాట్ అవైలబుల్ గా ఉంది అండి. మీకు ఏ టైం కంఫర్టబుల్ అండి?",
    "close_booked": "ఓకే అండి, రేపు {time} కి బుక్ చేశాము. కొంచెం ముందుగా రండి. ఏదైనా డౌట్ ఉంటే మళ్ళీ కాల్ చేయండి. థాంక్యూ అండి.",
    "anxious_reassure": "పర్వాలేదు అండి, మీరు కంగారు పడకండి, నేను వెంటనే అపాయింట్‌మెంట్ అరేంజ్ చేస్తాను.",
    "angry_validate": "క్షమించండి, నేను ఇప్పుడే చూస్తాను అండి.",
    "relay_to_doctor": "ఓకే అండి, నేను డాక్టర్ గారితో {name} గారి ప్రాబ్లం గురించి చెబుతాను. మీకు మళ్ళీ కాల్ చేస్తాను.",
    "ask_detail": "కొంచెం వివరంగా చెప్పగలరా అండి?",
    "speak_closer": "కొంచెం డిస్టర్బెన్స్ వస్తుంది అండి, ఫోన్ దగ్గరగా పెట్టి మాట్లాడతారా?",
}

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    bank = ExampleBank()
    added = bank.seed(APPROVED, source="vinay_correction")
    print(f"seeded {added} new examples; bank now has {len(bank.all())} total.")
