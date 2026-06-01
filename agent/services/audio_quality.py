"""Audio quality / garbled-input defense.

Two layers of detection (Component 10 from voice call flow spec):

A. STT confidence threshold — Sarvam Saaras returns per-word confidence in its
   final transcript. If average confidence < 60% → do NOT forward to LLM. Mark
   the turn as garbled and let the silence_handler counter escalate.

B. LLM-side clarification — handled in the system prompt (agent/prompts/
   system_prompt.py), not here. When LLM receives ambiguous text, it responds
   "kshamincandi, mali cheppagalara" and the agent treats that as a garbled turn.

This module owns Layer A only — the confidence calculation and threshold check.
"""
from dataclasses import dataclass

# Threshold below which we consider the transcript too unreliable to forward.
# Tuned heuristically from Sarvam Saaras v3 docs (confidence ∈ [0, 1]). To be
# revisited with real Phase 10 call recordings.
CONFIDENCE_THRESHOLD = 0.60


@dataclass(frozen=True)
class TranscriptQuality:
    """Result of analyzing a Sarvam STT response."""

    is_acceptable: bool
    confidence: float
    word_count: int
    reason: str  # "ok" | "low_confidence" | "empty" | "no_words"


def _word_confidences(stt_response: dict) -> list[float]:
    """Extract per-word confidence scores from a Sarvam Saaras response.

    Sarvam returns transcripts in the shape:
        {
          "transcript": "namaskaram doctor",
          "language_code": "te-IN",
          "words": [{"word": "namaskaram", "confidence": 0.92}, ...]
        }

    Returns: list of confidence floats. Empty list if no per-word confidence
    available (older API responses or partial transcripts).
    """
    words = stt_response.get("words") or []
    out: list[float] = []
    for w in words:
        c = w.get("confidence")
        if isinstance(c, (int, float)):
            out.append(float(c))
    return out


def assess_transcript(stt_response: dict) -> TranscriptQuality:
    """Decide whether to forward a Sarvam STT result to the LLM.

    Args:
        stt_response: dict from Sarvam Saaras (final transcript, not partial)

    Returns:
        TranscriptQuality with is_acceptable flag and reason. Caller should:
          - is_acceptable=True  → forward transcript.get("transcript", "") to LLM
          - is_acceptable=False → play CANNED_GARBLED_RETRY, increment garbled counter
    """
    transcript = stt_response.get("transcript", "")
    if not transcript or not transcript.strip():
        return TranscriptQuality(
            is_acceptable=False,
            confidence=0.0,
            word_count=0,
            reason="empty",
        )

    confs = _word_confidences(stt_response)
    if not confs:
        # No per-word confidence available; conservative: accept the transcript
        # because Sarvam at least produced text. A future Sarvam API change that
        # always returns confidences will tighten this path automatically.
        word_count = len(transcript.split())
        return TranscriptQuality(
            is_acceptable=True,
            confidence=1.0,
            word_count=word_count,
            reason="ok",
        )

    avg_confidence = sum(confs) / len(confs)
    if avg_confidence < CONFIDENCE_THRESHOLD:
        return TranscriptQuality(
            is_acceptable=False,
            confidence=avg_confidence,
            word_count=len(confs),
            reason="low_confidence",
        )

    return TranscriptQuality(
        is_acceptable=True,
        confidence=avg_confidence,
        word_count=len(confs),
        reason="ok",
    )


# Heuristic LLM-output detection — used to flag LLM responses that themselves
# indicate "I didn't understand". When the LLM returns such a response, the
# agent should treat the upstream turn as garbled too (increment counter), even
# though the STT confidence was above threshold.
_LLM_CLARIFICATION_PHRASES = [
    "kshamincandi",          # Telugu: sorry
    "mali cheppagalara",     # Telugu: can you say again
    "sound saripoga vinipinchledu",  # Telugu: didn't hear clearly
    "kshama",                # short
    "could you repeat",
    "could you say that again",
    "didn't catch that",
    "didn't hear",
    "phir se",               # Hindi
    "kya kaha",              # Hindi
]


def is_llm_clarification_request(llm_response_text: str) -> bool:
    """Return True if the LLM is asking the patient to repeat themselves.

    Used by agent.py to detect Layer B (LLM-side clarification) and increment
    the same garbled counter that Layer A maintains. Without this, an STT-passed
    but LLM-rejected turn would not escalate.
    """
    if not llm_response_text:
        return False
    text_lower = llm_response_text.lower()
    return any(phrase in text_lower for phrase in _LLM_CLARIFICATION_PHRASES)
