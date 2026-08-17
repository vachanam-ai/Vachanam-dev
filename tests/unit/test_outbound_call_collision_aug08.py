"""A patient's phone rings once, whichever job decided to call them.

Vinay 2026-08-08: "i think for remainder calls 2 calls triggering at same time
for 1 appointment. instead of just triggering 1 call."

FOUR independent jobs dial patients — pre_appt_reminder, next_visit_followup,
cascade_rebook and question_callback — and none of them knew about the others.
Each dispatches into a fresh `{kind}-{uuid4}` room, so nothing anywhere says
"this number is already being rung". An appointment reminder and a treatment
follow-up falling due in the same minute produce two simultaneous calls, and a
retry can do it with one job alone.

I could NOT reproduce it from the retained logs (one reminder room in the
window) and the leader election checked out — the pooler is on port 5432,
session mode, where advisory locks do hold. So this is a guard that makes the
outcome impossible rather than a fix for a proven single cause: what the
patient experiences is two phones ringing, and they do not care which job did
it.
"""
import pytest

from backend.services import outbound_guard


class _FakeRedis:
    """Just enough SET NX EX / DELETE to prove the mutual exclusion."""

    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail
        self.calls = []

    async def set(self, key, val, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append((key, val, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


@pytest.fixture
def redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr("backend.redis_client.get_redis", lambda: r)
    return r


PHONE = "+919876543210"
BRANCH = "branch-a"


@pytest.mark.asyncio
async def test_the_first_job_to_claim_a_number_wins(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True


@pytest.mark.asyncio
async def test_a_second_job_is_turned_away(redis):
    """The reported symptom: a reminder and a follow-up in the same minute."""
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True
    assert await outbound_guard.claim_outbound_call(PHONE, "next_visit") is False


@pytest.mark.asyncio
async def test_the_same_job_twice_is_also_turned_away(redis):
    """One job retrying before its own flag commits is the single-job case."""
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is False


@pytest.mark.asyncio
async def test_a_different_patient_is_unaffected(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True
    assert await outbound_guard.claim_outbound_call("+919000000001", "reminder") is True


@pytest.mark.asyncio
async def test_the_lock_is_keyed_on_the_last_ten_digits(redis):
    """Numbers are stored inconsistently (+91.., 0.., bare). Two spellings of
    one phone must not both get a call."""
    assert await outbound_guard.claim_outbound_call("+919876543210", "reminder") is True
    assert await outbound_guard.claim_outbound_call("09876543210", "next_visit") is False
    assert await outbound_guard.claim_outbound_call("9876543210", "rebook") is False


@pytest.mark.asyncio
async def test_the_claim_always_carries_an_expiry(redis):
    """Without a TTL a crashed worker would block that number forever."""
    await outbound_guard.claim_outbound_call(PHONE, "reminder")
    _key, _val, nx, ex = redis.calls[-1]
    assert nx is True
    assert isinstance(ex, int) and 60 <= ex <= 600


@pytest.mark.asyncio
async def test_a_failed_dispatch_hands_the_number_straight_back(redis):
    """A real retry must not wait out the TTL for a call that never happened."""
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True
    await outbound_guard.release_outbound_call(PHONE)
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True


@pytest.mark.asyncio
async def test_redis_trouble_fails_open(monkeypatch):
    """RULE 8. A doubled reminder is annoying; a reminder that never goes out
    because Redis hiccuped is a missed appointment the patient paid for."""
    monkeypatch.setattr("backend.redis_client.get_redis", lambda: _FakeRedis(fail=True))
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is True


@pytest.mark.asyncio
async def test_an_unusable_number_is_never_blocked(redis):
    for bad in (None, "", "123"):
        assert await outbound_guard.claim_outbound_call(bad, "reminder") is True


def test_the_key_carries_no_name_and_no_full_number():
    """RULE 9."""
    key = outbound_guard.lock_key(PHONE, BRANCH)
    assert key == "outbound:call:branch-a:9876543210"
    assert "+91" not in key


@pytest.mark.asyncio
async def test_same_number_at_another_clinic_is_unaffected(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder", "branch-a")
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder", "branch-b")


# ── every dialer is behind the guard ─────────────────────────────────────────

@pytest.mark.parametrize("module,func", [
    ("backend.jobs.pre_appt_reminder", "_dispatch_reminder_call"),
    ("backend.jobs.next_visit_followup_caller", "_dispatch"),
    ("backend.jobs.cascade_rebook_caller", "_dispatch_rebook_call"),
    ("backend.jobs.question_callback_caller", "_dispatch"),
])
def test_every_outbound_job_claims_before_dialing(module, func):
    """A fifth dialer added later without this is a regression, and the only
    way anyone finds out is a patient with two phones ringing."""
    import importlib
    import inspect

    mod = importlib.import_module(module)
    fn = getattr(mod, func, None)
    assert fn is not None, f"{module}.{func} no longer exists — update this test"
    src = inspect.getsource(fn)
    assert "claim_outbound_call" in src, (
        f"{module}.{func} dials without claiming the number first"
    )
    # The ATTRIBUTE call, not the bare word: several of these docstrings
    # discuss create_dispatch by name long before any code runs.
    assert src.index("claim_outbound_call") < src.index("agent_dispatch.create_dispatch"), (
        f"{module}.{func} claims the number AFTER dispatching, which guards "
        f"nothing"
    )
