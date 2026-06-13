"""Vobiz CDR (call-detail-records) client — authoritative call/minute source.

Vobiz records every call server-side regardless of what the agent process does,
so pulling its CDRs is the reliable source for "calls answered" + voice minutes:
it survives dropped calls, agent crashes, and local dev runs (the agent-written
CallLog rows were unreliable in exactly those cases).

API (Plivo-compatible): GET {base}/Account/{auth_id}/Call/ with X-Auth-ID /
X-Auth-Token headers, returns {"objects": [ ...call records... ]}. Field names
vary slightly across providers/versions, so parsing is defensive (.get fallbacks).
"""
from datetime import datetime, timezone

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()


def _parse_dt(raw) -> datetime | None:
    """Parse a Vobiz timestamp into a tz-aware UTC datetime, else None."""
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def parse_call_record(o: dict) -> dict | None:
    """Normalize one Vobiz call object into our shape, or None if unusable."""
    cid = o.get("call_uuid") or o.get("CallUUID") or o.get("id")
    if not cid:
        return None
    dur_raw = (
        o.get("call_duration")
        if o.get("call_duration") is not None
        else o.get("bill_duration")
        if o.get("bill_duration") is not None
        else o.get("duration")
    )
    try:
        duration = int(float(dur_raw or 0))
    except (ValueError, TypeError):
        duration = 0
    answer_time = o.get("answer_time") or o.get("AnswerTime")
    started = (
        _parse_dt(answer_time)
        or _parse_dt(o.get("initiation_time") or o.get("start_time"))
        or _parse_dt(o.get("end_time") or o.get("EndTime"))
    )
    return {
        "provider_call_id": str(cid),
        "to_number": o.get("to_number") or o.get("to") or o.get("To"),
        "from_number": o.get("from_number") or o.get("from") or o.get("From"),
        "duration_seconds": max(0, duration),
        "started_at": started or datetime.now(timezone.utc),
        "answered": bool(answer_time) or duration > 0,
        "direction": (o.get("call_direction") or o.get("direction") or "inbound").lower(),
    }


async def fetch_recent_calls(since: datetime, limit: int = 200) -> list[dict]:
    """Fetch Vobiz CDRs since ``since`` (UTC). Returns parsed records.

    Never raises — telephony control-plane hiccups must not crash the sync job.
    Returns [] when creds are unset (e.g. CI / local without Vobiz).
    """
    auth_id, auth_token = settings.vobiz_auth_id, settings.vobiz_auth_token
    if not (auth_id and auth_token):
        return []

    base = getattr(settings, "vobiz_api_base", "https://api.vobiz.ai/api/v1")
    url = f"{base}/Account/{auth_id}/Call/"
    headers = {"X-Auth-ID": auth_id, "X-Auth-Token": auth_token}
    params = {
        "limit": limit,
        "end_time__gte": since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("vobiz_cdr_fetch_failed", error=str(e))
        return []

    objects = data.get("objects") or data.get("calls") or data.get("data") or []
    out = []
    for o in objects:
        rec = parse_call_record(o) if isinstance(o, dict) else None
        if rec:
            out.append(rec)
    return out
