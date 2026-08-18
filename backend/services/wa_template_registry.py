"""Which of a clinic's OWN Meta templates to use for each purpose.

Vinay 2026-08-04: "i have templates verified in meta. can you fetch them and
use them? i have for confirmation, reschedule, cancellation, sending location
of clinic, feedback after appointment completed."

THE PROBLEM THIS SOLVES. `wa_templates.py` hardcodes four names —
booking_confirm, appt_reminder, rating_ask, leave_rebook — and Meta rejects a
send whose template name it does not recognise on that WABA. Under the
clinic-owned-WABA model every clinic registers and names its own templates, so
a hardcoded name is right for at most one clinic and silently wrong for the
next one onboarded. The clinic's WABA is the source of truth, so we ask it.

HOW A NAME IS CHOSEN. Approved templates only (a PENDING or REJECTED template
cannot be sent). Exact match on the canonical name first, so a clinic that
happens to use our names keeps working unchanged. Otherwise the first approved
template whose name contains a keyword for that purpose. Deliberately dumb and
inspectable: no fuzzy scoring, no model call, and a clinic can always force the
choice by naming its template with the canonical name.

WHY THE PARAMETER COUNT MATTERS. Meta rejects a send whose body parameter count
does not match the registered template ({{1}}..{{n}}). Two clinics' "booking
confirmation" templates will not agree on how many variables they take, so the
registry reports the count it found and callers fit their arguments to it —
otherwise every send to clinic #2 fails with an opaque 132000.

RULE 1: the lookup is per branch, using that branch's own WABA and token; one
clinic's template list can never be used to send from another's number.
RULE 9: cached values are template names and counts — never a token, never
patient data.
"""
from __future__ import annotations

import json
import re

import structlog

from backend.services import wa_template_admin

logger = structlog.get_logger()

# Meta's own state machine: only APPROVED templates are sendable.
_APPROVED = "APPROVED"

# Purpose -> (canonical name, keywords, excluded keywords). Keyword order
# inside a purpose is preference order; all matching is on the lowercased name.
#
# The exclusions are the load-bearing part. "booking_cancel_confirmation" and
# "reschedule_confirmed" both contain "confirm", and picking either as the
# booking confirmation would tell a patient who just booked that their
# appointment was cancelled or moved. A name that mentions cancelling or
# rescheduling belongs to THAT purpose, whatever else it also says.
PURPOSES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "booking_confirm": (
        "vachanam_booking_confirm",
        ("booking_confirm", "appointment_confirm", "confirm", "booking"),
        ("cancel", "reschedul", "resched", "remind", "feedback", "rating", "review"),
    ),
    "reschedule": (
        "vachanam_booking_reschedule", ("reschedul", "resched", "moved", "changed"), ("cancel",),
    ),
    "cancel": ("vachanam_booking_cancel", ("cancel",), ()),
    "location": (
        "vachanam_clinic_location", ("location", "address", "direction", "map", "reach"), (),
    ),
    "feedback": (
        "vachanam_feedback", ("feedback", "review", "experience"), ("cancel", "rating"),
    ),
    "reminder": ("vachanam_appt_reminder", ("remind",), ("cancel", "reschedul")),
    "followup": (
        "vachanam_followup", ("followup", "follow_up", "doctor_message"),
        ("cancel", "reschedul", "remind"),
    ),
    "rating": (
        "vachanam_rating_ask", ("rating", "rate", "star"), ("feedback", "review"),
    ),
    "leave_rebook": (
        "vachanam_leave_rebook", ("leave_rebook", "unavailable", "rebook"), ("rating",),
    ),
}

# Template mutations made through Vachanam explicitly invalidate this cache.
# Twelve hours covers a clinic day, so a quiet clinic does not pay Meta's
# multi-second discovery call on its first booking every hour; the TTL remains
# a safety net for edits made directly in Meta's dashboard.
_CACHE_TTL = 12 * 60 * 60
_BODY_VAR = re.compile(r"\{\{(\d+)\}\}")


def _cache_key(branch_id) -> str:
    return f"wa:templates:v1:{branch_id}"


def _body_param_count(components: list[dict]) -> int:
    """How many {{n}} placeholders the BODY carries. Meta counts the highest
    index, not the number of occurrences — {{1}} used twice is still one
    parameter."""
    for comp in components or []:
        if (comp.get("type") or "").upper() == "BODY":
            found = [int(n) for n in _BODY_VAR.findall(comp.get("text") or "")]
            return max(found) if found else 0
    return 0


