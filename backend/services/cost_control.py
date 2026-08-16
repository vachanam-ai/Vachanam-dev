"""Measured usage, immutable rate card, and fail-open provider reconciliation.

The clinic-facing request path never imports or calls this module.  Raw units
are persisted per call; this module prices those units and the existing hourly
maintenance wake captures vendor totals for the product-owner dashboard.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import ceil

import httpx
import structlog
from sqlalchemy import delete, select, text

from backend import database as _db_module
from backend.config import settings
from backend.models.schema import (
    Branch,
    CallLog,
    CallQuality,
    InfrastructureUsageSnapshot,
    Organization,
)
from backend.services.billing_math import month_revenue

logger = structlog.get_logger()

RATE_VERSION = "2026-08-16"

# USD rates are raw vendor units.  Keeping them here, rather than baking a
# rounded rupee/minute into calls, lets the owner audit every component.
SONIOX_STT_USD_PER_AUDIO_HOUR = Decimal("0.12")
SONIOX_TTS_USD_PER_AUDIO_HOUR = Decimal("0.70")
GEMINI_INPUT_USD_PER_MILLION = Decimal("0.30")
GEMINI_CACHED_INPUT_USD_PER_MILLION = Decimal("0.03")
GEMINI_OUTPUT_USD_PER_MILLION = Decimal("2.50")
LIVEKIT_SIP_USD_PER_MINUTE = Decimal("0.004")


def _d(value: float | int | Decimal | None) -> Decimal:
    return Decimal(str(value or 0))


def measured_ai_cost_inr(
    *,
    stt_audio_seconds: float = 0,
    tts_audio_seconds: float = 0,
    llm_prompt_tokens: int = 0,
    llm_cached_tokens: int = 0,
    llm_completion_tokens: int = 0,
) -> float:
    """Price SDK-measured Soniox + Gemini units under ``RATE_VERSION``."""
    fx = _d(settings.cost_usd_inr)
    uncached = max(0, int(llm_prompt_tokens) - int(llm_cached_tokens))
    usd = (
        _d(stt_audio_seconds) / Decimal(3600) * SONIOX_STT_USD_PER_AUDIO_HOUR
        + _d(tts_audio_seconds) / Decimal(3600) * SONIOX_TTS_USD_PER_AUDIO_HOUR
        + _d(uncached) / Decimal(1_000_000) * GEMINI_INPUT_USD_PER_MILLION
        + _d(llm_cached_tokens) / Decimal(1_000_000) * GEMINI_CACHED_INPUT_USD_PER_MILLION
        + _d(llm_completion_tokens) / Decimal(1_000_000) * GEMINI_OUTPUT_USD_PER_MILLION
    )
    return round(float(usd * fx), 6)


def billed_call_minutes(duration_seconds: int | float | None) -> int:
    """LiveKit and telephony bill each non-zero call as a whole minute."""
    seconds = max(0, int(duration_seconds or 0))
    return ceil(seconds / 60) if seconds else 0


def livekit_included_minutes() -> int:
    return 5000 if settings.livekit_plan == "ship" else 1000


def livekit_overage_cost_inr(platform_billed_minutes: int) -> float:
    over = max(0, int(platform_billed_minutes) - livekit_included_minutes())
    return round(
        float(_d(over) * LIVEKIT_SIP_USD_PER_MINUTE * _d(settings.cost_usd_inr)),
        4,
    )


def fixed_shared_cost_inr() -> float:
    return round(
        settings.cost_fly_month_inr
        + settings.cost_render_month_inr
        + settings.cost_supabase_month_inr
        + settings.cost_upstash_month_inr
        + settings.cost_cloudflare_month_inr,
        2,
    )


@dataclass(slots=True)
class Snapshot:
    provider: str
    status: str
    source: str
    used: float | None = None
    limit: float | None = None
    unit: str | None = None
    cost_inr: float | None = None
    details: dict | None = None
    error: str | None = None


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _soniox_snapshot(month_start: datetime, now: datetime) -> Snapshot:
    if not settings.soniox_jp_api_key:
        return Snapshot("soniox", "not_connected", "Soniox usage summary", error="SONIOX_JP_API_KEY missing")
    url = f"{settings.soniox_jp_api_url.rstrip('/')}/usage/summary"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {settings.soniox_jp_api_key}"},
            params={"start_time": _iso_utc(month_start), "end_time": _iso_utc(now)},
        )
        response.raise_for_status()
    payload = response.json()
    total = payload.get("total") or {}
    input_ms = int(total.get("total_input_audio_duration_ms") or 0)
    output_ms = int(total.get("total_output_audio_duration_ms") or 0)
    cost_usd = float(total.get("total_cost_usd") or 0)
    return Snapshot(
        "soniox",
        "live",
        "Soniox project API",
        used=round((input_ms + output_ms) / 60000, 2),
        unit="audio min",
        cost_inr=round(cost_usd * settings.cost_usd_inr, 2),
        details={
            "requests": int(total.get("total_num_requests") or 0),
            "stt_audio_minutes": round(input_ms / 60000, 2),
            "tts_audio_minutes": round(output_ms / 60000, 2),
            "cost_usd": cost_usd,
            "models": [m.get("model") for m in payload.get("models", []) if m.get("model")],
        },
    )


async def _upstash_snapshot(month_start: datetime, now: datetime) -> Snapshot:
    if not (settings.upstash_email and settings.upstash_api_key and settings.upstash_database_id):
        return Snapshot("upstash", "not_connected", "Upstash Developer API", error="UPSTASH_EMAIL/API_KEY/DATABASE_ID missing")
    url = f"https://api.upstash.com/v2/redis/stats/{settings.upstash_database_id}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, auth=(settings.upstash_email, settings.upstash_api_key))
        response.raise_for_status()
    data = response.json()
    billing_usd = float(data.get("total_monthly_billing") or 0)
    requests = float(data.get("total_monthly_requests") or 0)
    return Snapshot(
        "upstash",
        "live",
        "Upstash Developer API",
        used=requests,
        limit=500_000,
        unit="requests",
        cost_inr=round(billing_usd * settings.cost_usd_inr, 2),
        details={
            "storage_bytes": float(data.get("current_storage") or 0),
            "bandwidth_bytes": float(data.get("total_monthly_bandwidth") or 0),
            "read_requests": int(data.get("total_monthly_read_requests") or 0),
            "write_requests": int(data.get("total_monthly_write_requests") or 0),
            "projected_used": _project_month(requests, now, month_start),
        },
    )


async def _fly_snapshot(_month_start: datetime, _now: datetime) -> Snapshot:
    if not settings.fly_api_token:
        return Snapshot("fly", "not_connected", "Fly Machines API", error="FLY_API_TOKEN missing")
    url = f"https://api.machines.dev/v1/apps/{settings.fly_agent_app}/machines"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {settings.fly_api_token}"})
        response.raise_for_status()
    machines = response.json() if isinstance(response.json(), list) else []
    started = sum(1 for m in machines if m.get("state") == "started")
    return Snapshot(
        "fly",
        "live" if started else "warning",
        "Fly Machines API + configured commitment",
        used=float(started),
        unit="running machines",
        cost_inr=settings.cost_fly_month_inr,
        details={
            "app": settings.fly_agent_app,
            "states": {str(m.get("id", ""))[-8:]: m.get("state") for m in machines},
        },
    )


async def _render_snapshot(month_start: datetime, now: datetime) -> Snapshot:
    if not settings.render_api_key:
        return Snapshot("render", "not_connected", "Render API", error="RENDER_API_KEY missing")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://api.render.com/v1/services",
            headers={"Authorization": f"Bearer {settings.render_api_key}"},
            params={"limit": 100},
        )
        response.raise_for_status()
    services = []
    for item in response.json() if isinstance(response.json(), list) else []:
        service = item.get("service", item) if isinstance(item, dict) else {}
        if isinstance(service, dict):
            services.append(service)
    target = next(
        (
            s for s in services
            if (settings.render_service_id and s.get("id") == settings.render_service_id)
            or s.get("name") == "vachanam-backend"
        ),
        None,
    )
    if target is None:
        return Snapshot("render", "warning", "Render API", cost_inr=settings.cost_render_month_inr, error="vachanam-backend service not found")
    suspended = str(target.get("suspended") or "not_suspended")
    plan = ((target.get("serviceDetails") or {}).get("plan"))
    free_hours = max(0.0, (now - month_start).total_seconds() / 3600) if plan == "free" else None
    return Snapshot(
        "render",
        "live" if suspended in {"not_suspended", "false", "None"} else "warning",
        "Render API + configured commitment",
        used=round(free_hours, 1) if free_hours is not None else 1,
        limit=750 if free_hours is not None else None,
        unit="instance hours" if free_hours is not None else "service",
        cost_inr=settings.cost_render_month_inr,
        details={
            "service_id": target.get("id"),
            "plan": plan,
            "suspended": target.get("suspended"),
            "updated_at": target.get("updatedAt"),
            "projected_used": (
                _project_month(free_hours, now, month_start)
                if free_hours is not None
                else None
            ),
        },
    )


async def _cloudflare_snapshot(_month_start: datetime, _now: datetime) -> Snapshot:
    if not settings.cloudflare_api_token:
        return Snapshot("cloudflare", "not_connected", "Cloudflare API", error="CLOUDFLARE_API_TOKEN missing")
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
        )
        response.raise_for_status()
    ok = bool((response.json() or {}).get("success"))
    return Snapshot(
        "cloudflare",
        "live" if ok else "warning",
        "Cloudflare token verification",
        cost_inr=settings.cost_cloudflare_month_inr,
        details={"analytics": "add Account Analytics Read for request/bandwidth totals"},
    )


_COLLECTORS = (
    _soniox_snapshot,
    _upstash_snapshot,
    _fly_snapshot,
    _render_snapshot,
    _cloudflare_snapshot,
)


async def collect_provider_snapshots() -> list[Snapshot]:
    """Collect every provider concurrently; one failure is one stale card."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    results = await asyncio.gather(
        *(fn(month_start, now) for fn in _COLLECTORS), return_exceptions=True
    )
    snapshots: list[Snapshot] = []
    for fn, result in zip(_COLLECTORS, results, strict=True):
        provider = fn.__name__.removeprefix("_").removesuffix("_snapshot")
        if isinstance(result, Exception):
            snapshots.append(
                Snapshot(
                    provider,
                    "error",
                    "provider API",
                    error=f"{type(result).__name__}: {str(result)[:180]}",
                )
            )
        else:
            snapshots.append(result)
    return snapshots


