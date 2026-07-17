"""The problem sheet (docs/PROBLEMS.csv) must always reflect docs/FIXLOG.md
(Vinay 2026-07-17). This test regenerates the rows in memory and compares —
adding a FIXLOG row without running scripts/gen_problems_sheet.py fails the
suite, so the sheet can never silently fall behind."""
import csv

from scripts.gen_problems_sheet import HEADER, SHEET, fixlog_rows


def test_problems_sheet_in_sync_with_fixlog():
    assert SHEET.exists(), "run: python scripts/gen_problems_sheet.py"
    with SHEET.open(encoding="utf-8-sig") as f:
        got = list(csv.reader(f))
    want = fixlog_rows()
    assert got[0] == HEADER
    assert len(got) - 1 == len(want), (
        f"PROBLEMS.csv has {len(got) - 1} rows, FIXLOG has {len(want)} — "
        "run: python scripts/gen_problems_sheet.py"
    )
    assert got[1:] == want, "PROBLEMS.csv content drifted — regenerate it"


def test_every_problem_row_names_its_proof():
    # The whole point of the sheet: every fixed problem carries its guard.
    # 50 pre-#338 rows predate the ✅/⚠ marker convention (grandfathered) —
    # every row from #338 on MUST name its proof.
    import re

    missing = [
        r[0] for r in fixlog_rows()
        if int(re.match(r"(\d+)", r[0]).group(1)) >= 338
        and "✅" not in r[5] and "⚠" not in r[5]
    ]
    assert not missing, f"FIXLOG rows without a proof/guard column: {missing}"
