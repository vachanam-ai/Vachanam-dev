import agent.livekit_minimal.agent as ag


def test_prompt_extras_relay_only_and_record_patient_concern():
    assert "relay" in ag.DOCTOR_ADVICE_PROMPT_EXTRA.lower()
    assert "{message}" in ag.DOCTOR_ADVICE_PROMPT_EXTRA
    assert "call take_message" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "inform the doctor" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "still offer the visit" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "prepared opening already asked" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()


def test_followup_metadata_helper_excludes_private_notes():
    meta = {"call_type": "next_visit_book", "message": "how is pain?",
            "patient_name": "P", "doctor_name": "D", "target_date": "2026-06-25",
            "steps_performed": "LEAK", "next_steps": "LEAK"}
    safe = ag._followup_meta_safe(meta)
    assert "steps_performed" not in safe and "next_steps" not in safe
    assert safe["message"] == "how is pain?"
