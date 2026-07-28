"""Security headers middleware.

Adds the following HTTP response headers to every outgoing response, regardless
of route or status code. These headers harden the browser/client-side posture
against the most common web attack classes.

Per security spec §10.5 (2026-05-22-security-hardening-design.md).

Header explanations (one line each):
  - Strict-Transport-Security: Force HTTPS for 1 year; browsers refuse HTTP.
  - X-Content-Type-Options: Browser must not sniff content-type (MIME confusion).
  - X-Frame-Options: Block embedding in iframes (clickjacking defense).
  - Referrer-Policy: Do not leak our URLs to third-party sites via Referer.
  - Permissions-Policy: Explicitly deny geolocation, microphone, camera access.
  - Content-Security-Policy: Deny browser resources on this API-only origin.
  - Cross-Origin-* policies: Isolate API documents and resources.
  - Cache-Control: Do not retain patient-facing API responses.
"""

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

# The frontend is hosted separately; API/legal responses execute no scripts.
_CSP_DIRECTIVE = (
    "default-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that injects security headers into every response.

    Positioned BEFORE CORSMiddleware in main.py so that security headers appear
    on ALL responses, including CORS preflight (OPTIONS) responses. CORS
    middleware adds its own headers after this one runs.

    No configuration needed — all headers are static strings per spec §10.5.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # Force HTTPS for 1 year; includeSubDomains covers api.vachanam.in
        # and any future subdomains.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Prevent browsers from guessing content types (MIME sniffing attacks).
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Block our pages from being loaded inside an <iframe> (clickjacking).
        response.headers["X-Frame-Options"] = "DENY"

        # Only send origin in Referer header to same-origin; nothing to
        # cross-origin requests (prevents URL leakage to third-party analytics).
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Deny API access to device features even if a script tried to request
        # them — belt-and-suspenders with the absence of those features in our app.
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        # Full CSP directive from spec §10.5.
        response.headers["Content-Security-Policy"] = _CSP_DIRECTIVE

        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Preserve deliberate route-specific caching (for example public legal
        # documents); patient-facing API responses default to never cached.
        response.headers.setdefault("Cache-Control", "no-store")

        return response
