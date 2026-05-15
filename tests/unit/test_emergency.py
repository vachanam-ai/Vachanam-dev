import pytest
from agent.services.emergency import is_emergency


def test_heart_attack_english():
    assert is_emergency("I am having a heart attack") is True


def test_chest_pain_english():
    assert is_emergency("severe chest pain right now") is True


def test_unconscious_english():
    assert is_emergency("he is unconscious on the floor") is True


def test_not_breathing():
    assert is_emergency("patient is not breathing") is True


def test_severe_bleeding():
    assert is_emergency("there is severe bleeding") is True


def test_telugu_emergency_keyword():
    # "padipōyāḍu" = collapsed / fell down
    assert is_emergency("padipōyāḍu") is True


def test_routine_headache_not_emergency():
    assert is_emergency("I have a headache since yesterday") is False


def test_routine_fever_not_emergency():
    assert is_emergency("fever for two days") is False


def test_empty_string_not_emergency():
    assert is_emergency("") is False


def test_routine_dental_not_emergency():
    assert is_emergency("my tooth is paining") is False


def test_case_insensitive():
    assert is_emergency("HEART ATTACK") is True


def test_keyword_in_middle_of_sentence():
    assert is_emergency("please help my father is unconscious") is True