async def run_infrastructure_usage_sync() -> None:
    """Persist one hourly reconciliation sample without adding a DB wake."""
    now = datetime.now(timezone.utc)
    period_start = now.date().replace(day=1)
    snapshots = await collect_provider_snapshots()
    async with _db_module.AsyncSessionLocal() as db:
        for item in snapshots:
            db.add(
                InfrastructureUsageSnapshot(
                    provider=item.provider,
                    status=item.status,
                    source=item.source,
                    period_start=period_start,
                    used=item.used,
                    limit=item.limit,
                    unit=item.unit,
                    cost_inr=item.cost_inr,
                    details=item.details,
                    error=item.error,
                )
            )
        # Ninety days is enough for trend/debugging; invoices remain in the
        # billing system.  Bound this append-only telemetry table permanently.
        await db.execute(
            delete(InfrastructureUsageSnapshot).where(
                InfrastructureUsageSnapshot.captured_at < now - timedelta(days=90)
            )
        )
        await db.commit()
    logger.info(
        "infrastructure_usage_synced",
        providers=len(snapshots),
        healthy=sum(1 for s in snapshots if s.status == "live"),
    )


def _project_month(value: float, now: datetime, month_start: datetime) -> float:
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    elapsed = max(1.0, (now - month_start).total_seconds())
    total = (month_end - month_start).total_seconds()
    return round(value * total / elapsed, 2)


