"""Safety guards for the Venkateshwara latency-sandbox phone route."""
from __future__ import annotations

import inspect

from scripts import route_venkateshwara_tts_sandbox as route


def test_did_routing_uses_a_separate_inbound_trunk():
    source = inspect.getsource(route.apply)
    assert "create_inbound_trunk" in source
    assert "numbers=[VENKAT]" in source
    assert "trunk_ids=[sandbox_trunk.sip_trunk_id]" in source
    assert "update_inbound_trunk_fields" in inspect.getsource(route._set_numbers)


def test_did_is_never_put_in_the_caller_number_filter():
    source = inspect.getsource(route.apply)
    assert "inbound_numbers=[route.VENKAT]" not in source
    assert "inbound_numbers=[VENKAT]" not in source


def test_failure_path_cleans_conflicting_trunk_then_restores_production():
    source = inspect.getsource(route.apply)
    restore = source.index("[*prod.numbers, VENKAT]")
    delete_rule = source.index("delete_dispatch_rule")
    assert delete_rule < restore


def test_revert_restores_prod_and_deletes_sandbox_resources():
    source = inspect.getsource(route.revert)
    assert "[*prod_trunk.numbers, VENKAT]" in source
    assert "delete_dispatch_rule" in source
    assert "delete_trunk" in source
