"""Check: backchannel picker never repeats and every ack is reachable."""
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from backchannel import BACKCHANNELS, pick_backchannel  # noqa: E402


def test_never_repeats() -> None:
    prev = None
    for _ in range(200):
        bc = pick_backchannel(prev)
        assert bc in BACKCHANNELS
        assert bc != prev  # never twice running
        prev = bc


def test_covers_pool() -> None:
    seen = Counter(pick_backchannel(None) for _ in range(400))
    assert set(seen) == set(BACKCHANNELS)  # every ack reachable


if __name__ == "__main__":
    test_never_repeats()
    test_covers_pool()
    print("ok")
