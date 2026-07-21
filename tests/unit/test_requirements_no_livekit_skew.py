"""#441 regression: the recurring "AI not answering" pool-death (LK-7) was
version SKEW inside the LiveKit family — agents/soniox floored at >=1.6.5 while
the other plugins floored at >=1.5.x, so a fresh pip resolve installed 1.5.x
inference-subprocess plugins under a 1.6.x job supervisor. The old proc-IPC
protocol then timed out in supervised_proc.initialize() (duplex_unix recv),
looping "error initializing process" and killing the pool (livekit/agents#3785).

Guard: agents + every livekit-plugins-* must be pinned with `==` to the SAME
major.minor. This test fails the moment anyone re-introduces a floor (`>=`) or
mixes trains, so the skew cannot silently return on the next build.
"""
import re
from pathlib import Path

_REQ = Path("agent/livekit_minimal/requirements.txt")
# These are the packages that share the LiveKit Agents release train and MUST
# move together. livekit-api and noise-cancellation version independently.
_TRAIN_PREFIXES = ("livekit-agents", "livekit-plugins-")
_TRAIN_EXCLUDE = ("livekit-plugins-noise-cancellation",)


def _train_lines():
    out = []
    for raw in _REQ.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[=<>!~ ]", line, maxsplit=1)[0]
        if name.startswith(_TRAIN_PREFIXES) and name not in _TRAIN_EXCLUDE:
            out.append((name, line))
    return out


def test_livekit_train_pinned_and_coherent():
    lines = _train_lines()
    assert lines, "no livekit-agents/plugins lines found — path wrong?"

    versions = {}
    for name, line in lines:
        m = re.match(rf"^{re.escape(name)}==(\d+)\.(\d+)\.(\d+)", line)
        assert m, (
            f"{name} must be pinned with `==X.Y.Z` (found `{line}`). A `>=` "
            "floor is exactly what let 1.5.x plugins skew under a 1.6.x agent "
            "supervisor (#441 / livekit/agents#3785)."
        )
        versions[name] = (m.group(1), m.group(2))  # (major, minor)

    minors = set(versions.values())
    assert len(minors) == 1, (
        "LiveKit family is SKEWED across release trains — all of "
        f"{sorted(versions)} must share one major.minor, got {versions}. "
        "This mismatch causes the proc-IPC pool-death (#441)."
    )


def test_agents_is_on_the_train():
    names = {n for n, _ in _train_lines()}
    assert "livekit-agents" in names, "livekit-agents must be pinned in the train"
