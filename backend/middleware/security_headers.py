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
  - Content-Security-Policy: Whitelist script/frame/connect/img/style/font origins;
      block inline scripts; Razorpay + Google OAuth explicitly allowed.
      Any XSS attempt fails because a malicious script cannot load from 'evil.com'.
"""

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

# Content Security Policy — each directive on its own line for readability.
# Keep this list in sync with the security spec §10.5 whenever new external
# domains are added (e.g. Sarvam, LiveKit, etc.).
_CSP_DIRECTIVE = (
    "default-src 'self'; "
    "script-src 'self' https://checkout.razorpay.com https://accounts.google.com; "
    "frame-src https://api.razorpay.com https://accounts.google.com; "
    "connect-src 'self' https://api.razorpay.com; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    # frame-ancestors blocks framing at the CSP level (modern equivalent of
    # X-Frame-Options, which some browsers now ignore). upgrade-insecure-requests
    # rewrites any stray http:// sub-resource to https. Both are pure additions —
    # no legitimate request is blocked (G15 partial; the stricter img-src/style-src
    # tightening is deferred pending a frontend render check — see docs/GO_LIVE.md).
    "frame-ancestors 'none'; "
    "upgrade-insecure-requests; "
    "form-action 'self'"
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

        return response
