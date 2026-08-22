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
import asyncio

import pytest

from backend.services import outbound_guard


class _FakeRedis:
    """Just enough SET NX EX / compare-and-delete to prove exclusion."""

    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail
        self.calls = []
        self.renewed = asyncio.Event()

    async def set(self, key, val, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append((key, val, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True

    async def eval(self, script, numkeys, key, owner, *args):
        assert numkeys == 1
        if script == outbound_guard._RENEW_LUA:
            assert args == (outbound_guard.LOCK_TTL_SECONDS,)
            self.renewed.set()
            return int(self.store.get(key) == owner)
        assert script == outbound_guard._RELEASE_LUA
        assert not args
        if self.store.get(key) != owner:
            return 0
        del self.store[key]
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
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")


@pytest.mark.asyncio
async def test_a_second_job_is_turned_away(redis):
    """The reported symptom: a reminder and a follow-up in the same minute."""
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert await outbound_guard.claim_outbound_call(PHONE, "next_visit") is None


@pytest.mark.asyncio
async def test_the_same_job_twice_is_also_turned_away(redis):
    """One job retrying before its own flag commits is the single-job case."""
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder") is None


@pytest.mark.asyncio
async def test_a_different_patient_is_unaffected(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert await outbound_guard.claim_outbound_call("+919000000001", "reminder")


@pytest.mark.asyncio
async def test_the_lock_is_keyed_on_the_last_ten_digits(redis):
    """Numbers are stored inconsistently (+91.., 0.., bare). Two spellings of
    one phone must not both get a call."""
    assert await outbound_guard.claim_outbound_call("+919876543210", "reminder")
    assert await outbound_guard.claim_outbound_call("09876543210", "next_visit") is None
    assert await outbound_guard.claim_outbound_call("9876543210", "rebook") is None


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
    owner = await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert owner
    await outbound_guard.release_outbound_call(PHONE, owner)
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")


@pytest.mark.asyncio
async def test_stale_owner_cannot_release_a_new_owners_lock(redis):
    """TTL expiry can let B claim while A's failed dispatch is still unwinding."""
    stale_owner = await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert stale_owner
    key = outbound_guard.lock_key(PHONE)
    redis.store.pop(key)  # simulate A's TTL expiring
    new_owner = await outbound_guard.claim_outbound_call(PHONE, "next_visit")
    assert new_owner and new_owner != stale_owner

    await outbound_guard.release_outbound_call(PHONE, stale_owner)

    assert redis.store[key] == new_owner
    assert not await outbound_guard.claim_outbound_call(PHONE, "rebook")


@pytest.mark.asyncio
async def test_worker_renews_for_call_lifetime_and_stale_owner_stops(
    redis, monkeypatch
):
    owner = await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert owner
    key = outbound_guard.lock_key(PHONE)
    monkeypatch.setattr(outbound_guard, "LOCK_RENEW_SECONDS", 0)
    renewal = asyncio.create_task(outbound_guard.maintain_outbound_claim(key, owner))
    await asyncio.wait_for(redis.renewed.wait(), timeout=0.2)

    new_owner = "next_visit:new-owner"
    redis.store[key] = new_owner
    await asyncio.wait_for(renewal, timeout=0.2)
    await outbound_guard.finish_outbound_claim(renewal, key, owner)

    assert redis.store[key] == new_owner


@pytest.mark.asyncio
async def test_worker_shutdown_releases_its_current_claim(redis):
    owner = await outbound_guard.claim_outbound_call(PHONE, "reminder")
    assert owner
    key = outbound_guard.lock_key(PHONE)

    await outbound_guard.finish_outbound_claim(None, key, owner)

    assert key not in redis.store


@pytest.mark.asyncio
async def test_unclaimed_cascade_dispatch_releases_exact_claim(
    monkeypatch
):
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from livekit import api as lk_api

    from backend.jobs import cascade_rebook_caller as cascade
    from backend.services import dispatch_verify

    owner = "rebook:test-owner"
    released = []
    dispatched = []

    async def _claim(*_args):
        return owner

    async def _release(phone, claim, branch_id):
        released.append((phone, claim, branch_id))

    async def _not_claimed(*_args):
        return False

    class _Dispatch:
        async def create_dispatch(self, request):
            dispatched.append(request)

    class _LiveKit:
        agent_dispatch = _Dispatch()

        async def aclose(self):
            pass

    monkeypatch.setattr(outbound_guard, "claim_outbound_call", _claim)
    monkeypatch.setattr(outbound_guard, "release_outbound_call", _release)
    monkeypatch.setattr(dispatch_verify, "verify_or_cleanup", _not_claimed)
    monkeypatch.setattr(lk_api, "LiveKitAPI", _LiveKit)
    monkeypatch.setattr(
        cascade, "validate_branch_outbound_trunk", lambda _branch, trunk: trunk
    )

    branch_id = uuid4()
    phone = "+919876543210"
    await cascade._dispatch_rebook_call(
        SimpleNamespace(id=uuid4(), branch_id=branch_id, attempt_count=1),
        SimpleNamespace(phone=phone),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(id=branch_id),
        "trunk-1",
    )

    metadata = json.loads(dispatched[0].metadata)
    assert metadata["outbound_lock_key"] == outbound_guard.lock_key(phone)
    assert metadata["outbound_lock_owner"] == owner
    assert phone not in dispatched[0].metadata
    assert released == [(phone, owner, branch_id)]


@pytest.mark.asyncio
async def test_client_close_failure_cannot_turn_a_joined_call_into_retry(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from livekit import api as lk_api

    from backend.jobs import cascade_rebook_caller as cascade
    from backend.services import dispatch_verify

    released = []

    async def _claim(*_args):
        return "rebook:owner"

    async def _release(*args):
        released.append(args)

    async def _joined(*_args):
        return True

    class _Dispatch:
        async def create_dispatch(self, _request):
            return None

    class _LiveKit:
        agent_dispatch = _Dispatch()

        async def aclose(self):
            raise ConnectionError("close failed after handoff")

    monkeypatch.setattr(outbound_guard, "claim_outbound_call", _claim)
    monkeypatch.setattr(outbound_guard, "release_outbound_call", _release)
    monkeypatch.setattr(dispatch_verify, "verify_or_cleanup", _joined)
    monkeypatch.setattr(lk_api, "LiveKitAPI", _LiveKit)
    monkeypatch.setattr(
        cascade, "validate_branch_outbound_trunk", lambda _branch, trunk: trunk
    )

    branch_id = uuid4()
    result = await cascade._dispatch_rebook_call(
        SimpleNamespace(id=uuid4(), branch_id=branch_id, attempt_count=0),
        SimpleNamespace(phone="+919876543210"),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(id=branch_id),
        "trunk-1",
    )

    assert result is True
    assert released == []


@pytest.mark.asyncio
async def test_redis_trouble_fails_open(monkeypatch):
    """RULE 8. A doubled reminder is annoying; a reminder that never goes out
    because Redis hiccuped is a missed appointment the patient paid for."""
    monkeypatch.setattr("backend.redis_client.get_redis", lambda: _FakeRedis(fail=True))
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder")


@pytest.mark.asyncio
async def test_an_unusable_number_is_never_blocked(redis):
    for bad in (None, "", "123"):
        assert await outbound_guard.claim_outbound_call(bad, "reminder")


def test_the_key_carries_no_phone_digits_or_branch_identifier():
    """RULE 9: Redis and logs get only a stable HMAC fingerprint."""
    key = outbound_guard.lock_key(PHONE, BRANCH)
    assert key.startswith("outbound:call:")
    assert "9876543210" not in key
    assert "+91" not in key
    assert BRANCH not in key
    assert key == outbound_guard.lock_key("09876543210", "branch-b")


@pytest.mark.asyncio
async def test_same_handset_at_another_clinic_is_serialized(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder", "branch-a")
    assert not await outbound_guard.claim_outbound_call(
        PHONE, "reminder", "branch-b"
    )


@pytest.mark.asyncio
async def test_distinct_handsets_at_different_clinics_still_run_together(redis):
    assert await outbound_guard.claim_outbound_call(PHONE, "reminder", "branch-a")
    assert await outbound_guard.claim_outbound_call(
        "+919000000001", "reminder", "branch-b"
    )


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


@pytest.mark.parametrize("module,func", [
    ("backend.jobs.pre_appt_reminder", "_dispatch_reminder_call"),
    ("backend.jobs.next_visit_followup_caller", "_dispatch"),
    ("backend.jobs.cascade_rebook_caller", "_dispatch_rebook_call"),
    ("backend.jobs.question_callback_caller", "_dispatch"),
])
def test_every_failed_dispatch_releases_its_exact_claim(module, func):
    """Never regress to a phone-only DELETE that can remove a newer claim."""
    import ast
    import importlib
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(getattr(importlib.import_module(module), func)))
    tree = ast.parse(source)
    releases = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "release_outbound_call"
    ]
    assert releases, f"{module}.{func} has no failed-dispatch release"
    assert all(
        len(call.args) >= 2
        and isinstance(call.args[1], ast.Name)
        and call.args[1].id == "outbound_claim"
        for call in releases
    ), f"{module}.{func} must compare-and-delete its exact outbound_claim"
