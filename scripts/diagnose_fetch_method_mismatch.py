"""
DIAGNOSTIC — Compare start/end date-based fetch vs period-based fetch.

The production market_data.py fix uses start=X/end=Y (400 calendar
days back) instead of period="1y". This has NEVER been verified
against the REAL yfinance API (only tested with mocked data) — this
script checks, for a few well-established real stocks, whether the
date-based approach genuinely returns as many rows as a straightforward
period-based call, since that's the one remaining unverified link in
the "Insufficient historical candles" investigation.

Usage:
    python scripts/diagnose_fetch_method_mismatch.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

SYMBOLS = ["ICICIBANK.NS", "ASIANPAINT.NS", "BAJFINANCE.NS", "RELIANCE.NS"]


def main() -> None:
    for symbol in SYMBOLS:
        print(f"\n=== {symbol} ===")

        # Approach A: exactly what market_data.py's fix does.
        end = datetime.now()
        start = end - pd.Timedelta(days=400)
        try:
            df_dates = yf.download(
                tickers=symbol,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            print(f"  start/end (400 calendar days): {len(df_dates)} rows")
        except Exception as exc:
            print(f"  start/end approach FAILED: {exc}")

        # Approach B: simple period string, for direct comparison.
        try:
            df_period = yf.download(
                tickers=symbol,
                period="1y",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            print(f"  period='1y': {len(df_period)} rows")
        except Exception as exc:
            print(f"  period='1y' approach FAILED: {exc}")

        # Approach C: what our own diagnose_insufficient_history.py uses.
        try:
            df_max = yf.download(symbol, period="max", progress=False, auto_adjust=False)
            print(f"  period='max' (real full history): {len(df_max)} rows")
        except Exception as exc:
            print(f"  period='max' approach FAILED: {exc}")


if __name__ == "__main__":
    main()
