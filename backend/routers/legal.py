"""Legal document router — Phase 4.5 Task 12.

Serves privacy policy, terms of service, and DPA as styled HTML pages.
Markdown files are read from docs/legal/ at module load and cached in memory.
These are public routes (no auth, no rate limit) — legal disclosures must be
accessible without credentials.

Per CLAUDE.md Rule 7: structlog on load errors.
Per CLAUDE.md Rule 10: no hardcoded paths — resolved relative to repo root.
"""
from pathlib import Path

import structlog
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = structlog.get_logger()

router = APIRouter()

# ── Locate docs/legal/ relative to this file (backend/routers/legal.py)
# backend/ is two levels down from repo root, so we go up twice.
_REPO_ROOT = Path(__file__).parent.parent.parent
_LEGAL_DIR = _REPO_ROOT / "docs" / "legal"

# ── HTML wrapper template ────────────────────────────────────────────────────
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Vachanam</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   Helvetica, Arial, sans-serif;
      font-size: 16px;
      line-height: 1.6;
      color: #1a1a1a;
      background: #ffffff;
      margin: 0;
      padding: 2rem 1rem;
    }}
    .container {{
      max-width: 720px;
      margin: 0 auto;
    }}
    h1 {{ font-size: 2rem; margin-top: 0; color: #111; }}
    h2 {{ font-size: 1.4rem; margin-top: 2rem; color: #222; border-bottom: 1px solid #e5e5e5; padding-bottom: 0.25rem; }}
    h3 {{ font-size: 1.15rem; margin-top: 1.5rem; color: #333; }}
    p  {{ margin: 0.75rem 0; }}
    ul, ol {{ padding-left: 1.5rem; }}
    li {{ margin: 0.4rem 0; }}
    a  {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    strong {{ font-weight: 600; }}
    hr {{ border: none; border-top: 1px solid #e5e5e5; margin: 2rem 0; }}
    code {{ background: #f4f4f4; padding: 0.1em 0.35em; border-radius: 3px; font-size: 0.9em; }}
    blockquote {{
      margin: 1rem 0;
      padding: 0.5rem 1rem;
      border-left: 4px solid #d1d5db;
      color: #555;
    }}
    .footer {{
      margin-top: 3rem;
      padding-top: 1rem;
      border-top: 1px solid #e5e5e5;
      font-size: 0.85rem;
      color: #666;
    }}
  </style>
</head>
<body>
  <div class="container">
    {body}
    <div class="footer">
      <p>Vachanam &mdash; AI-powered appointment booking for Indian clinics.<br>
      Contact: <a href="mailto:hello@vachanam.in">hello@vachanam.in</a></p>
    </div>
  </div>
</body>
</html>
"""

# ── Load markdown files at module load, cache as rendered HTML ───────────────

def _load_doc(filename: str, title: str) -> str | None:
    """Read and render a markdown file into a full HTML string.

    Returns None if the file is missing or empty so routes can return 503.
    Errors are logged but do NOT raise — callers decide how to respond.
    """
    path = _LEGAL_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.error("legal_doc_missing", filename=filename, path=str(path))
        return None
    except OSError as exc:
        logger.error("legal_doc_read_error", filename=filename, error=str(exc))
        return None

    if not text:
        logger.error("legal_doc_empty", filename=filename, path=str(path))
        return None

    # Import here to isolate the dependency; module-level import would fail
    # loudly if the package is absent before requirements are installed.
    try:
        import markdown as md_lib
    except ImportError:
        logger.error("markdown_library_missing")
        return None

    rendered_body = md_lib.markdown(
        text,
        extensions=["extra", "toc"],
    )
    return _HTML_TEMPLATE.format(title=title, body=rendered_body)


# Cache at module load — these are static documents; reload requires restart.
_PRIVACY_HTML: str | None = _load_doc("privacy-policy.md", "Privacy Policy")
_TERMS_HTML: str | None = _load_doc("terms-of-service.md", "Terms of Service")
_DPA_HTML: str | None = _load_doc("data-processing-agreement.md", "Data Processing Agreement")
_DATA_HANDLING_HTML: str | None = _load_doc("data-handling.md", "How Vachanam Handles Your Data")

_CACHE_HEADERS = {"Cache-Control": "public, max-age=3600"}
_CONTENT_TYPE = "text/html; charset=utf-8"


def _doc_response(html: str | None, doc_name: str) -> HTMLResponse:
    """Return HTMLResponse for a cached doc, or 503 if unavailable."""
    if html is None:
        logger.warning("legal_doc_unavailable_on_request", doc=doc_name)
        return HTMLResponse(
            content="<h1>Service Unavailable</h1><p>Document temporarily unavailable.</p>",
            status_code=503,
            media_type=_CONTENT_TYPE,
            headers=_CACHE_HEADERS,
        )
    return HTMLResponse(
        content=html,
        status_code=200,
        media_type=_CONTENT_TYPE,
        headers=_CACHE_HEADERS,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get(
    "/privacy",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="Privacy Policy",
)
async def privacy_policy() -> HTMLResponse:
    """Render docs/legal/privacy-policy.md as styled HTML.

    Public — no authentication required. Cache-Control: public, max-age=3600.
    Returns 503 if the markdown file is missing or empty at startup.
    """
    return _doc_response(_PRIVACY_HTML, "privacy-policy")


@router.get(
    "/terms",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="Terms of Service",
)
async def terms_of_service() -> HTMLResponse:
    """Render docs/legal/terms-of-service.md as styled HTML.

    Public — no authentication required. Cache-Control: public, max-age=3600.
    Returns 503 if the markdown file is missing or empty at startup.
    """
    return _doc_response(_TERMS_HTML, "terms-of-service")


@router.get(
    "/dpa",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="Data Processing Agreement",
)
async def data_processing_agreement() -> HTMLResponse:
    """Render docs/legal/data-processing-agreement.md as styled HTML.

    Public — no authentication required. Cache-Control: public, max-age=3600.
    Returns 503 if the markdown file is missing or empty at startup.
    """
    return _doc_response(_DPA_HTML, "data-processing-agreement")


@router.get(
    "/data-handling",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="How Vachanam Handles Your Data",
)
async def data_handling() -> HTMLResponse:
    """Render docs/legal/data-handling.md as styled HTML (DPDP transparency doc).

    Public — no authentication required. Cache-Control: public, max-age=3600.
    Returns 503 if the markdown file is missing or empty at startup.
    """
    return _doc_response(_DATA_HANDLING_HTML, "data-handling")
