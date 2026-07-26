"""
DIAGNOSTIC — Identify and verify "Insufficient historical candles"
rejections.

Reads reports/full_report.csv, finds every symbol rejected with
"Insufficient historical candles." (any signal direction), then
fetches each one's REAL full historical data via yfinance
(period="max") to check how many trading days of history genuinely
exist — confirming whether these are truly newly-listed stocks (short
real history) or something else is going on.

This is diagnostic-only — it doesn't change any strategy code.

Usage:
    python scripts/diagnose_insufficient_history.py
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf  # noqa: E402


def main() -> None:
    report_path = Path("reports/full_report.csv")
    if not report_path.exists():
        print(f"{report_path} not found — run Daily Scan first.")
        return

    affected: list[dict] = []
    all_dates: set[str] = set()
    with open(report_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Date"):
                all_dates.add(row["Date"])

    if not all_dates:
        print("No 'Date' column values found — cannot determine the latest scan day.")
        return

    latest_date = max(all_dates)
    print(
        f"Note: reports/full_report.csv is APPEND-only (accumulates every "
        f"day's scan forever) — filtering to the LATEST date only: {latest_date}\n"
        f"(found {len(all_dates)} distinct scan date(s) in the file total)\n"
    )

    with open(report_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Date") != latest_date:
                continue
            block_text = (row.get("Tier4Block") or "")
            if "Insufficient historical candles" in block_text:
                affected.append(row)

    if not affected:
        print("No 'Insufficient historical candles' rejections found in the latest full_report.csv.")
        return

    print(f"Found {len(affected)} row(s) rejected for 'Insufficient historical candles':\n")

    for row in affected:
        symbol = row.get("Stock") or row.get("Symbol")
        signal = row.get("Signal")
        if not symbol:
            continue
        try:
            df = yf.download(symbol, period="max", progress=False, auto_adjust=False)
            real_history_days = len(df) if not df.empty else 0
        except Exception as exc:
            real_history_days = f"ERROR: {exc}"

        verdict = ""
        if isinstance(real_history_days, int):
            if real_history_days < 250:
                verdict = "-> Genuinely newly-listed (real max history is under 250 trading days)."
            else:
                verdict = "-> Has 250+ real trading days available — worth investigating why it was still rejected."

        print(f"{symbol} (Signal={signal}): real max history = {real_history_days} trading days {verdict}")
        time.sleep(1.0)  # be polite to the API across many symbols


if __name__ == "__main__":
    main()
