"""Per-clinic WhatsApp template administration (WA MVP1 Task 10).

Templates live PER WABA at Meta, not in our DB — every read/write scopes
through `wa_service.token_for(branch)` and `branch.wa_waba_id` (RULE 1: a
clinic must never see or touch another clinic's templates, and the platform
token must never be used here — it belongs to no single clinic's WABA).

Validation happens BEFORE Meta ever sees the payload — each check below maps
to a real Meta rejection we would otherwise surface as an opaque Graph 400:
  - name: lowercase alphanumeric + underscores only
  - body placeholders: sequential from {{1}}, no gaps ({{1}},{{3}} rejected)
  - every placeholder needs an example value
  - category defaults to UTILITY — Marketing costs more per message and is
    rejected harder by Meta's review.

The required system templates are wired into live booking, reschedule,
cancellation, reminder and follow-up paths. Deleting one would silently break
future patient notifications, so delete_template refuses them (409).
"""
from __future__ import annotations

import asyncio
import re

import httpx
import structlog

from backend.services import wa_service

logger = structlog.get_logger()

_GRAPH = "https://graph.facebook.com/v21.0"

# Wired into wa_templates.py send paths — never deletable from this admin UI.
SYSTEM_TEMPLATE_DEFINITIONS = (
    {
        "name": "vachanam_booking_confirm", "body": (
            "Hello {{1}}, your appointment at {{2}} with Dr {{3}} is confirmed "
            "for {{4}} at {{5}}. Please come on time."
        ),
        "examples": ["Anjali", "Venkateshwara Clinic", "Srinivas", "12 August", "10:30 AM"],
        "buttons": ["Reschedule", "Cancel"],
    },
    {
        "name": "vachanam_booking_reschedule", "body": (
            "Hello {{1}}, your appointment with Dr {{2}} is moved to {{3}} at "
            "{{4}}. Please come on time."
        ),
        "examples": ["Anjali", "Srinivas", "12 August", "11:00 AM"],
        "buttons": ["Reschedule", "Cancel"],
    },
    {
        "name": "vachanam_booking_cancel", "body": (
            "Hello {{1}}, your appointment with Dr {{2}} on {{3}} at {{4}} "
            "has been cancelled."
        ),
        "examples": ["Anjali", "Srinivas", "12 August", "10:30 AM"],
        "buttons": [],
    },
    {
        "name": "vachanam_appt_reminder", "body": (
            "Reminder for {{1}}: your appointment with Dr {{2}} is on {{3}} "
            "at {{4}}. Please come on time."
        ),
        "examples": ["Anjali", "Srinivas", "12 August", "10:30 AM"],
        "buttons": ["Reschedule", "Cancel"],
    },
    {
        "name": "vachanam_clinic_location",
        "body": "{{1}} is at {{2}}. Directions: {{3}}",
        "examples": ["Venkateshwara Clinic", "Hyderabad", "https://maps.google.com/"],
        "buttons": [],
    },
    {
        "name": "vachanam_feedback",
        "body": "Thank you for visiting us. Share your feedback here: {{1}}",
        "examples": ["https://example.com/review"],
        "buttons": [],
    },
    {
        "name": "vachanam_rating_ask",
        "body": "How was your visit to {{1}}? Tap a rating below.",
        "examples": ["Venkateshwara Clinic"],
        "buttons": ["1", "2", "3", "4", "5"],
    },
    {
        "name": "vachanam_leave_rebook",
        "body": "Dr {{1}} is unavailable on {{2}}. Tap below to reschedule.",
        "examples": ["Srinivas", "12 August"],
        "buttons": ["Reschedule"],
    },
)

SYSTEM_TEMPLATES = frozenset({
    "booking_confirm", "appt_reminder", "rating_ask", "leave_rebook",
    *(item["name"] for item in SYSTEM_TEMPLATE_DEFINITIONS),
})

_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")


