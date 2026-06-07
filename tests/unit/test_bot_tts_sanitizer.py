"""Unit tests for TtsSanitizerProcessor in agent/bot.py.

TDD Step 1 (Task 8): write tests before implementation.
These must FAIL before TtsSanitizerProcessor is added to bot.py.

Pipecat 1.3.0 design notes:
- FrameProcessor.process_frame() does NOT return the frame.
  Override calls super().process_frame() first (handles infrastructure frames:
  StartFrame, CancelFrame, etc.), then mutates TextFrame and calls push_frame().
- Tests inject a capture coroutine as push_frame to intercept the pushed frame
  without needing a full pipeline context.
"""
import pytest


@pytest.mark.asyncio
async def test_tts_sanitizer_strips_markdown():
    """TtsSanitizerProcessor must strip markdown from TextFrame.text via sanitize_for_tts()
    before pushing the frame downstream.
    """
    from agent.bot import TtsSanitizerProcessor
    from pipecat.frames.frames import TextFrame

    proc = TtsSanitizerProcessor()

    pushed_frames: list = []

    async def capture_push(frame, direction=None):
        pushed_frames.append(frame)

    # Override push_frame to capture pushed frames without needing a full pipeline
    proc.push_frame = capture_push

    frame = TextFrame(text="**Token #8** confirmed!")
    # process_frame returns None; effects are visible via push_frame captures
    await proc.process_frame(frame, direction="downstream")

    assert len(pushed_frames) == 1, f"Expected 1 frame pushed, got {len(pushed_frames)}"
    out = pushed_frames[0]
    assert "**" not in out.text, f"Bold markdown not stripped: {out.text!r}"
    assert "#" not in out.text, f"Hash-number pattern not stripped: {out.text!r}"
    # Verify the text content is still meaningful after sanitization
    assert "Token" in out.text
    assert "8" in out.text
    assert "confirmed" in out.text


@pytest.mark.asyncio
async def test_tts_sanitizer_passes_non_text_frames_through():
    """TtsSanitizerProcessor must pass non-TextFrame frames through unchanged (same object).

    Uses AudioRawFrame (a plain data frame) to avoid StartFrame's special
    infrastructure handling in the base class.
    """
    from agent.bot import TtsSanitizerProcessor
    from pipecat.frames.frames import AudioRawFrame

    proc = TtsSanitizerProcessor()

    pushed_frames: list = []

    async def capture_push(frame, direction=None):
        pushed_frames.append(frame)

    proc.push_frame = capture_push

    # AudioRawFrame is a non-text data frame; processor should pass it through unchanged
    frame = AudioRawFrame(audio=b"\x00\x01", sample_rate=8000, num_channels=1)
    await proc.process_frame(frame, direction="downstream")

    assert len(pushed_frames) == 1, (
        f"Non-TextFrame should be pushed through unchanged; got {len(pushed_frames)} frames"
    )
    assert pushed_frames[0] is frame, (
        "Non-TextFrame should be the exact same object (no copy, no mutation)"
    )
