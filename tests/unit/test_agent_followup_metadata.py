import agent.livekit_minimal.agent as ag


def test_prompt_extras_relay_only_and_promise_doctor():
    assert "relay" in ag.DOCTOR_ADVICE_PROMPT_EXTRA.lower()
    assert "{message}" in ag.DOCTOR_ADVICE_PROMPT_EXTRA
    assert "inform the doctor" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "{message}" in ag.NEXT_VISIT_PROMPT_EXTRA


def test_followup_metadata_helper_excludes_private_notes():
    meta = {"call_type": "next_visit_book", "message": "how is pain?",
            "patient_name": "P", "doctor_name": "D", "target_date": "2026-06-25",
            "steps_performed": "LEAK", "next_steps": "LEAK"}
    safe = ag._followup_meta_safe(meta)
    assert "steps_performed" not in safe and "next_steps" not in safe
    assert safe["message"] == "how is pain?"
