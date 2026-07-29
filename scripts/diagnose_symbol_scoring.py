"""
DIAGNOSTIC — Full scoring detail for specific symbols.

Read-only investigation tool: extracts and displays EVERY available
column from reports/full_report.csv for a given list of symbols (on
whichever day(s) they appear), so a specific "why was this picked"
question can be investigated using the exact data the strategy saw at
scan-time — without touching any strategy code.

Usage:
    python scripts/diagnose_symbol_scoring.py --symbols DATAPATTNS.NS,NUVAMA.NS,CROMPTON.NS
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FULL_REPORT_PATH = "reports/full_report.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols", required=True,
        help="Comma-separated list of symbols to investigate, e.g. DATAPATTNS.NS,NUVAMA.NS",
    )
    args = parser.parse_args()
    target_symbols = {s.strip() for s in args.symbols.split(",") if s.strip()}

    path = Path(FULL_REPORT_PATH)
    if not path.exists():
        print(f"{path} not found.")
        return

    with open(path, newline="") as f:
        all_rows = list(csv.DictReader(f))

    matched = [r for r in all_rows if r.get("Stock") in target_symbols]
    if not matched:
        print(f"No rows found for {target_symbols} in {path}.")
        print("(full_report.csv is append-only across many days — if these symbols "
              "were scanned on an older day, they should still be present unless "
              "the file was reset/archived since then.)")
        return

    print(f"Found {len(matched)} row(s) across {len({r.get('Date') for r in matched})} distinct day(s).\n")

    for row in matched:
        print("=" * 70)
        print(f"{row.get('Stock')} — Date: {row.get('Date')} — Signal: {row.get('Signal')}")
        print("=" * 70)
        for key, value in row.items():
            if key in ("Stock", "Date", "Signal"):
                continue
            if not value:
                continue
            # Pretty-print the JSON-encoded per-rule checklist columns
            # instead of dumping raw JSON text.
            if key in ("BuyTechnicalChecks", "SellTechnicalChecks") and value not in ("{}", ""):
                try:
                    checks = json.loads(value)
                    passed = [k for k, v in checks.items() if v]
                    failed = [k for k, v in checks.items() if not v]
                    print(f"{key}:")
                    print(f"  Passed ({len(passed)}): {', '.join(passed) if passed else '(none)'}")
                    print(f"  Failed ({len(failed)}): {', '.join(failed) if failed else '(none)'}")
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            print(f"{key}: {value}")
        print()


if __name__ == "__main__":
    main()