def _provider_card(
    key: str,
    name: str,
    *,
    status: str,
    source: str,
    used: float | None = None,
    limit: float | None = None,
    unit: str | None = None,
    cost_inr: float | None = None,
    updated_at: str | None = None,
    details: dict | None = None,
    error: str | None = None,
) -> dict:
    pct = round(used / limit * 100, 1) if used is not None and limit else None
    action = None
    projected = float((details or {}).get("projected_used") or 0)
    if limit and projected >= limit:
        action = "Upgrade before month end: current pace projects past the configured limit."
    elif pct is not None and pct >= 80:
        action = "Upgrade now: at least 80% of the configured limit is used."
    elif pct is not None and pct >= 60:
        action = "Watch closely: usage passed 60% of the configured limit."
    elif status in {"error", "warning", "stale"}:
        action = "Check the provider connection or console."
    elif status == "not_connected":
        action = "Add the provider telemetry credential to enable reconciliation."
    return {
        "key": key,
        "name": name,
        "status": status,
        "source": source,
        "used": used,
        "limit": limit,
        "unit": unit,
        "pct_used": pct,
        "cost_month_inr": round(cost_inr, 2) if cost_inr is not None else None,
        "updated_at": updated_at,
        "details": details or {},
        "error": error,
        "action": action,
    }


