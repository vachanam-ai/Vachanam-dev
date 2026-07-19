"""#420: the support chatbot must be able to answer clinics' privacy/security
due-diligence questions (Vinay: bot said "not sure about data security" on the
landing page — basics clinics need before trusting us). Live proof:
agent/eval/support_bot_privacy_eval.py = 25/25 (20 mandatory privacy Qs
answered, 5 off-topic refused). These tests guard the two inputs that made it
possible: the KNOWLEDGE.md facts and the bot-prompt boundary."""
from backend.services import support_kb
from backend.services.support_bot import _SYSTEM


def test_knowledge_covers_mandatory_privacy_facts():
    kb = support_kb.knowledge_text()
    for fact in [
        "DPDP",                      # compliance + roles
        "Data Processor",
        "Data Fiduciary",
        "vachanam.in/dpa",           # signable DPA
        "AES-256",                   # encryption at rest
        "TLS",
        "Singapore",                 # storage location
        "NOT recorded",              # call recording
        "90",                        # transcript window
        "2 years",                   # retention
        "7 years",                   # audit retention
        "24 hours",                  # breach clinic notice
        "72 hours",                  # breach board notice
        "train",                     # never trains on patient data
        "Razorpay",                  # payment security
        "last-4",                    # calendar minimalism
        "privacy@vachanam.in",       # grievance contact
        "AI assistant",              # disclosure to patients
    ]:
        assert fact in kb, f"KNOWLEDGE.md lost mandatory privacy fact: {fact!r}"


def test_bot_prompt_answers_privacy_and_refuses_offtopic():
    # Privacy/security must be answered confidently (old boundary refused
    # "legal questions", which swallowed security due-diligence)...
    assert "Privacy, data security, DPDP compliance" in _SYSTEM
    assert "answer these confidently" in _SYSTEM
    assert "legal or medical questions" not in _SYSTEM  # the old blanket ban
    # ...and pure off-topic (coding, jokes, other products) is scoped back
    # without creating a human ticket.
    assert "OFF-TOPIC" in _SYSTEM
    assert "coding/programming help" in _SYSTEM
