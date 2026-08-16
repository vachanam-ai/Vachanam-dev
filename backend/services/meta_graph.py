"""One source of truth for Meta Graph API URLs."""
from __future__ import annotations

import re

from backend.config import settings


def version() -> str:
    value = (settings.meta_graph_version or "").strip()
    return value if re.fullmatch(r"v\d+\.\d+", value) else "v25.0"


def url(path: str) -> str:
    return f"https://graph.facebook.com/{version()}/{path.lstrip('/')}"
