"""Every route carries a rate limit. The allowlist is one entry long.

Vinay 2026-08-12, security sweep: "backend endpoints ratelimits" and
"manipulating Ratelimits and subscriptions and llm calls".

The limiters were never missing — `backend/middleware/rate_limit.py` has had
per-endpoint buckets, Redis sliding windows, IP fallback keying and an IP
blocklist since Phase 4.5. What was missing was ATTACHING them. Measured on
the day: 78 of 138 routes had no limiter at all, including `/api/plan-change`,
`/api/plan-cancel`, `/api/billing/gstin`, every `/support/*` ticket route and
every `/treatment/*` route.

The fix attaches a floor at `include_router`, so a NEW route is covered the
moment someone adds it. This test is what stops that floor from being removed,
and what stops the allowlist from quietly growing.
"""
from __future__ import annotations

import pytest

# Names that identify a rate-limit dependency. `_make_endpoint_limiter` returns
# a closure called `_rate_limit_dep`; the exported instances all end in _limit.
_LIMIT_MARKERS = ("_limit", "limiter", "check_ip_blocklist")

# FastAPI/OpenAPI plumbing, not our endpoints.
_NOT_OURS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}

# THE ONLY ROUTE ALLOWED TO BE UNLIMITED.
#
# /health is what UptimeRobot, Render and Fly poll. A 429 there is read as a
# dead instance: Render restarts the process, the restart makes the next probe
# more likely to 429, and the service flaps. It touches no database and no
# Redis by design, so an unauthenticated flood costs a dict lookup. Every
# DETAILED probe (/health/redis, /health/ratelimit, /health/voice-plane,
# /health/whatsapp) is both admin-gated and rate-limited — those leak recon,
# this one returns {"status": "ok"}.
_EXEMPT = {"/health"}


def _app():
    from backend.main import app

    return app


def _limited(route) -> bool:
    for dep in getattr(route, "dependencies", []):
        if any(m in getattr(dep.dependency, "__name__", "") for m in _LIMIT_MARKERS):
            return True
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for sub in dependant.dependencies:
            if any(m in getattr(sub.call, "__name__", "") for m in _LIMIT_MARKERS):
                return True
    return False


def _routes():
    for route in _app().routes:
        methods = getattr(route, "methods", None)
        if not methods or not getattr(route, "endpoint", None):
            continue
        if route.path in _NOT_OURS:
            continue
        yield route, methods - {"HEAD", "OPTIONS"}


def test_every_route_is_rate_limited():
    naked = sorted(
        f"{','.join(sorted(methods))} {route.path}"
        for route, methods in _routes()
        if route.path not in _EXEMPT and not _limited(route)
    )
    assert not naked, (
        f"{len(naked)} route(s) ship with no rate limit:\n  "
        + "\n  ".join(naked)
        + "\nAttach a limiter, or justify an addition to _EXEMPT in this file."
    )


def test_the_exemption_list_stays_one_route_long():
    """An allowlist is only safe while it is small enough to read."""
    assert _EXEMPT == {"/health"}, (
        "the unlimited-route allowlist changed — every entry is an "
        "unauthenticated endpoint anyone may call without bound"
    )


def test_exempt_routes_actually_exist():
    """A typo in _EXEMPT would silently widen it to nothing, hiding a real gap."""
    paths = {route.path for route, _ in _routes()}
    missing = _EXEMPT - paths
    assert not missing, f"_EXEMPT names routes that do not exist: {missing}"


def test_money_and_abuse_paths_are_covered():
    """The routes that made this worth doing, named explicitly.

    A future refactor could drop the router-level floor and still pass the
    sweep above if it also shrank the route table. These are pinned by name.
    """
    want = {
        "/api/plan-change",
        "/api/plan-cancel",
        "/api/billing/gstin",
        "/webhooks/whatsapp",
        "/support/tickets",
        "/patients/{patient_id}",
    }
    by_path = {route.path: route for route, _ in _routes()}
    for path in sorted(want):
        assert path in by_path, f"{path} vanished from the route table"
        assert _limited(by_path[path]), f"{path} lost its rate limit"


def test_the_whatsapp_webhook_gets_the_wide_bucket_not_the_floor():
    """Meta bursts deliveries; a 429 makes it retry and can drop a message.

    The webhook must be limited, but at 1000/min, not the 100/min floor.
    """
    import backend.main as main

    src = open(main.__file__, encoding="utf-8").read()
    block = src.split("app.include_router(\n    whatsapp_webhook_router.router", 1)
    assert len(block) == 2, "whatsapp webhook router registration moved"
    assert "Depends(whatsapp_webhook_limit)" in block[1][:200]


def test_the_floor_is_attached_at_router_level_not_per_route():
    """Per-route attachment is what failed for 78 routes — someone forgets.

    Registering the floor on include_router means a new route inherits it.
    """
    import ast

    import backend.main as main

    src = open(main.__file__, encoding="utf-8").read()
    assert "_FLOOR = [Depends(default_limit)]" in src

    unfloored = []
    for node in ast.walk(ast.parse(src)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
        ):
            continue
        router = ast.unparse(node.args[0]) if node.args else "?"
        deps = next(
            (kw.value for kw in node.keywords if kw.arg == "dependencies"), None
        )
        if deps is None:
            unfloored.append(router)
            continue
        # Either the shared floor, or an explicit tighter limiter.
        rendered = ast.unparse(deps)
        if "_FLOOR" not in rendered and "_limit" not in rendered:
            unfloored.append(router)

    assert not unfloored, f"router(s) registered without a rate limit: {unfloored}"


@pytest.mark.parametrize("path", sorted(_EXEMPT))
def test_exempt_route_touches_no_database_or_redis(path):
    """The exemption is only defensible while the route is cheap.

    /health is documented as not touching DB or Redis. If that ever changes,
    an unauthenticated flood becomes a real amplification vector and the
    exemption must be re-argued.
    """
    import inspect

    by_path = {route.path: route for route, _ in _routes()}
    src = inspect.getsource(by_path[path].endpoint)
    for forbidden in ("AsyncSessionLocal", "get_redis", "await db", "execute("):
        assert forbidden not in src, (
            f"{path} is exempt from rate limiting but now touches {forbidden}"
        )
