"""Focused tests for the patient-name identity boundary."""

from agent.tools.booking_tools import _names_overlap, _normalize_name


def _matches(spoken: str, stored: str) -> bool:
    return _names_overlap(_normalize_name(spoken), _normalize_name(stored))


def test_first_name_matches_the_first_token_of_a_full_name():
    assert _matches("Ravi", "Ravi Kumar") is True
    assert _matches("Ravi Kumar", "Ravi") is True


def test_surname_alone_does_not_match_a_full_name():
    assert _matches("Kumar", "Ravi Kumar") is False
    assert _matches("Ravi Kumar", "Kumar") is False


def test_reordered_complete_name_matches():
    assert _matches("Kumar Ravi", "Ravi Kumar") is True


def test_shared_token_between_different_full_names_does_not_match():
    assert _matches("Ravi Sharma", "Ravi Kumar") is False


def test_existing_case_and_honorific_normalization_is_preserved():
    assert _matches("Mr. RAVI kumar garu", "Ravi Kumar") is True
