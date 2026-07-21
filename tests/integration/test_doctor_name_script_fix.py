"""FIXLOG #294 — live 2026-07-08: patient asked for Dr. Lakshmi by name; the
LLM passed the NATIVE-SCRIPT name; substring match against Latin DB names
failed; with no route_to_doctor fallback the whole booking died on
"Unknown doctor" twice. Guards: (a) non-ASCII doctor names transliterate to
Latin before matching, (b) a no-match with real doctors present returns a
SELF-HEALING error listing the actual names + retry instruction, (c) prompt
pins the pass-the-listed-name rule."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.schema import Branch, Doctor, Organization
from agent.session_state import SessionState



@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(name="Script Clinic", owner_phone="+919999999294",
                       owner_email="s294@clinic.test", plan="clinic", status="active")
    db.add(org)
    await db.flush()
    branch = Branch(org_id=org.id, name="Script Branch",
                    whatsapp_number="+911111112294", did_number="+912222222294",
                    google_calendar_id="s294@group.calendar.google.com", status="active")
    db.add(branch)
    await db.flush()
    await db.commit()
    return {"org": org, "branch": branch}


def _agent(state, db):
    from agent.livekit_minimal.agent import VachanamAgent
    return VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=None, transfer_to="",
    )


async def _seed(clinic, db):
    branch = clinic["branch"]
    db.add_all([
        Doctor(branch_id=branch.id, name="Dr. Lakshmi", specialization="skin",
               routing_keywords=["skin"], booking_type="appointment", status="active"),
        Doctor(branch_id=branch.id, name="Dr. Srinivas", specialization="dentistry",
               routing_keywords=["tooth"], booking_type="token", status="active"),
    ])
    await db.commit()
    return branch


async def test_native_script_doctor_name_resolves(clinic, db, monkeypatch):
    """"లక్ష్మి" (Telugu) must resolve to the Latin "Dr. Lakshmi" row."""
    branch = await _seed(clinic, db)
    state = SessionState(session_id="s294a")
    state.branch_id = branch.id
    agent = _agent(state, db)

    async def fake_spoken_text(text, lang):  # offline transliteration stub
        assert lang == "en"
        return "Lakshmi"

    import agent.livekit_minimal.agent as ag
    monkeypatch.setattr(ag, "spoken_text", fake_spoken_text)

    resolved = await agent._resolve_doctor_id("డాక్టర్ లక్ష్మి")
    doc = (await db.execute(select(Doctor).where(Doctor.id == resolved))).scalar_one()
    assert doc.name == "Dr. Lakshmi"


async def test_no_match_error_lists_real_doctors(clinic, db, monkeypatch):
    """Dead-end becomes recovery: error carries the actual names + retry order."""
    from livekit.agents import ToolError

    branch = await _seed(clinic, db)
    state = SessionState(session_id="s294b")
    state.branch_id = branch.id
    agent = _agent(state, db)

    async def fake_spoken_text(text, lang):
        return text  # transliteration failed / returned input (RULE 8 path)

    import agent.livekit_minimal.agent as ag
    monkeypatch.setattr(ag, "spoken_text", fake_spoken_text)

    with pytest.raises(ToolError) as e:
        await agent._resolve_doctor_id("డాక్టర్ లక్ష్మణ్రావు")
    msg = str(e.value)
    assert "Dr. Lakshmi" in msg and "Dr. Srinivas" in msg
    assert "Retry the SAME tool call" in msg


async def test_transliteration_failure_still_safe(clinic, db, monkeypatch):
    """spoken_text raising must not crash resolution (RULE 8)."""
    from livekit.agents import ToolError

    branch = await _seed(clinic, db)
    state = SessionState(session_id="s294c")
    state.branch_id = branch.id
    agent = _agent(state, db)

    async def boom(text, lang):
        raise RuntimeError("sarvam down")

    import agent.livekit_minimal.agent as ag
    monkeypatch.setattr(ag, "spoken_text", boom)

    with pytest.raises(ToolError):  # instructive error, not a crash
        await agent._resolve_doctor_id("లక్ష్మి")


async def test_state_fallback_unaffected(clinic, db):
    """A no-match with state.doctor_id set still falls back silently."""
    branch = await _seed(clinic, db)
    lakshmi = (await db.execute(
        select(Doctor).where(Doctor.name == "Dr. Lakshmi"))).scalar_one()
    state = SessionState(session_id="s294d")
    state.branch_id = branch.id
    state.doctor_id = lakshmi.id
    agent = _agent(state, db)
    resolved = await agent._resolve_doctor_id("nonexistent person")
    assert resolved == lakshmi.id


def test_prompt_pins_listed_name_rule():
    from agent.prompts.system_prompt import build_system_prompt, DoctorContext
    p = build_system_prompt(
        clinic_name="C", doctors=[DoctorContext(
            id="1", name="Dr. Lakshmi", specialization="skin",
            routing_keywords=["skin"], booking_type="appointment", is_default=True)],
        emergency_contact="x", plan="clinic", language="te",
    )
    assert "TOOL CALLS TAKE THE LISTED NAME" in p
    assert "NEVER" in p and "native-script" in p
