"""
DIAGNOSTIC — Verify fetched data freshness for a specific symbol.

Prints the EXACT date of the latest row returned by MarketDataProvider,
compared to today's actual date, so a genuine staleness bug (vs a
fixed one) can be confirmed directly against real production data —
not just date-math logic in an offline sandbox.

Usage:
    python scripts/diagnose_data_freshness.py --symbol DIVISLAB.NS
"""

from __future__ import annotations

import argparse
from datetime import datetime

from data.market_data import MarketDataProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    today = datetime.now()
    print(f"Script run time (server clock): {today.isoformat()}")
    print(f"Fetching {args.symbol} via MarketDataProvider.fetch() ...")

    provider = MarketDataProvider()
    df = provider.fetch(symbol=args.symbol, interval="1d", period="1y")

    if df.empty:
        print("EMPTY dataframe returned — cannot check freshness.")
        return

    last_row = df.iloc[-1]
    last_date = last_row.get("timestamp", "unknown")
    print(f"\nTotal rows fetched: {len(df)}")
    print(f"LATEST row timestamp: {last_date}")
    print(f"LATEST row close price: {last_row.get('close')}")
    print(f"LATEST row full data: {dict(last_row)}")

    print(f"\nToday's date: {today.date()}")
    if hasattr(last_date, "date"):
        gap_days = (today.date() - last_date.date()).days
        print(f"Gap between today and latest fetched row: {gap_days} day(s)")
        if gap_days >= 2:
            print("⚠️  WARNING: latest data is 2+ days old — if today or yesterday "
                  "was a trading day, this indicates a genuine staleness issue.")
        elif gap_days <= 1:
            print("✓ Latest data appears fresh (0-1 day gap, consistent with a normal weekend/holiday gap).")


if __name__ == "__main__":
    main()