class TemplateAdminError(Exception):
    """Base for template-admin failures. Carries the HTTP status the route
    should return and a message safe to show the clinic verbatim."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class NotConnected(TemplateAdminError):
    def __init__(self):
        super().__init__(
            422, "Connect this clinic's WhatsApp Business Account first."
        )


class MetaTemplateError(TemplateAdminError):
    def __init__(self, detail: str):
        super().__init__(422, detail)


def _waba_and_token(branch) -> tuple[str, str]:
    waba_id = getattr(branch, "wa_waba_id", None)
    token = wa_service.token_for(branch)
    if not waba_id or not token:
        raise NotConnected()
    return waba_id, token


def validate_name(name: str) -> str:
    """Meta requires lowercase alphanumeric + underscore names. Rejecting
    locally gives an instant, readable error instead of an opaque Graph 400."""
    name = (name or "").strip()
    if not name or not _NAME_RE.match(name):
        raise TemplateAdminError(
            422,
            "Template name must be lowercase letters, numbers and "
            "underscores only (e.g. diwali_offer).",
        )
    return name


def placeholder_numbers(body: str) -> list[int]:
    return sorted({int(n) for n in _PLACEHOLDER_RE.findall(body or "")})


def validate_body(body: str, examples: list[str] | None) -> list[int]:
    """{{1}},{{3}} (a gap) is a guaranteed Meta rejection; a placeholder with
    no example value is too. Returns the sorted, deduplicated placeholder
    numbers so the caller can build the `example.body_text` payload."""
    numbers = placeholder_numbers(body)
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        raise TemplateAdminError(
            422,
            "Placeholders must be sequential starting from {{1}} — e.g. "
            "{{1}}, {{2}}, not {{1}}, {{3}}.",
        )
    examples = examples or []
    if numbers and len(examples) < len(numbers):
        raise TemplateAdminError(
            422,
            "Every placeholder needs an example value so Meta can review "
            "the template.",
        )
    if numbers and any(not (examples[i] or "").strip() for i in range(len(numbers))):
        raise TemplateAdminError(
            422,
            "Every placeholder needs an example value so Meta can review "
            "the template.",
        )
    return numbers


async def _get(url: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()


async def _post(url: str, token: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as c:
        return await c.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)


async def _delete(url: str, token: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as c:
        return await c.delete(url, headers={"Authorization": f"Bearer {token}"})


def _meta_error_message(r: httpx.Response) -> str:
    """Map a Graph error to a readable message — the clinic must never see a
    raw Graph payload."""
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 — non-JSON error body
        return "WhatsApp rejected this template."
    msg = (body.get("error") or {}).get("message")
    return (msg or "WhatsApp rejected this template.")[:300]


async def list_templates(branch) -> list[dict]:
    """This branch's own templates from ITS WABA (RULE 1). A branch with no
    WABA connected yet has nothing to list — callers should treat
    `NotConnected` as "no templates", not an error."""
    waba_id, token = _waba_and_token(branch)
    try:
        data = await _get(
            f"{_GRAPH}/{waba_id}/message_templates"
            "?fields=name,language,status,category,components",
            token,
        )
    except httpx.HTTPStatusError as e:
        logger.warning(
            "wa_template_list_failed", branch_id=str(branch.id),
            status=e.response.status_code,
        )
        raise MetaTemplateError("Could not load templates from WhatsApp right now.") from e
    except httpx.TransportError as e:
        logger.warning(
            "wa_template_list_failed", branch_id=str(branch.id), error=str(e)[:120],
        )
        raise MetaTemplateError("Could not reach WhatsApp right now.") from e
    return data.get("data", [])


async def create_template(
    branch,
    *,
    name: str,
    category: str,
    body: str,
    examples: list[str] | None = None,
    buttons: list[str] | None = None,
    language: str = "en",
) -> dict:
    """Validate locally, THEN call Meta. Order matters: a clinic gets an
    instant, readable rejection for a bad name/placeholders before we ever
    spend a Graph call (or need a connected WABA to explain the mistake)."""
    name = validate_name(name)
    numbers = validate_body(body, examples)
    waba_id, token = _waba_and_token(branch)

    components: list[dict] = [{"type": "BODY", "text": body}]
    if numbers:
        components[0]["example"] = {
            "body_text": [[(examples or [])[i] for i in range(len(numbers))]]
        }
    quick_replies = [b.strip() for b in (buttons or []) if b and b.strip()]
    if quick_replies:
        components.append({
            "type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": b} for b in quick_replies],
        })

    payload = {
        "name": name,
        "category": (category or "UTILITY").upper(),
        "language": language,
        "components": components,
    }
    r = await _post(f"{_GRAPH}/{waba_id}/message_templates", token, payload)
    if r.status_code >= 300:
        logger.warning(
            "wa_template_create_failed", branch_id=str(branch.id),
            status=r.status_code,
        )
        raise MetaTemplateError(_meta_error_message(r))
    logger.info(
        "wa_template_created", branch_id=str(branch.id), category=payload["category"],
    )
    return r.json()


async def ensure_system_templates(branch) -> dict:
    """Submit every missing required template for this clinic's Meta review."""
    existing = {str(t.get("name") or "") for t in await list_templates(branch)}
    missing = [s for s in SYSTEM_TEMPLATE_DEFINITIONS if s["name"] not in existing]

    async def submit(spec: dict) -> tuple[str, str | None]:
        try:
            await create_template(
                branch,
                name=spec["name"],
                category="UTILITY",
                body=spec["body"],
                examples=spec["examples"],
                buttons=spec["buttons"],
                language="en",
            )
            return spec["name"], None
        except TemplateAdminError as exc:
            return spec["name"], exc.detail

    results = await asyncio.gather(*(submit(spec) for spec in missing))
    created = [name for name, error in results if error is None]
    errors = [
        {"name": name, "detail": error}
        for name, error in results if error is not None
    ]
    return {
        "created": created,
        "existing": sorted(existing & SYSTEM_TEMPLATES),
        "errors": errors,
    }


async def delete_template(branch, name: str) -> None:
    if name in SYSTEM_TEMPLATES:
        raise TemplateAdminError(
            409,
            "This template is used for booking confirmations and cannot be deleted.",
        )
    waba_id, token = _waba_and_token(branch)
    r = await _delete(
        f"{_GRAPH}/{waba_id}/message_templates?name={name}", token,
    )
    if r.status_code >= 300 and r.status_code != 404:
        logger.warning(
            "wa_template_delete_failed", branch_id=str(branch.id), status=r.status_code,
        )
        raise MetaTemplateError("Could not delete this template right now.")
    logger.info("wa_template_deleted", branch_id=str(branch.id))
