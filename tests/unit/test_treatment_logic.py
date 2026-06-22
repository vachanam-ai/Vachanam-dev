from backend.services.treatment_logic import resolve_is_final


def test_button_sets_final():
    assert resolve_is_final(True, "keep going") is True


def test_end_keyword_sets_final_case_insensitive():
    assert resolve_is_final(False, "  END ") is True
    assert resolve_is_final(None, "end") is True


def test_partial_word_does_not_close():
    assert resolve_is_final(False, "treatment ending soon") is False
    assert resolve_is_final(None, "send report") is False


def test_default_open():
    assert resolve_is_final(None, None) is False
    assert resolve_is_final(False, "floss daily") is False
