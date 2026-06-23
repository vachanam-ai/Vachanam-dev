"""Humanizer example/correction bank (Level-1 "training").

A curated, DE-IDENTIFIED store of approved spoken lines keyed by situation. It
is the loop's memory: it seeds Gemini few-shot generation (C1) and is the
judge's gold set (C2). Vinay's corrections and (de-identified) good real-call
turns accumulate here over time.

DPDP (RULE 1 / RULE 9): every write passes the de-id gate
(`backend.services.deidentify.assert_deidentified`) and is REJECTED on any
identifying data. Stored locally as JSON; no PII ever enters.

Entry: {situation_key, line, score, source}. source ∈ {seed, vinay_correction,
real_call}.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from backend.services.deidentify import assert_deidentified

VALID_SOURCES = {"seed", "vinay_correction", "real_call"}
_DEFAULT_PATH = Path(__file__).with_name("example_bank.json")


class ExampleBank:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path or os.environ.get("HUMANIZER_BANK_PATH") or _DEFAULT_PATH)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8") or "[]")

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(
        self,
        situation_key: str,
        line: str,
        *,
        score: float | None = None,
        source: str = "seed",
    ) -> bool:
        """Add one example. Runs the de-id gate (raises on PII). Returns False if
        an identical (situation_key, line) is already present (dedup)."""
        if source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")
        line = (line or "").strip()
        if not line:
            raise ValueError("line is empty")
        assert_deidentified(line)  # DPDP hard gate — RULE 1 / RULE 9
        rows = self._load()
        if any(r["situation_key"] == situation_key and r["line"] == line for r in rows):
            return False
        rows.append(
            {"situation_key": situation_key, "line": line, "score": score, "source": source}
        )
        self._save(rows)
        return True

    def examples_for(self, situation_key: str) -> list[dict]:
        return [r for r in self._load() if r["situation_key"] == situation_key]

    def all(self) -> list[dict]:
        return self._load()

    def seed(self, lines: dict[str, str], *, source: str = "seed") -> int:
        """Bulk-add a {situation_key: line} map; returns the count newly added."""
        return sum(self.add(k, v, source=source) for k, v in lines.items())
