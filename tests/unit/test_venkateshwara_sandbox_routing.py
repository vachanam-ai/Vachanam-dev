"""Safety guards for the Venkateshwara latency-sandbox phone route."""
from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from scripts import route_venkateshwara_tts_sandbox as route


def test_did_routing_uses_a_separate_inbound_trunk():
    source = inspect.getsource(route.apply)
    assert "create_inbound_trunk" in source
    assert "numbers=[did]" in source
    assert "trunk_ids=[sandbox_trunk.sip_trunk_id]" in source
    assert "update_inbound_trunk_fields" in inspect.getsource(route._set_numbers)


def test_did_is_never_put_in_the_caller_number_filter():
    source = inspect.getsource(route.apply)
    assert "inbound_numbers=[did]" not in source


def test_failure_path_cleans_conflicting_trunk_then_restores_production():
    source = inspect.getsource(route.apply)
    restore = source.index("[*prod.numbers, did]")
    delete_rule = source.index("delete_dispatch_rule")
    assert delete_rule < restore


def test_revert_restores_prod_and_deletes_sandbox_resources():
    source = inspect.getsource(route.revert)
    assert "[*prod_trunk.numbers, did]" in source
    assert "delete_dispatch_rule" in source
    assert "delete_trunk" in source


def test_each_allowed_clinic_gets_distinct_reversible_resources():
    assert route.CLINICS["venkateshwara"] == "+918046733493"
    assert route._names("venkateshwara") == (
        "vobiz-inbound-venkateshwara-sandbox",
        "tts-sandbox-venkateshwara",
    )
    assert route._names("skincare") != route._names("venkateshwara")


def test_routing_fails_closed_without_a_started_sandbox_machine(monkeypatch):
    monkeypatch.setattr(
        route.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([])),
    )
    with pytest.raises(RuntimeError, match="no started Fly machine"):
        route._assert_sandbox_machine_started()


def test_started_sandbox_machine_passes_health_gate(monkeypatch):
    monkeypatch.setattr(
        route.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps([{"state": "started"}])
        ),
    )
    route._assert_sandbox_machine_started()


def test_apply_checks_worker_before_touching_livekit():
    source = inspect.getsource(route.apply)
    assert source.index("_assert_sandbox_machine_started()") < source.index("_api()")
