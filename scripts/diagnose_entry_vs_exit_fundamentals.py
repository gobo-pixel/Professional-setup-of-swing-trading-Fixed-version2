"""
DIAGNOSTIC — Prove/disprove the "weak-but-compensated fundamentals" hypothesis.

For each given symbol, finds its ENTRY-DAY row in full_report.csv (the
day it was actually bought/sold) and prints the exact component scores
used AT THAT MOMENT: TechnicalScore, FundamentalScore, NewsScore,
OverallScore, and the qualifying Threshold.

This directly answers: was the fundamental component ALREADY weak at
entry (proving it wasn't "new deterioration" by the time of the exit
check hours/a day later), and did OTHER components compensate to let
it qualify anyway? Real numbers, not theory.

Usage:
    python scripts/diagnose_entry_vs_exit_fundamentals.py --symbols ATHERENERG.NS,EMAMILTD.NS,TITAN.NS,AUROPHARMA.NS,NAM-INDIA.NS
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

FULL_REPORT_PATH = "reports/full_report.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    args = parser.parse_args()
    target_symbols = {s.strip() for s in args.symbols.split(",") if s.strip()}

    path = Path(FULL_REPORT_PATH)
    if not path.exists():
        print(f"{path} not found.")
        return

    with open(path, newline="") as f:
        all_rows = list(csv.DictReader(f))

    for symbol in sorted(target_symbols):
        matches = [r for r in all_rows if r.get("Stock") == symbol and r.get("Signal") in ("BUY", "SELL")]
        if not matches:
            print(f"{symbol}: no BUY/SELL entry-day row found in full_report.csv (may have been trimmed).\n")
            continue

        row = matches[-1]  # most recent entry-signal row
        direction = row.get("Signal")
        overall = row.get(f"{direction.title()}OverallScore", row.get("OverallScore"))
        threshold = row.get(f"{direction.title()}Threshold")
        technical = row.get("TechnicalScore")
        fundamental = row.get("FundamentalScore")
        news = row.get("NewsScore")

        print("=" * 60)
        print(f"{symbol} — Entry Date: {row.get('Date')} — Direction: {direction}")
        print("=" * 60)
        print(f"  TechnicalScore   : {technical}")
        print(f"  FundamentalScore : {fundamental}   <- entry-time value, compare to exit-check's fundamental_exit")
        print(f"  NewsScore        : {news}")
        print(f"  OverallScore     : {overall}")
        print(f"  Threshold        : {threshold}")
        try:
            qualified = float(overall) >= float(threshold)
            fund_weak = float(fundamental) < 50
            print(f"  Qualified (Overall >= Threshold)? {qualified}")
            print(f"  Fundamental already weak (<50) AT ENTRY? {fund_weak}")
            if qualified and fund_weak:
                print("  => CONFIRMED: entered with a weak fundamental component, compensated by others.")
        except (TypeError, ValueError):
            print("  (Could not compute — missing/non-numeric values)")
        print()


if __name__ == "__main__":
    main()
