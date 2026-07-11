"""In-memory support knowledge base. KB = markdown files in docs/support/*.md
with a small front-matter block:

    ---
    title: Pricing & plans
    audience: public   # public | clinic | both
    category: billing
    tags: price, plan, cost
    ---
    <markdown body>

ponytail: loaded once at import into a module list; the corpus is tiny. Move to
a table + cache-bust only if it needs runtime edits or outgrows memory.
"""
from __future__ import annotations

import pathlib

_DIR = pathlib.Path(__file__).resolve().parents[2] / "docs" / "support"


def _parse(text: str) -> dict:
    # text starts with "---\n<front>\n---\n<body>"
    after_first = text.partition("---\n")[2]
    front, _, body = after_first.partition("\n---\n")
    meta: dict[str, str] = {}
    for line in front.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return {
        "title": meta.get("title", ""),
        "audience": meta.get("audience", "both"),
        "category": meta.get("category", "other"),
        "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        "body": body.strip(),
    }


def load_kb() -> list[dict]:
    if not _DIR.exists():
        return []
    return [_parse(p.read_text(encoding="utf-8")) for p in sorted(_DIR.glob("*.md"))]


_CACHE = load_kb()


def kb_text(audience: str) -> str:
    """Concatenated markdown for one audience. `both` entries always included."""
    parts = [
        f"## {e['title']}\n{e['body']}"
        for e in _CACHE
        if e["audience"] in (audience, "both")
    ]
    return "\n\n".join(parts)


if __name__ == "__main__":  # ponytail self-check
    assert kb_text("public"), "public KB empty"
    assert "phone number" in kb_text("clinic").lower()
    print("support_kb ok:", len(_CACHE), "entries")