async def build_cost_control_payload(db) -> dict:
    """Build the owner-only monthly cost picture from aggregate, non-PII rows."""
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    orgs = (await db.execute(select(Organization))).scalars().all()
    branches = (await db.execute(select(Branch))).scalars().all()
    branch_org = {branch.id: branch.org_id for branch in branches}
    org_branches: dict = {}
    for branch in branches:
        org_branches.setdefault(branch.org_id, []).append(branch)

    call_rows = (
        await db.execute(
            select(CallLog.branch_id, CallLog.duration_seconds).where(
                CallLog.started_at >= month_start
            )
        )
    ).all()
    quality_rows = (
        await db.execute(
            select(
                CallQuality.branch_id,
                CallQuality.duration_seconds,
                CallQuality.stt_audio_seconds,
                CallQuality.tts_audio_seconds,
                CallQuality.llm_prompt_tokens,
                CallQuality.llm_cached_tokens,
                CallQuality.llm_completion_tokens,
                CallQuality.measured_ai_cost_inr,
            ).where(CallQuality.created_at >= month_start)
        )
    ).all()

    by_org: dict = {}
    for org in orgs:
        by_org[org.id] = {
            "calls": 0,
            "duration_seconds": 0,
            "billed_minutes": 0,
            "telemetry_seconds": 0,
            "stt_seconds": 0.0,
            "tts_seconds": 0.0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "measured_ai": 0.0,
        }
    for branch_id, duration in call_rows:
        oid = branch_org.get(branch_id)
        if oid not in by_org:
            continue
        row = by_org[oid]
        row["calls"] += 1
        row["duration_seconds"] += max(0, int(duration or 0))
        row["billed_minutes"] += billed_call_minutes(duration)
    for q in quality_rows:
        oid = branch_org.get(q.branch_id)
        if oid not in by_org:
            continue
        row = by_org[oid]
        has_usage = bool(
            (q.stt_audio_seconds or 0)
            or (q.tts_audio_seconds or 0)
            or (q.llm_prompt_tokens or 0)
            or (q.llm_completion_tokens or 0)
        )
        if has_usage:
            row["telemetry_seconds"] += max(0, int(q.duration_seconds or 0))
        row["stt_seconds"] += float(q.stt_audio_seconds or 0)
        row["tts_seconds"] += float(q.tts_audio_seconds or 0)
        row["prompt_tokens"] += int(q.llm_prompt_tokens or 0)
        row["cached_tokens"] += int(q.llm_cached_tokens or 0)
        row["completion_tokens"] += int(q.llm_completion_tokens or 0)
        row["measured_ai"] += float(q.measured_ai_cost_inr or 0)

    platform_billed = sum(v["billed_minutes"] for v in by_org.values())
    livekit_cost = livekit_overage_cost_inr(platform_billed)
    active_orgs = [o for o in orgs if o.status in {"active", "trial"}]
    fixed_shared = fixed_shared_cost_inr()
    shared_each = fixed_shared / len(active_orgs) if active_orgs else 0.0

    clinics = []
    for org in orgs:
        usage = by_org[org.id]
        cdr_seconds = usage["duration_seconds"]
        coverage = min(100.0, usage["telemetry_seconds"] / cdr_seconds * 100) if cdr_seconds else 0.0
        uncovered_seconds = max(0, cdr_seconds - usage["telemetry_seconds"])
        # Historical calls pre-date raw SDK telemetry. Keep them visible as an
        # explicit modeled gap instead of silently reporting zero provider cost.
        estimated_gap = uncovered_seconds / 60 * 2.25
        vobiz_cost = usage["billed_minutes"] * settings.cost_vobiz_per_billed_min_inr
        org_livekit = (
            livekit_cost * usage["billed_minutes"] / platform_billed
            if platform_billed
            else 0.0
        )
        dids = sum(1 for b in org_branches.get(org.id, []) if b.did_number)
        did_cost = dids * settings.cost_vobiz_did_month_inr
        shared_allocation = shared_each if org in active_orgs else 0.0
        total = usage["measured_ai"] + estimated_gap + vobiz_cost + org_livekit + did_cost + shared_allocation
        minutes = cdr_seconds / 60
        revenue = month_revenue(org.plan, org.status, minutes)
        profit = revenue - total
        clinics.append(
            {
                "org_id": str(org.id),
                "name": org.name,
                "calls": usage["calls"],
                "cdr_minutes": round(minutes, 2),
                "billed_minutes": usage["billed_minutes"],
                "telemetry_coverage_pct": round(coverage, 1),
                "stt_audio_minutes": round(usage["stt_seconds"] / 60, 2),
                "tts_audio_minutes": round(usage["tts_seconds"] / 60, 2),
                "llm_prompt_tokens": usage["prompt_tokens"],
                "llm_cached_tokens": usage["cached_tokens"],
                "llm_completion_tokens": usage["completion_tokens"],
                "measured_ai_cost_inr": round(usage["measured_ai"], 2),
                "estimated_gap_cost_inr": round(estimated_gap, 2),
                "vobiz_usage_cost_inr": round(vobiz_cost, 2),
                "livekit_cost_inr": round(org_livekit, 2),
                "did_cost_inr": round(did_cost, 2),
                "shared_cost_allocation_inr": round(shared_allocation, 2),
                "total_cost_inr": round(total, 2),
                "revenue_inr": round(revenue, 2),
                "gross_profit_inr": round(profit, 2),
                "gross_margin_pct": round(profit / revenue * 100, 1) if revenue else None,
            }
        )
    clinics.sort(key=lambda item: item["total_cost_inr"], reverse=True)

    latest_rows = (
        await db.execute(
            select(InfrastructureUsageSnapshot).order_by(
                InfrastructureUsageSnapshot.captured_at.desc()
            )
        )
    ).scalars().all()
    latest: dict[str, InfrastructureUsageSnapshot] = {}
    for snapshot in latest_rows:
        latest.setdefault(snapshot.provider, snapshot)

    def snap_card(provider: str, name: str, configured_cost: float = 0.0) -> dict:
        snap = latest.get(provider)
        if snap is None:
            return _provider_card(
                provider,
                name,
                status="pending",
                source="awaiting first hourly sync",
                cost_inr=configured_cost,
                error="No snapshot yet",
            )
        captured = snap.captured_at
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - captured.astimezone(timezone.utc)
        status = "stale" if age > timedelta(hours=3) and snap.status == "live" else snap.status
        return _provider_card(
            provider,
            name,
            status=status,
            source=snap.source,
            used=float(snap.used) if snap.used is not None else None,
            limit=float(snap.limit) if snap.limit is not None else None,
            unit=snap.unit,
            cost_inr=float(snap.cost_inr) if snap.cost_inr is not None else configured_cost,
            updated_at=captured.isoformat(),
            details=snap.details,
            error=snap.error,
        )

    total_measured_ai = sum(item["measured_ai_cost_inr"] for item in clinics)
    total_gap = sum(item["estimated_gap_cost_inr"] for item in clinics)
    total_vobiz = sum(item["vobiz_usage_cost_inr"] for item in clinics)
    total_dids = sum(item["did_cost_inr"] for item in clinics)
    total_duration_seconds = sum(v["duration_seconds"] for v in by_org.values())
    total_telemetry_seconds = sum(v["telemetry_seconds"] for v in by_org.values())
    telemetry_coverage = (
        min(100.0, total_telemetry_seconds / total_duration_seconds * 100)
        if total_duration_seconds
        else 0.0
    )
    variable_cost = total_measured_ai + total_gap + total_vobiz + livekit_cost
    estimated_total = variable_cost + total_dids + fixed_shared

    try:
        database_bytes = int(
            (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar_one()
            or 0
        )
        supabase_status = "live"
        supabase_error = None
    except Exception as exc:  # fail-open on restricted/local database roles
        database_bytes = 0
        supabase_status = "warning"
        supabase_error = f"Database size probe unavailable: {type(exc).__name__}"

    total_prompt = sum(v["prompt_tokens"] for v in by_org.values())
    total_cached = sum(v["cached_tokens"] for v in by_org.values())
    total_completion = sum(v["completion_tokens"] for v in by_org.values())
    gemini_cost = measured_ai_cost_inr(
        llm_prompt_tokens=total_prompt,
        llm_cached_tokens=total_cached,
        llm_completion_tokens=total_completion,
    )
    providers = [
        snap_card("soniox", "Soniox speech"),
        _provider_card(
            "gemini",
            "Gemini LLM",
            status="estimated",
            source="LiveKit SDK token metrics",
            used=float(total_prompt + total_completion),
            unit="tokens",
            cost_inr=gemini_cost,
            details={
                "prompt_tokens": total_prompt,
                "cached_prompt_tokens": total_cached,
                "completion_tokens": total_completion,
                "billing_export": "not connected; local token allocation is measured",
            },
        ),
        _provider_card(
            "vobiz",
            "Vobiz telephony",
            status="live" if settings.vobiz_auth_id else "not_connected",
            source="authoritative CDR sync + configured tariff",
            used=float(platform_billed),
            unit="billed call min",
            cost_inr=total_vobiz + total_dids,
            details={"dids": sum(1 for b in branches if b.did_number), "did_cost_inr": total_dids},
        ),
        _provider_card(
            "livekit",
            "LiveKit SIP",
            status="live" if settings.livekit_url else "not_connected",
            source="CDR calls, per-call minute rounding",
            used=float(platform_billed),
            limit=float(livekit_included_minutes()),
            unit="SIP min",
            cost_inr=livekit_cost,
            details={
                "plan": settings.livekit_plan,
                "overage_rate_usd_per_min": 0.004,
                "projected_used": _project_month(platform_billed, now, month_start),
            },
        ),
        snap_card("fly", "Fly voice compute", settings.cost_fly_month_inr),
        snap_card("render", "Render API", settings.cost_render_month_inr),
        _provider_card(
            "supabase",
            "Supabase database",
            status=supabase_status,
            source="live pg_database_size",
            used=float(database_bytes),
            limit=float(500 * 1024 * 1024),
            unit="bytes",
            cost_inr=settings.cost_supabase_month_inr,
            error=supabase_error,
            details={"plan_limit": "500 MB free database"},
        ),
        snap_card("upstash", "Upstash Redis", settings.cost_upstash_month_inr),
        snap_card("cloudflare", "Cloudflare edge", settings.cost_cloudflare_month_inr),
    ]

    soniox_snapshot = latest.get("soniox")
    soniox_actual = (
        float(soniox_snapshot.cost_inr)
        if soniox_snapshot and soniox_snapshot.status == "live" and soniox_snapshot.cost_inr is not None
        else None
    )
    reconciled_total = None
    if soniox_actual is not None:
        # Soniox is the only speech invoice API currently connected. Gemini is
        # still token-priced locally until Cloud Billing export is configured.
        reconciled_total = round(
            soniox_actual + gemini_cost + total_vobiz + livekit_cost + total_dids + fixed_shared,
            2,
        )

    return {
        "as_of": now.isoformat(),
        "rate_version": RATE_VERSION,
        "currency": "INR",
        "platform": {
            "calls": sum(v["calls"] for v in by_org.values()),
            "cdr_minutes": round(total_duration_seconds / 60, 2),
            "billed_minutes": platform_billed,
            "telemetry_coverage_pct": round(telemetry_coverage, 1),
            "measured_ai_cost_inr": round(total_measured_ai, 2),
            "estimated_gap_cost_inr": round(total_gap, 2),
            "telephony_cost_inr": round(total_vobiz, 2),
            "livekit_cost_inr": round(livekit_cost, 2),
            "did_cost_inr": round(total_dids, 2),
            "fixed_shared_cost_inr": round(fixed_shared, 2),
            "estimated_total_month_inr": round(estimated_total, 2),
            "reconciled_total_month_inr": reconciled_total,
            "projected_month_end_inr": round(
                _project_month(variable_cost, now, month_start) + total_dids + fixed_shared,
                2,
            ),
            "active_clinics": len(active_orgs),
        },
        "clinics": clinics,
        "providers": providers,
        "rates": [
            {"component": "Soniox STT", "rate": "$0.12 / input audio hour"},
            {"component": "Soniox TTS", "rate": "$0.70 / output audio hour"},
            {"component": "Gemini input", "rate": "$0.30 / 1M tokens"},
            {"component": "Gemini cached input", "rate": "$0.03 / 1M tokens"},
            {"component": "Gemini output", "rate": "$2.50 / 1M tokens"},
            {"component": "LiveKit SIP overage", "rate": "$0.004 / billed minute"},
            {"component": "Vobiz usage", "rate": f"₹{settings.cost_vobiz_per_billed_min_inr:.2f} / billed minute"},
            {"component": "Vobiz DID", "rate": f"₹{settings.cost_vobiz_did_month_inr:.0f} / DID / month"},
            {"component": "FX used", "rate": f"₹{settings.cost_usd_inr:.2f} / USD"},
        ],
        "method": {
            "measured": "SDK audio seconds/token counts and Vobiz CDR durations",
            "estimated": "pre-ledger calls use ₹2.25 per real call minute for the unmeasured AI gap",
            "allocated": "shared fixed cost is split equally across active/trial clinics",
            "reconciled": "vendor project totals override estimates only when an official usage API is connected",
        },
    }
