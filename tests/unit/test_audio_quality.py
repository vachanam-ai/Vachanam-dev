"""Unit tests for audio_quality module."""

from agent.services.audio_quality import (
    CONFIDENCE_THRESHOLD,
    assess_transcript,
    is_llm_clarification_request,
)


# ──────────────────────────────────────────────────────────────────────────
# assess_transcript — STT confidence threshold (Layer A)
# ──────────────────────────────────────────────────────────────────────────


def test_empty_transcript_is_unacceptable():
    result = assess_transcript({"transcript": "", "words": []})
    assert result.is_acceptable is False
    assert result.reason == "empty"


def test_whitespace_only_transcript_is_unacceptable():
    result = assess_transcript({"transcript": "   ", "words": []})
    assert result.is_acceptable is False
    assert result.reason == "empty"


def test_missing_transcript_key_is_unacceptable():
    result = assess_transcript({})
    assert result.is_acceptable is False
    assert result.reason == "empty"


def test_high_confidence_words_pass():
    response = {
        "transcript": "namaskaram doctor kavali",
        "words": [
            {"word": "namaskaram", "confidence": 0.92},
            {"word": "doctor", "confidence": 0.88},
            {"word": "kavali", "confidence": 0.95},
        ],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is True
    assert result.confidence > CONFIDENCE_THRESHOLD
    assert result.word_count == 3
    assert result.reason == "ok"


def test_low_average_confidence_rejected():
    """Sub-threshold avg (0.4) → don't forward to LLM."""
    response = {
        "transcript": "garbled text here",
        "words": [
            {"word": "garbled", "confidence": 0.3},
            {"word": "text", "confidence": 0.4},
            {"word": "here", "confidence": 0.5},
        ],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is False
    assert result.reason == "low_confidence"
    assert result.confidence < CONFIDENCE_THRESHOLD


def test_at_threshold_exactly_is_accepted():
    """Floor edge: confidence exactly == threshold should pass (not strict less-than)."""
    response = {
        "transcript": "test",
        "words": [{"word": "test", "confidence": CONFIDENCE_THRESHOLD}],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is True


def test_just_below_threshold_rejected():
    response = {
        "transcript": "test",
        "words": [{"word": "test", "confidence": CONFIDENCE_THRESHOLD - 0.01}],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is False


def test_no_word_confidences_falls_back_to_accept():
    """If Sarvam returns no per-word confidence (older API), conservative: accept."""
    response = {"transcript": "namaskaram"}
    result = assess_transcript(response)
    assert result.is_acceptable is True
    assert result.reason == "ok"
    assert result.word_count == 1  # split() on transcript


def test_words_list_present_but_no_confidence_fields():
    """Words present but no confidence keys — same fallback."""
    response = {
        "transcript": "namaskaram doctor",
        "words": [{"word": "namaskaram"}, {"word": "doctor"}],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is True
    assert result.reason == "ok"


def test_mixed_languages_high_confidence_accepted():
    """Telugu + English code-mixing should pass with normal confidence scores."""
    response = {
        "transcript": "doctor appointment kavali tomorrow",
        "words": [
            {"word": "doctor", "confidence": 0.95},
            {"word": "appointment", "confidence": 0.91},
            {"word": "kavali", "confidence": 0.89},
            {"word": "tomorrow", "confidence": 0.93},
        ],
    }
    result = assess_transcript(response)
    assert result.is_acceptable is True


# ──────────────────────────────────────────────────────────────────────────
# is_llm_clarification_request — Layer B detector
# ──────────────────────────────────────────────────────────────────────────


def test_kshamincandi_detected():
    assert is_llm_clarification_request("Kshamincandi, mali cheppagalara?") is True


def test_mali_cheppagalara_detected():
    assert is_llm_clarification_request("Naaku sound saripoga vinipinchledu. Mali cheppagalara?") is True


def test_english_didnt_catch_detected():
    assert is_llm_clarification_request("Sorry, I didn't catch that") is True


def test_hindi_phir_se_detected():
    assert is_llm_clarification_request("Maaf kijiye, phir se boliye") is True


def test_normal_response_not_detected():
    assert is_llm_clarification_request("Mee paeru cheppandi") is False
    assert is_llm_clarification_request("Doctor selected. Confirm cheyali?") is False


def test_empty_string_not_detected():
    assert is_llm_clarification_request("") is False


def test_none_not_detected():
    assert is_llm_clarification_request(None) is False


def test_case_insensitive():
    assert is_llm_clarification_request("KSHAMINCANDI") is True
