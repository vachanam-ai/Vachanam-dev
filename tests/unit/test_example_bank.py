"""Example bank: de-id gate enforced on write, dedup, seed, retrieval."""
import pytest

from agent.eval.example_bank import ExampleBank
from backend.services.deidentify import DeidentificationError


@pytest.fixture
def bank(tmp_path):
    return ExampleBank(path=tmp_path / "bank.json")


def test_add_and_retrieve(bank):
    assert bank.add("greeting", "నమస్తే అండి, {clinic} నుంచి.") is True
    rows = bank.examples_for("greeting")
    assert len(rows) == 1 and rows[0]["line"].startswith("నమస్తే")


def test_dedup(bank):
    assert bank.add("greeting", "నమస్తే అండి.") is True
    assert bank.add("greeting", "నమస్తే అండి.") is False  # identical → not re-added
    assert len(bank.examples_for("greeting")) == 1


def test_pii_write_rejected(bank):
    # DPDP gate: a line carrying a phone must NOT be storable.
    with pytest.raises(DeidentificationError):
        bank.add("relay", "నేను {name} కి 9876543210 కి కాల్ చేస్తాను.")
    assert bank.all() == []  # nothing written


def test_invalid_source_rejected(bank):
    with pytest.raises(ValueError):
        bank.add("greeting", "నమస్తే అండి.", source="random")


def test_seed_bulk(bank):
    n = bank.seed({"greeting": "నమస్తే అండి.", "ok": "ఓకే అండి."})
    assert n == 2
    assert len(bank.all()) == 2
