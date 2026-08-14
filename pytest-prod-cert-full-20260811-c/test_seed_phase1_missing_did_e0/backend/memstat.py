"""Process memory sampling — zero dependencies, Linux-only (/proc).

Render's free tier OOM-kills the API at 512MB (first reported 2026-07-11).
/health and the hourly maintenance wake both report through this, so the
growth curve (steady leak vs step-correlated spike) is readable straight
from Render logs and curl.
"""


def process_mem_mb() -> dict | None:
    """{'rss': current MB, 'peak': high-water MB} from /proc/self/status.
    Returns None off-Linux; never raises — callers are health paths."""
    try:
        cur = peak = None
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    cur = int(line.split()[1]) // 1024
                elif line.startswith("VmHWM:"):
                    peak = int(line.split()[1]) // 1024
        if cur is None:
            return None
        return {"rss": cur, "peak": peak}
    except OSError:
        return None
