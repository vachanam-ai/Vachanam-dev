"""Cached native-script pronunciations for doctor names and their roles.

Vinay 2026-08-01: "name pronunciation of doctors and their roles is very
important. so per language per clinic. extract them and store them as cache
(they remain same across). so we can directly speak and pronunciation also
remains intact."

WHY THIS EXISTS. Soniox TTS renders text per SCRIPT: Telugu script gets an
Indian voice, Latin script gets an English/American one. Doctor names are
stored in Latin ("Dr. Srinivas"), so a Telugu sentence containing one flips
accent mid-sentence (live 2026-08-01).

WHY NOT RULE-BASED TRANSLITERATION. That was tried (#478, offline
`indic-transliteration`) and REVERTED: mechanical letter mapping mangles real
proper nouns. A language model transliterates names far better, but is far too
slow to run per turn — so it runs ONCE per (clinic, language, roster) and the
result is cached in Redis. Names change about never, so the cache is ~always
warm and the call path pays nothing.

WHERE IT APPLIES. The TTS boundary only (RULE 6). The LLM and every tool keep
working on the original Latin names, so doctor matching, availability strings
and tool arguments are untouched — only the audio changes.

FAILURE MODE. Any error (no Redis, no LLM, bad JSON) returns an EMPTY map and
the caller speaks the original Latin text — exactly today's behaviour. This is
a pronunciation nicety; it must never fail a call.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

logger = logging.getLogger("vachanam-agent")

# Names change about never; a month keeps the cache warm across deploys while
# still letting a correction propagate without a manual purge.
CACHE_TTL_SECONDS = 30 * 24 * 3600
_CACHE_VERSION = "v1"

# Scripts that already speak correctly — if a clinic stored the name in the
# call language's own script there is nothing to convert.
_LATIN = re.compile(r"[A-Za-z]")

# Per-process memo so repeated calls in one worker skip even the Redis hop.
_LOCAL: dict[str, dict[str, str]] = {}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def roster_digest(pairs: list[tuple[str, str]]) -> str:
    """Stable digest of the (name, role) roster — changing a doctor or a role
    yields a new cache entry instead of serving a stale pronunciation."""
    blob = "|".join(f"{_clean(n)}~{_clean(r)}" for n, r in pairs)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def cache_key(branch_id, lang: str, digest: str) -> str:
    return f"pron:{_CACHE_VERSION}:{branch_id}:{(lang or '').lower()}:{digest}"


def needs_conversion(text: str, lang: str) -> bool:
    """Only Latin text spoken in a non-Latin call language needs converting."""
    if (lang or "").lower() in ("", "en"):
        return False
    return bool(_LATIN.search(text or ""))


_PROMPT = (
    "You write pronunciation spellings for a clinic phone assistant.\n"
    "For each entry below, rewrite the doctor's name and their role in {script} "
    "script, spelled so a {script} text-to-speech voice pronounces them the way "
    "an Indian receptionist would SAY them out loud.\n"
    "Rules: transliterate the SOUND, never translate the name. Keep the honorific "
    "(Dr. -> the natural {script} equivalent). Roles ARE translated to the natural "
    "everyday {script} word patients use. No extra words, no explanations.\n"
    'Reply with ONLY a JSON array, one object per entry, same order: '
    '[{{"name": "...", "role": "..."}}]\n\n'
    "Entries:\n{entries}"
)

_SCRIPTS = {
    "te": "Telugu", "hi": "Devanagari (Hindi)", "ta": "Tamil",
    "kn": "Kannada", "mr": "Devanagari (Marathi)", "bn": "Bengali",
    "gu": "Gujarati", "ml": "Malayalam", "pa": "Gurmukhi (Punjabi)",
}


async def _call_gemini(prompt: str) -> str:
    """Same plain-text Gemini path the rest of the codebase uses. Runs at most
    once per (clinic, language, roster) — never on the turn hot path."""
    from google import genai
    from google.genai import types as genai_types

    from backend.config import settings

    client = genai.Client(api_key=settings.gemini_api_key)
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            temperature=0,
            max_output_tokens=1024,
        ),
    )
    return resp.text or ""


def _parse_json(text: str):
    """Tolerate a fenced ```json block around the array."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", body).strip()
    start = min((i for i in (body.find("["), body.find("{")) if i != -1), default=-1)
    if start == -1:
        return None
    try:
        return json.loads(body[start:])
    except json.JSONDecodeError:
        return None


async def _generate(pairs: list[tuple[str, str]], lang: str) -> dict[str, str]:
    """One LLM pass for the whole roster. Returns {latin_text: spoken_text}."""
    script = _SCRIPTS.get((lang or "").lower())
    if not script:
        return {}
    entries = "\n".join(
        f"{i + 1}. name={_clean(n)} | role={_clean(r)}" for i, (n, r) in enumerate(pairs)
    )
    prompt = _PROMPT.format(script=script, entries=entries)
    raw = _parse_json(await _call_gemini(prompt))
    rows = raw if isinstance(raw, list) else (raw or {}).get("entries") or []
    out: dict[str, str] = {}
    for (name, role), row in zip(pairs, rows):
        if not isinstance(row, dict):
            continue
        spoken_name, spoken_role = _clean(row.get("name")), _clean(row.get("role"))
        # Reject a model that echoed the Latin input back — that would be a
        # no-op replacement that still sounds American.
        if spoken_name and not _LATIN.search(spoken_name) and _clean(name):
            out[_clean(name)] = spoken_name
        if spoken_role and not _LATIN.search(spoken_role) and _clean(role):
            out[_clean(role)] = spoken_role
    return out


async def spoken_map(branch_id, lang: str, pairs: list[tuple[str, str]]) -> dict[str, str]:
    """{original_text: native_script_text} for this clinic + language.

    Cheap and safe to call on every call setup: process memo -> Redis -> LLM.
    Returns {} on any failure, which means "speak the original text".
    """
    pairs = [(_clean(n), _clean(r)) for n, r in pairs if _clean(n)]
    if not pairs or not needs_conversion(" ".join(n for n, _ in pairs), lang):
        return {}

    key = cache_key(branch_id, lang, roster_digest(pairs))
    if key in _LOCAL:
        return _LOCAL[key]

    redis = None
    try:
        from backend.redis_client import get_redis

        redis = get_redis()
        cached = await redis.get(key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, dict):
                _LOCAL[key] = data
                return data
    except Exception as e:  # noqa: BLE001 — cache is an optimisation, never fatal
        logger.warning("pronunciation_cache_read_failed: %s", str(e)[:140])

    try:
        mapping = await _generate(pairs, lang)
    except Exception as e:  # noqa: BLE001 — fall back to the Latin spelling
        logger.warning("pronunciation_generate_failed: %s", str(e)[:140])
        return {}

    _LOCAL[key] = mapping
    if redis is not None and mapping:
        try:
            await redis.set(key, json.dumps(mapping, ensure_ascii=False),
                            ex=CACHE_TTL_SECONDS)
            logger.info("pronunciation_cached key=%s entries=%d", key, len(mapping))
        except Exception as e:  # noqa: BLE001
            logger.warning("pronunciation_cache_write_failed: %s", str(e)[:140])
    return mapping


def build_replacer(mapping: dict[str, str]):
    """Compile MAPPING into ``(sub, hold)`` for the TTS stream.

    ``sub(text)`` rewrites every known name/role. Longest-first so
    "Dr. Srinivas Rao" wins over "Srinivas"; Latin keys are word-bounded so a
    name never matches inside a longer word ("Srinivasan").

    ``hold(buf)`` returns how many trailing characters of BUF must be kept back
    because they could still grow into a name on the next chunk. Holding back a
    fixed window is NOT enough — a name starting just before the cut would be
    split and missed — so this holds back exactly the longest suffix that is a
    live prefix of some key, and nothing more.
    """
    keys = [k for k in mapping if k]
    if not keys:
        return None, None
    keys.sort(key=len, reverse=True)
    parts = []
    for k in keys:
        esc = re.escape(k)
        if k[:1].isascii() and k[:1].isalpha():
            esc = r"\b" + esc
        if k[-1:].isascii() and k[-1:].isalpha():
            esc = esc + r"\b"
        parts.append(esc)
    pattern = re.compile("|".join(parts), re.IGNORECASE)
    lookup = {k.lower(): v for k, v in mapping.items()}

    def sub(text: str) -> str:
        return pattern.sub(lambda m: lookup.get(m.group(0).lower(), m.group(0)), text)

    longest = max(len(k) for k in keys)
    prefixes = {k[:i].lower() for k in keys for i in range(1, len(k) + 1)}

    def hold(buf: str) -> int:
        for size in range(min(len(buf), longest), 0, -1):
            if buf[-size:].lower() in prefixes:
                return size
        return 0

    return sub, hold


async def prime(branch_id, lang: str, pairs: list[tuple[str, str]]) -> None:
    """Fire-and-forget warm so the first call of the day never waits on the LLM."""
    try:
        await spoken_map(branch_id, lang, pairs)
    except Exception as e:  # noqa: BLE001
        logger.warning("pronunciation_prime_failed: %s", str(e)[:140])


def prime_background(branch_id, lang: str, pairs: list[tuple[str, str]]) -> None:
    try:
        asyncio.create_task(prime(branch_id, lang, pairs))
    except RuntimeError:  # no running loop (prewarm/tests)
        pass
