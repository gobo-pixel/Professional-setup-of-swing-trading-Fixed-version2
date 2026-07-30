"""
DIAGNOSTIC - Scan for "News masking weak Fundamentals" pattern.

Read-only investigation: scans the ENTIRE reports/full_report.csv
(every symbol, every day) for BUY or SELL signals where the News score
was high (>= NEWS_HIGH_THRESHOLD) while the Fundamental score was weak
(< FUNDAMENTAL_WEAK_THRESHOLD) - the same pattern found in
DATAPATTNS.NS / NUVAMA.NS / CROMPTON.NS, to see how widespread it is.

Does NOT touch any strategy code - purely reads and reports.

Usage:
    python scripts/diagnose_news_fundamental_pattern.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FULL_REPORT_PATH = "reports/full_report.csv"
NEWS_HIGH_THRESHOLD = 80.0
FUNDAMENTAL_WEAK_THRESHOLD = 50.0


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    path = Path(FULL_REPORT_PATH)
    if not path.exists():
        print(f"{path} not found.")
        return

    with open(path, newline="") as f:
        all_rows = list(csv.DictReader(f))

    matches = []
    for r in all_rows:
        signal = r.get("Signal")
        if signal not in ("BUY", "SELL"):
            continue
        news = _to_float(r.get("NewsScore"))
        fundamental = _to_float(r.get("FundamentalScore"))
        if news is None or fundamental is None:
            continue
        if news >= NEWS_HIGH_THRESHOLD and fundamental < FUNDAMENTAL_WEAK_THRESHOLD:
            matches.append({
                "date": r.get("Date"), "stock": r.get("Stock"), "signal": signal,
                "news": news, "fundamental": fundamental,
                "overall_score": r.get("OverallScore"), "status": r.get("Status"),
                "exit_reason": r.get("ExitReason"), "return_pct": r.get("Return"),
            })

    total_buy_sell = sum(1 for r in all_rows if r.get("Signal") in ("BUY", "SELL"))
    print(
        f"Scanned {len(all_rows)} total rows ({total_buy_sell} BUY/SELL signals) "
        f"across {len({r.get('Date') for r in all_rows if r.get('Date')})} distinct day(s).\n"
    )
    print(
        f"Pattern: News >= {NEWS_HIGH_THRESHOLD} AND Fundamental < {FUNDAMENTAL_WEAK_THRESHOLD}\n"
        f"Found {len(matches)} matching row(s) "
        f"({round(len(matches) / total_buy_sell * 100, 1) if total_buy_sell else 0}% of all BUY/SELL signals).\n"
    )

    by_symbol: dict[str, list[dict]] = {}
    for m in matches:
        by_symbol.setdefault(m["stock"], []).append(m)

    for symbol, entries in sorted(by_symbol.items()):
        latest = entries[-1]
        print(f"{symbol} ({latest['signal']}) - seen on {len(entries)} day(s), latest: {latest['date']}")
        print(f"  News: {latest['news']}, Fundamental: {latest['fundamental']}, Overall: {latest['overall_score']}")
        if latest.get("status") == "CLOSED":
            print(f"  CLOSED - Return: {latest.get('return_pct')}%, Exit: {latest.get('exit_reason')}")
        else:
            print(f"  Status: {latest.get('status')}")
        print()


if __name__ == "__main__":
    main()
