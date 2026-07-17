"""Regenerate docs/PROBLEMS.csv — the master problem sheet (Vinay 2026-07-17:
"note down all problems from start of the build to now in a sheet; every time
we update something make sure no other problem is getting repeated").

Source of truth stays docs/FIXLOG.md (one row per problem, each with its
regression guard). This script flattens it to a spreadsheet; the unit test
tests/unit/test_problems_sheet.py fails the suite whenever FIXLOG changed but
the sheet was not regenerated, so the sheet can never drift.

Run:  python scripts/gen_problems_sheet.py
"""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXLOG = ROOT / "docs" / "FIXLOG.md"
SHEET = ROOT / "docs" / "PROBLEMS.csv"
HEADER = ["id", "date_2026", "problem", "root_cause", "fix", "proof_and_guard"]


def fixlog_rows() -> list[list[str]]:
    rows = []
    for line in FIXLOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not re.match(r"^\d+s?$", cells[0]):
            continue
        rows.append((cells + [""] * 6)[:6])
    rows.sort(key=lambda r: (int(re.match(r"(\d+)", r[0]).group(1)), r[0]))
    return rows


def write_sheet() -> int:
    rows = fixlog_rows()
    with SHEET.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    print(f"PROBLEMS.csv written: {write_sheet()} problems")
