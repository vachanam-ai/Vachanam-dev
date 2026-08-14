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
    # KNOWLEDGE.md is the chatbot's grounding document (knowledge_text below),
    # not a Help-page article — keep it out of the article list.
    return [_parse(p.read_text(encoding="utf-8"))
            for p in sorted(_DIR.glob("*.md")) if p.name != "KNOWLEDGE.md"]


_CACHE = load_kb()


def kb_text(audience: str) -> str:
    """Concatenated markdown for one audience.

    - clinic (logged-in) sees EVERYTHING — a clinic can ask about pricing
      (public) as well as clinic-only how-tos. (Bug 2026-07-12: clinic users
      were getting only clinic+both, so the bot refused pricing questions.)
    - public (logged-out) sees public + both only — clinic-internal how-tos are
      hidden from anonymous visitors.
    """
    if audience == "clinic":
        keep = lambda a: True  # noqa: E731 — clinic sees all articles
    else:
        keep = lambda a: a in ("public", "both")  # noqa: E731
    parts = [f"## {e['title']}\n{e['body']}" for e in _CACHE if keep(e["audience"])]
    return "\n\n".join(parts)


# ── Chatbot grounding document (2026-07-12, Vinay: one end-to-end knowledge
# doc, free-style answers, strict refusal outside it). Loaded ONCE at import;
# it sits as the STABLE PREFIX of every bot prompt, so the model provider's
# implicit prompt caching discounts the repeated tokens automatically — no
# explicit cache API/TTL to manage at this size (~15 KB).
_KNOWLEDGE = ""
try:
    _KNOWLEDGE = (_DIR / "KNOWLEDGE.md").read_text(encoding="utf-8").strip()
except OSError:
    pass  # missing doc → bot falls back to refusing everything (safe)


def knowledge_text() -> str:
    """The full product-knowledge document for the chatbot's system prompt."""
    return _KNOWLEDGE


if __name__ == "__main__":  # ponytail self-check
    assert kb_text("public"), "public KB empty"
    assert "phone number" in kb_text("clinic").lower()
    print("support_kb ok:", len(_CACHE), "entries")
