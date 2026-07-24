"""
REPAIR EXIT PRICES FROM REAL HISTORICAL DATA (one-time utility)

The original NaN-propagation bug (see CHANGELOG "Known Limitations")
left 10 closed trades with permanently unrecoverable-looking
current_price/realized_pnl in virtual_portfolio_state.json — we
deliberately did NOT fabricate a number for them at the time.

This script recovers the REAL exit price instead of guessing: for each
corrupted trade, it fetches the ACTUAL NSE closing price for that
symbol on its real exit date via yfinance — a matter of public record,
not a fabrication. It then recomputes realized_pnl / realized_pnl_percent
using the exact same direction-aware formula as portfolio.py.

IMPORTANT — analysis isolation:
These trades were force-closed by a since-fixed bug (max_positions
incorrectly blocking monitoring), not a genuine strategy exit signal.
Backfilling their numbers would let Learning Engine silently start
treating them as real trade outcomes and skew its statistics. To
prevent that, every repaired trade is recorded in
storage/trades/learning_exclusions.json, which analytics/learning_engine.py
now filters out before running any analysis. Reporting/display (Daily
Scan's "Return" column, Paper Trading's "Last Exits" summary) is NOT
filtered — those correctly show the real recovered numbers.

Requires internet access (yfinance) — run this in GitHub Actions, not
locally in an offline sandbox.

Usage:
    python scripts/repair_exit_prices.py --dry-run
    python scripts/repair_exit_prices.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf  # noqa: E402

from core.logger import get_logger  # noqa: E402
from storage.trades.trade_diary import TradeDiary  # noqa: E402

logger = get_logger(__name__)

PORTFOLIO_STATE_PATH = "storage/trades/virtual_portfolio_state.json"
TRADE_STORE_PATH = "storage/trades/trades_master.csv"
EXCLUSIONS_PATH = "storage/trades/learning_exclusions.json"


def _is_nan(value) -> bool:
    try:
        return isinstance(value, float) and math.isnan(value)
    except (TypeError, ValueError):
        return False


def _fetch_real_close(symbol: str, around_date: datetime) -> float | None:
    """Fetch the REAL NSE closing price for `symbol` on the first
    available trading day on/after `around_date` — a real, public
    historical fact, not a guess."""
    start = around_date.strftime("%Y-%m-%d")
    end = (around_date + timedelta(days=5)).strftime("%Y-%m-%d")
    try:
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
    except Exception as exc:
        logger.warning("Historical fetch failed for %s: %s", symbol, exc)
        return None
    if df.empty:
        return None
    close_col = df["Close"] if "Close" in df.columns else df.iloc[:, 3]
    first_valid = close_col.dropna()
    if first_valid.empty:
        return None
    return round(float(first_valid.iloc[0]), 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(PORTFOLIO_STATE_PATH) as f:
        state = json.load(f)

    repaired: list[dict] = []
    exclusions: list[str] = []

    for pos in state.get("closed_positions", []):
        if not _is_nan(pos.get("current_price")) and not _is_nan(pos.get("realized_pnl")):
            continue  # already fine, skip

        symbol = pos["symbol"]
        entry_price = pos["entry_price"]
        quantity = pos["quantity"]
        direction = pos.get("direction", "BUY")
        exit_date = datetime.fromtimestamp(pos.get("updated_at", 0))

        real_close = _fetch_real_close(symbol, exit_date)
        if real_close is None:
            logger.warning("Could not recover a real price for %s — leaving as NaN.", symbol)
            continue

        price_diff = real_close - entry_price
        if direction == "SELL":
            price_diff = -price_diff
        realized_pnl = round(price_diff * quantity, 2)
        realized_pnl_percent = round(price_diff / entry_price * 100, 2) if entry_price else 0.0

        repaired.append({
            "symbol": symbol, "entry_price": entry_price, "recovered_exit_price": real_close,
            "realized_pnl": realized_pnl, "realized_pnl_percent": realized_pnl_percent,
        })

        if not args.dry_run:
            pos["current_price"] = real_close
            pos["realized_pnl"] = realized_pnl
            pos["realized_pnl_percent"] = realized_pnl_percent
            pos["data_recovered"] = True  # audit trail — this was NOT a live-observed exit price

        exclusions.append(symbol)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Recovered {len(repaired)} record(s):")
    for r in repaired:
        print(f"  {r['symbol']}: exit={r['recovered_exit_price']}, "
              f"P&L=₹{r['realized_pnl']} ({r['realized_pnl_percent']}%)")

    if args.dry_run:
        return

    with open(PORTFOLIO_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

    # Propagate the same recovered numbers into the diary (matched by
    # symbol — this repair batch has exactly one closed trade per
    # symbol, so a symbol match is unambiguous here).
    diary = TradeDiary()
    for r in repaired:
        for trade_id in diary.list_closed_trade_ids():
            record = diary.get_diary(trade_id)
            if record and record.get("symbol") == r["symbol"] and _is_nan(record.get("exit_price")):
                record["exit_price"] = r["recovered_exit_price"]
                record["final_pnl"] = r["realized_pnl"]
                record["final_pnl_percent"] = r["realized_pnl_percent"]
                record["data_recovered"] = True
                diary._write(trade_id, record)

    # Propagate into trades_master.csv (rewrite — no in-place CSV update).
    import csv
    if Path(TRADE_STORE_PATH).exists():
        with open(TRADE_STORE_PATH, newline="") as f:
            rows = list(csv.DictReader(f))
        fieldnames = rows[0].keys() if rows else []
        for row in rows:
            if row.get("status") == "CLOSED" and row.get("symbol") in [r["symbol"] for r in repaired]:
                match = next(r for r in repaired if r["symbol"] == row["symbol"])
                row["exit_price"] = match["recovered_exit_price"]
                row["realized_pnl"] = match["realized_pnl"]
                row["realized_pnl_percent"] = match["realized_pnl_percent"]
        with open(TRADE_STORE_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # Record exclusions so Learning Engine never treats these
    # bug-forced exits as genuine strategy performance data.
    existing_exclusions = []
    if Path(EXCLUSIONS_PATH).exists():
        with open(EXCLUSIONS_PATH) as f:
            existing_exclusions = json.load(f)
    combined = sorted(set(existing_exclusions) | set(exclusions))
    with open(EXCLUSIONS_PATH, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"\n{len(exclusions)} symbol(s) added to learning_exclusions.json "
          f"(excluded from Learning Engine analysis — these were bug-forced exits).")


if __name__ == "__main__":
    main()