def _quick_reply_count(components: list[dict]) -> int:
    for comp in components or []:
        if (comp.get("type") or "").upper() == "BUTTONS":
            return sum(
                1
                for button in comp.get("buttons") or []
                if (button.get("type") or "").upper() == "QUICK_REPLY"
            )
    return 0


def _pick(
    templates: list[dict], canonical: str, keywords: tuple[str, ...],
    excludes: tuple[str, ...] = (),
) -> dict | None:
    approved = [
        t for t in templates
        if (t.get("status") or "").upper() == _APPROVED and t.get("name")
    ]
    # An exact canonical match is an explicit choice by the clinic and beats
    # every heuristic below, exclusions included.
    for t in approved:
        if (t.get("name") or "").lower() == canonical:
            return t
    eligible = [
        t for t in approved
        if not any(bad in (t.get("name") or "").lower() for bad in excludes)
    ]
    for keyword in keywords:
        for t in eligible:
            if keyword in (t.get("name") or "").lower():
                return t
    return None


def build_map(templates: list[dict]) -> dict[str, dict]:
    """Purpose -> {name, language, params}. Pure, so it is testable without
    Meta or Redis in the way."""
    out: dict[str, dict] = {}
    for purpose, (canonical, keywords, excludes) in PURPOSES.items():
        chosen = _pick(templates, canonical, keywords, excludes)
        if chosen is None:
            continue
        out[purpose] = {
            "name": chosen["name"],
            "language": chosen.get("language") or "en",
            "params": _body_param_count(chosen.get("components") or []),
            "buttons": _quick_reply_count(chosen.get("components") or []),
        }
    return out


async def _cached(branch_id) -> dict | None:
    try:
        from backend.redis_client import get_redis

        raw = await get_redis().get(_cache_key(branch_id))
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001 — cache is an optimisation, never a gate
        logger.debug("wa_template_cache_read_failed", error=str(e)[:120])
        return None


async def _store(branch_id, value: dict) -> None:
    try:
        from backend.redis_client import get_redis

        await get_redis().set(_cache_key(branch_id), json.dumps(value), ex=_CACHE_TTL)
    except Exception as e:  # noqa: BLE001
        logger.debug("wa_template_cache_write_failed", error=str(e)[:120])


async def invalidate(branch_id) -> None:
    """Called when a clinic creates or deletes a template, so the next send
    sees the change instead of waiting out the hour."""
    try:
        from backend.redis_client import get_redis

        await get_redis().delete(_cache_key(branch_id))
    except Exception as e:  # noqa: BLE001
        logger.debug("wa_template_cache_purge_failed", error=str(e)[:120])


async def template_map(branch, *, refresh: bool = False) -> dict[str, dict]:
    """This branch's purpose -> template mapping, cached.

    Never raises: a clinic with no WABA connected, or a Meta hiccup, yields an
    empty map, and callers treat "no template for this purpose" as "skip the
    notification". RULE 4 — a notification must never be able to fail a
    booking.
    """
    branch_id = getattr(branch, "id", None)
    if not refresh:
        hit = await _cached(branch_id)
        if hit is not None:
            return hit
    try:
        templates = await wa_template_admin.list_templates(branch)
    except Exception as e:  # noqa: BLE001 — NotConnected, Meta down, bad token
        logger.info(
            "wa_template_discovery_skipped", branch_id=str(branch_id),
            error=str(e)[:120],
        )
        return {}

    mapping = build_map(templates)
    await _store(branch_id, mapping)
    logger.info(
        "wa_templates_discovered", branch_id=str(branch_id),
        purposes=sorted(mapping), total=len(templates),
    )
    return mapping


async def resolve(branch, purpose: str) -> dict | None:
    """The approved template for one purpose, or None if the clinic has not
    registered one. None is a normal outcome, not an error."""
    return (await template_map(branch)).get(purpose)


def fit_params(values: list[str], count: int) -> list[str]:
    """Fit our arguments to the clinic's own template.

    Meta rejects a mismatch outright, and clinics write their own templates, so
    the count we want and the count they registered will differ. Extra values
    are dropped from the end (ours are ordered most- to least-important) and a
    shortfall is padded with a dash rather than an empty string, which Meta
    rejects as a blank parameter.
    """
    fitted = list(values[:count])
    while len(fitted) < count:
        fitted.append("-")
    return fitted
