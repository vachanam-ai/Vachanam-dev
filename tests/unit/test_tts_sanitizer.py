from agent.services.tts_sanitizer import sanitize_for_tts


def test_bold_markdown_stripped():
    assert sanitize_for_tts("**Token number** is ready") == "Token number is ready"


def test_italic_markdown_stripped():
    assert sanitize_for_tts("*urgent* appointment") == "urgent appointment"


def test_hash_number_converted():
    # Markdown hash is removed; token number remains natural for Soniox.
    result = sanitize_for_tts("Token #8 confirmed")
    assert result == "Token 8 confirmed"


def test_markdown_header_stripped():
    assert sanitize_for_tts("## Welcome to Vachanam") == "Welcome to Vachanam"


def test_dash_bullet_stripped():
    result = sanitize_for_tts("- Morning slot\n- Evening slot")
    assert "#" not in result
    assert "-" not in result


def test_asterisk_bullet_stripped():
    result = sanitize_for_tts("* Token 1\n* Token 2")
    assert result.strip().startswith("Token")


def test_multiple_spaces_collapsed():
    result = sanitize_for_tts("Hello   world")
    assert "  " not in result


def test_emoji_stripped():
    result = sanitize_for_tts("Booking confirmed ✅")
    assert "✅" not in result


def test_numbered_list_dot_stripped():
    # "8. Next patient" — the "8." should become "8"
    result = sanitize_for_tts("8. Next patient please")
    assert "8." not in result


def test_clean_small_numbers_remain_natural():
    result = sanitize_for_tts("Your token number is 5. Doctor will see you soon.")
    assert result == "Your token number is 5. Doctor will see you soon."


def test_combined_markdown():
    result = sanitize_for_tts("**Token #3** confirmed! ✅\n- See you at 10:30")
    assert "**" not in result
    assert "#" not in result
    assert "✅" not in result
