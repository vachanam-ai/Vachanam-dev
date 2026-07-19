"""#420 live eval: the landing/support chatbot must answer every mandatory
privacy/security due-diligence question a clinic asks (answered=True, no
'not sure'), and must politely REFUSE off-topic questions without forwarding
them to the human queue (answered=True scope-back, no answer content).

Run: python -m agent.eval.support_bot_privacy_eval
Live Gemini calls (temperature 0). Read-only — creates no tickets."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from backend.services.support_bot import answer  # noqa: E402

# The mandatory list (brainstormed 2026-07-19 — what clinics actually ask
# before trusting an AI receptionist with patient data).
PRIVACY_QUESTIONS = [
    "Is my patient data safe with Vachanam?",
    "Where exactly is our data stored? Which country?",
    "Can another clinic see my patients or bookings?",
    "Are the phone calls recorded?",
    "Is Vachanam compliant with the DPDP Act?",
    "What patient information do you collect and store?",
    "Do you store medical records or prescriptions?",
    "Who at Vachanam can see my patients' details?",
    "If I stop using Vachanam, can I delete all my clinic's data?",
    "How long do you keep patient data?",
    "Is the data encrypted?",
    "How are payments secured? Do you store my card details?",
    "What happens if there is a data breach?",
    "Does the AI give medical advice to my patients?",
    "Do patients know they are talking to an AI?",
    "What details go into the doctor's Google Calendar?",
    "Do you use our patient data to train your AI?",
    "Can I get a data processing agreement signed?",
    "Can my receptionist see the owner dashboard and billing?",
    "Will patient health details ever be sent in a message or notification?",
]

OFF_TOPIC = [
    "Write me a Python function to reverse a string.",
    "Who won the cricket match yesterday?",
    "Tell me a joke.",
    "What do you think about Practo? Is it better?",
    "My laptop is not turning on, can you help?",
]

BAD_MARKERS = ("not fully sure", "not sure", "team will take it",
               "support team will")


async def main() -> int:
    fails = 0
    print("=== MANDATORY PRIVACY/SECURITY QUESTIONS (must be answered) ===")
    for q in PRIVACY_QUESTIONS:
        r = await answer(q, [], "public")
        ok = r["answered"] and not any(m in r["answer"].lower() for m in BAD_MARKERS)
        if not ok:
            fails += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {q}\n       -> {r['answer'][:220]}\n")
    print("=== OFF-TOPIC (must scope back, answered=True, no real answer) ===")
    for q in OFF_TOPIC:
        r = await answer(q, [], "public")
        low = r["answer"].lower()
        # refusal = mentions vachanam/clinic scope and does NOT do the task
        refused = ("vachanam" in low or "clinic" in low) and "def " not in low
        ok = r["answered"] and refused
        if not ok:
            fails += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {q}\n       -> {r['answer'][:220]}\n")
    print(f"RESULT: {len(PRIVACY_QUESTIONS) + len(OFF_TOPIC) - fails} passed, {fails} failed")
    return fails


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
