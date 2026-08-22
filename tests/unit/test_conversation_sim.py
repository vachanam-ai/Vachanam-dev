"""C6+ multi-turn sim: roles alternate (caller first), ends on a thanks turn.
Gemini mocked."""
from agent.eval import conversation_sim


class _Resp:
    def __init__(self, text):
        self.text = text


class _ScriptedModels:
    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0

    def generate_content(self, model, contents):
        self.calls += 1
        return _Resp(self._turns.pop(0) if self._turns else "...")


class _ScriptedClient:
    def __init__(self, turns):
        self.models = _ScriptedModels(turns)


def test_conversation_alternates_and_ends_on_thanks():
    # caller, agent, caller(thanks) -> stops after the thanks turn
    client = _ScriptedClient([
        "హలో, అపాయింట్‌మెంట్ కావాలి.",      # caller (turn 0)
        "నమస్తే అండి, ఏ రోజు కావాలి అండి?",  # agent  (turn 1)
        "ఓకే, ధన్యవాదాలు అండి.",            # caller (turn 2) — thanks -> end
    ])
    t = conversation_sim.simulate_conversation(
        {"persona": "a patient", "goal": "book"}, client=client, max_turns=6
    )
    roles = [x["role"] for x in t]
    assert roles == ["user", "agent", "user"]   # caller starts, alternates, ends on thanks
    assert "ధన్యవాదాలు" in t[-1]["text"]


def test_build_live_agent_prompt_wraps_real_prompt_with_facts():
    from agent.prompts.system_prompt import DoctorContext

    docs = [DoctorContext(id="d1", name="అనిల్", specialization="dermatology",
                          routing_keywords=["skin"], booking_type="appointment", is_default=True)]
    p = conversation_sim.build_live_agent_prompt(
        docs, "- Consultation fee: four hundred rupees.", clinic="ఆరోగ్య"
    )
    # sim wrapper forbids tools + injects the facts
    assert "NO tools" in p and "KNOWN FACTS" in p
    assert "four hundred rupees" in p
    # The REAL receptionist prompt is included (clinic-window time rule + phone digits).
    assert "compare both interpretations" in p and "PLAIN DIGITS" in p
    assert '<call_type kind="runtime">' in p
    assert "exactly one <speak>...</speak> envelope" in p


def test_live_prompt_sim_enforces_and_strips_production_speech_envelope():
    live_prompt = conversation_sim.build_live_agent_prompt([], "none")
    client = _ScriptedClient([
        "అపాయింట్‌మెంట్ కావాలి.",
        "<speak>ఏ రోజు కావాలండి?</speak>",
    ])
    transcript = conversation_sim.simulate_conversation(
        {"persona": "p", "goal": "book"},
        client=client,
        agent_prompt=live_prompt,
        max_turns=2,
    )
    assert transcript[-1] == {"role": "agent", "text": "ఏ రోజు కావాలండి?"}


def test_live_prompt_sim_has_exactly_one_authoritative_call_mode():
    expected_modes = {
        "inbound_booking": "inbound_booking",
        "reminder": "reminder",
        "cascade_rebook": "cascade_rebook",
        "next_visit": "next_visit_book",
        "doctor_advice": "doctor_advice",
        "question_answer": "question_answer",
    }
    for requested, expected in expected_modes.items():
        prompt = conversation_sim.build_live_agent_prompt(
            [], "none", call_type=requested
        )
        assert prompt.count("<private_session_context>") == 1
        assert prompt.count(f"<call_mode>{expected}</call_mode>") == 1
        assert all(
            f"<call_mode>{other}</call_mode>" not in prompt
            for other in set(expected_modes.values()) - {expected}
        )


def test_live_prompt_sim_rejects_unknown_call_mode():
    try:
        conversation_sim.build_live_agent_prompt([], "none", call_type="made_up")
    except ValueError as exc:
        assert str(exc) == "unsupported live call type: made_up"
    else:
        raise AssertionError("unknown call mode was accepted")


def test_agent_first_inbound_order():
    # inbound-faithful: agent greets first, then caller, then agent.
    client = _ScriptedClient(["నమస్కారం అండి.", "అపాయింట్‌మెంట్ కావాలి.", "ఏ రోజు అండి?"])
    t = conversation_sim.simulate_conversation(
        {"persona": "p", "goal": "g"}, client=client, max_turns=3, agent_first=True
    )
    assert [x["role"] for x in t] == ["agent", "user", "agent"]


def test_conversation_respects_max_turns():
    client = _ScriptedClient(["turn"] * 10)  # never says thanks
    t = conversation_sim.simulate_conversation(
        {"persona": "p", "goal": "g"}, client=client, max_turns=4
    )
    assert len(t) == 4
