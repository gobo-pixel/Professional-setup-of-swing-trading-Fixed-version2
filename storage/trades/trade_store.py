"""
TRADE STORE (JOURNALING)

Appends every trade (open or closed) as one row into a single running CSV
(storage/trades/trades_master.csv), so the analytics/learning engines can
read the full trade history back for real profit/loss accuracy tracking —
instead of the old behavior of writing one throwaway JSON file per trade.
"""

import csv
import json
import os
import time
from typing import Any


class TradeStore:

    FIELDNAMES = [
        "id",
        "timestamp",
        "symbol",
        "direction",
        "action",
        "quantity",
        "entry_price",
        "exit_price",
        "status",
        "realized_pnl",
        "realized_pnl_percent",
        "max_profit_percent",
        "max_drawdown_percent",
        "regime",
        "confidence",
        "reasons",
    ]

    def __init__(self, path: str = "storage/trades"):
        self.path = path
        os.makedirs(self.path, exist_ok=True)
        self.master_csv = os.path.join(self.path, "trades_master.csv")

    def save_trade(self, trade: dict[str, Any]) -> None:
        """Append a single trade record as one row in the master CSV.

        `trade` should be a flat dict; missing fields default to "".
        Also keeps the original per-trade JSON for full diagnostics.
        """
        trade = dict(trade)
        trade.setdefault("id", f"trade_{int(time.time() * 1000)}")
        trade.setdefault("timestamp", time.time())

        file_exists = os.path.isfile(self.master_csv)
        with open(self.master_csv, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow({k: trade.get(k, "") for k in self.FIELDNAMES})

        # Keep the detailed JSON too (useful for full diagnostics/debugging).
        detail_path = os.path.join(self.path, f"{trade['id']}.json")
        with open(detail_path, "w") as f:
            json.dump(trade, f, indent=2, default=str)

    def get_all_trades(self) -> list[dict[str, Any]]:
        """Read the full trade journal back (used by analytics/learning)."""
        if not os.path.isfile(self.master_csv):
            return []
        with open(self.master_csv, newline="") as f:
            return list(csv.DictReader(f))

    def get_closed_trades(self) -> list[dict[str, Any]]:
        return [t for t in self.get_all_trades() if t.get("status") == "CLOSED"]
