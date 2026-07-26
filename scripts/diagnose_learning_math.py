"""
DIAGNOSTIC — Why doesn't Wins + Losses = Total Trades?

Dumps the EXACT realized_pnl value (and its parsed float, if
parseable) for every closed BUY trade in storage/trades/trades_master.csv,
so we can see precisely what's causing the classification gap instead
of guessing.

Usage:
    python scripts/diagnose_learning_math.py
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TRADE_STORE_PATH = "storage/trades/trades_master.csv"


def main() -> None:
    path = Path(TRADE_STORE_PATH)
    if not path.exists():
        print(f"{path} not found.")
        return

    with open(path, newline="") as f:
        all_rows = list(csv.DictReader(f))

    buy_closed = [r for r in all_rows if r.get("direction") == "BUY" and r.get("status") == "CLOSED"]
    print(f"Total BUY closed rows: {len(buy_closed)}\n")

    wins = losses = nan_count = unparseable = 0
    for r in buy_closed:
        raw = r.get("realized_pnl")
        try:
            val = float(raw) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            unparseable += 1
            print(f"  UNPARSEABLE: symbol={r.get('symbol')} raw_realized_pnl={raw!r}")
            continue

        if math.isnan(val):
            nan_count += 1
            print(f"  NaN: symbol={r.get('symbol')} raw_realized_pnl={raw!r}")
        elif val > 0:
            wins += 1
        else:
            losses += 1

    print(f"\nwins={wins}, losses={losses}, nan={nan_count}, unparseable={unparseable}")
    print(f"Sum: {wins + losses + nan_count + unparseable} (should equal {len(buy_closed)})")


if __name__ == "__main__":
    main()
