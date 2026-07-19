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
    # the REAL receptionist prompt is included (its AM/PM ban + #408 digit rule)
    assert '"AM"' in p and "NUMBERS ARE ALWAYS DIGITS" in p


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
