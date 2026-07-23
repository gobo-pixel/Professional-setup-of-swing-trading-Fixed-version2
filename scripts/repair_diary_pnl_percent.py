"""
REPAIR DIARY PnL PERCENT (one-time utility)

Old closed trade diary records (from before `final_pnl_percent` was
added to close_trade()) have this field stuck at its default 0.0,
even though the underlying data needed to compute it correctly
(entry_price, exit_price, direction) was always present.

This recomputes final_pnl_percent using the SAME direction-aware
formula as portfolio.py's close_position() — does NOT touch final_pnl
(rupees), which was always correct, and does NOT fabricate any value
that isn't derivable from data already in the record.

Usage:
    python scripts/repair_diary_pnl_percent.py --dry-run
    python scripts/repair_diary_pnl_percent.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from storage.trades.trade_diary import TradeDiary  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    diary = TradeDiary()
    fixed = []
    skipped = []

    for trade_id in diary.list_closed_trade_ids():
        record = diary.get_diary(trade_id)
        if record is None:
            continue

        current = record.get("final_pnl_percent", 0.0)
        entry_price = record.get("entry_price")
        exit_price = record.get("exit_price")
        direction = record.get("direction", "BUY")

        if current not in (0.0, None):
            skipped.append((trade_id, "already has a non-zero value"))
            continue
        if not entry_price or exit_price is None:
            skipped.append((trade_id, "missing entry/exit price — cannot recompute"))
            continue
        try:
            if float(exit_price) != float(exit_price):  # NaN check
                skipped.append((trade_id, "exit_price is NaN — cannot recompute"))
                continue
        except (TypeError, ValueError):
            skipped.append((trade_id, "exit_price not numeric"))
            continue

        price_diff = exit_price - entry_price
        if direction == "SELL":
            price_diff = -price_diff
        new_pct = round(price_diff / entry_price * 100, 2)

        fixed.append((trade_id, record.get("symbol", "?"), current, new_pct))
        if not args.dry_run:
            record["final_pnl_percent"] = new_pct
            diary._write(trade_id, record)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Recomputed {len(fixed)} record(s):")
    for trade_id, symbol, old, new in fixed:
        print(f"  {symbol} ({trade_id}): {old}% -> {new}%")

    print(f"\nSkipped {len(skipped)} record(s):")
    for trade_id, reason in skipped:
        print(f"  {trade_id}: {reason}")


if __name__ == "__main__":
    main()
