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
# Brand-matched to the PWA design system ("calm clinic ledger"): teal/cream/ink
# tokens, Fraunces display + Outfit UI (CSP already whitelists Google Fonts),
# light/dark via prefers-color-scheme, styled tables (the processor lists), and
# a header bar linking back to vachanam.in.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — Vachanam</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Outfit:wght@400;500;600&family=Pacifico&display=swap" rel="stylesheet">
  <style>
    :root {{
      --teal: #006b6b; --teal-deep: #004f4f; --teal-light: #008f8f;
      --teal-pale: #e0f2f1; --teal-mint: #f0fafa;
      --ink: #1a2e2e; --ink-soft: #2d4444; --slate: #708090;
      --cream: #fafcfc; --surface: #ffffff; --hairline: #d0e4e4;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --teal: #20b2a6; --teal-deep: #7fd4cd; --teal-light: #35c1b8;
        --teal-pale: #133231; --teal-mint: #0f1f1e;
        --ink: #e8f1ef; --ink-soft: #c6d6d3; --slate: #94a6a3;
        --cream: #0a1312; --surface: #122019; --hairline: #203634;
      }}
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    html {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
    body {{
      font-family: "Outfit", system-ui, sans-serif;
      font-size: 16px; line-height: 1.7;
      color: var(--ink); background: var(--cream);
      margin: 0;
      background-image:
        radial-gradient(1200px 600px at 85% -10%, rgba(0,143,143,.06), transparent 60%),
        radial-gradient(900px 500px at -10% 110%, rgba(0,107,107,.05), transparent 55%);
    }}
    .topbar {{
      position: sticky; top: 0; z-index: 10;
      display: flex; align-items: center; gap: .75rem;
      padding: .8rem 1.25rem;
      background: color-mix(in srgb, var(--cream) 85%, transparent);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--hairline);
    }}
    .brand {{ font-family: "Pacifico", cursive; font-size: 1.3rem; color: var(--teal); text-decoration: none; }}
    .topbar .doc {{ font-size: .8rem; letter-spacing: .14em; text-transform: uppercase; color: var(--slate); }}
    .container {{ max-width: 760px; margin: 0 auto; padding: 2.5rem 1.25rem 3rem; }}
    h1, h2, h3 {{ font-family: "Fraunces", Georgia, serif; letter-spacing: -0.01em; text-wrap: balance; }}
    h1 {{ font-size: 2.1rem; font-weight: 600; margin: 0 0 .5rem; color: var(--ink); }}
    h2 {{ font-size: 1.35rem; font-weight: 600; margin-top: 2.4rem; color: var(--teal-deep);
          border-bottom: 1px solid var(--hairline); padding-bottom: .35rem; }}
    h3 {{ font-size: 1.1rem; font-weight: 600; margin-top: 1.6rem; color: var(--ink-soft); }}
    p  {{ margin: .8rem 0; }}
    ul, ol {{ padding-left: 1.4rem; }}
    li {{ margin: .35rem 0; }}
    a  {{ color: var(--teal); text-decoration: none; text-underline-offset: 3px; }}
    a:hover {{ text-decoration: underline; }}
    strong {{ font-weight: 600; color: var(--ink); }}
    hr {{ border: none; border-top: 1px solid var(--hairline); margin: 2rem 0; }}
    code {{ background: var(--teal-mint); padding: .1em .35em; border-radius: 4px; font-size: .9em; }}
    blockquote {{
      margin: 1rem 0; padding: .6rem 1rem;
      border-left: 3px solid var(--teal-light);
      background: var(--teal-mint); border-radius: 0 10px 10px 0;
      color: var(--ink-soft);
    }}
    .tablewrap, body {{ overflow-x: auto; }}
    table {{
      width: 100%; border-collapse: collapse; margin: 1.2rem 0;
      font-size: .92rem; background: var(--surface);
      border: 1px solid var(--hairline); border-radius: 12px; overflow: hidden;
    }}
    th {{
      text-align: left; font-weight: 600; font-size: .78rem;
      letter-spacing: .08em; text-transform: uppercase;
      color: var(--teal-deep); background: var(--teal-mint);
      padding: .6rem .8rem; border-bottom: 1px solid var(--hairline);
    }}
    td {{ padding: .55rem .8rem; border-bottom: 1px solid var(--hairline); vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .footer {{
      margin-top: 3rem; padding-top: 1.2rem;
      border-top: 1px solid var(--hairline);
      font-size: .85rem; color: var(--slate);
    }}
    .footer a {{ color: var(--teal); }}
  </style>
</head>
<body>
  <div class="topbar">
    <a class="brand" href="https://vachanam.in">Vachanam</a>
    <span class="doc">{title}</span>
  </div>
  <div class="container">
    {body}
    <div class="footer">
      <p>Vachanam &mdash; AI-powered appointment booking for Indian clinics.<br>
      Healing starts with being heard.<br>
      General: <a href="mailto:hello@vachanam.in">hello@vachanam.in</a> ·
      Privacy &amp; data requests: <a href="mailto:privacy@vachanam.in">privacy@vachanam.in</a> ·
      Support: <a href="mailto:support@vachanam.in">support@vachanam.in</a></p>
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
# Razorpay website-compliance requirement (live-mode KYC checks the site has a
# published refund/cancellation policy).
_REFUND_HTML: str | None = _load_doc("refund-policy.md", "Refund & Cancellation Policy")
# Doctor-facing pitch lives under docs/pitch/, not docs/legal/ — reach it via
# the repo root the same way (served publicly so clinics get a shareable URL).
_PITCH_HTML: str | None = _load_doc(
    str(Path("..") / "pitch" / "data-safety-pitch.md"),
    "How Vachanam Keeps Patient Data Safe",
)

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
    "/refunds",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="Refund & Cancellation Policy",
)
async def refund_policy() -> HTMLResponse:
    """Render docs/legal/refund-policy.md as styled HTML.

    Public — Razorpay live-mode KYC verifies the site publishes this. Returns
    503 if the markdown file is missing or empty at startup.
    """
    return _doc_response(_REFUND_HTML, "refund-policy")


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


@router.get(
    "/data-safety",
    response_class=HTMLResponse,
    include_in_schema=True,
    tags=["legal"],
    summary="How Vachanam Keeps Patient Data Safe (clinic pitch)",
)
async def data_safety_pitch() -> HTMLResponse:
    """Render docs/pitch/data-safety-pitch.md — the doctor-facing answer to
    "how do you keep patient data safe?", shareable as a URL.

    Public — no authentication required. Cache-Control: public, max-age=3600.
    """
    return _doc_response(_PITCH_HTML, "data-safety-pitch")
