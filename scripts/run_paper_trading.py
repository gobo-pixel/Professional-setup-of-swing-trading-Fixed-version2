"""
RUN PAPER TRADING (daily cycle)

Runs one day's paper-trading cycle: monitors every open virtual
position through the Exit Engine, opens new virtual positions for any
fresh BUY/SELL signal that clears production validation, and writes a
daily report.

Usage:
    python scripts/run_paper_trading.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from data.watchlist import WatchlistManager  # noqa: E402
from paper_trading.paper_trading_engine import PaperTradingEngine  # noqa: E402
from storage.trades.trade_diary import TradeDiary  # noqa: E402

logger = get_logger(__name__)

REPORT_PATH = "reports/paper_trading_daily_report.csv"


def average_holding_days(closed_trades: list[dict]) -> float:
    days = [t.get("holding_days", 0) for t in closed_trades]
    return round(sum(days) / len(days), 2) if days else 0.0


def write_daily_report(summary: dict, diary: TradeDiary) -> None:
    Path("reports").mkdir(exist_ok=True)

    open_trades = diary.get_open_trades()
    closed_trades = diary.get_closed_trades()
    snap = summary["portfolio_snapshot"]

    row = {
        "Date": summary["date"],
        "OpenedToday": len(summary["opened_today"]),
        "ClosedToday": len(summary["closed_today"]),
        "Monitored": len(summary["monitored"]),
        "OpenPositions": len(open_trades),
        "ClosedPositions": len(closed_trades),
        "CashBalance": round(snap.get("available_capital", 0.0), 2),
        "PortfolioValue": round(snap.get("portfolio_value", 0.0), 2),
        "RealizedPnL": round(snap.get("total_pnl", 0.0), 2),
        "PortfolioReturnPercent": round(snap.get("portfolio_return_percent", 0.0), 2),
        "WinRate": snap.get("win_rate"),
        "LossRate": snap.get("loss_rate"),
        "AverageHoldingDays": average_holding_days(closed_trades),
        "SectorExposure": json.dumps(snap.get("sector_exposure", {})),
        "ClosedToday_Detail": json.dumps(summary["closed_today"]),
        "OpenedToday_Detail": json.dumps(summary["opened_today"]),
    }

    file_exists = Path(REPORT_PATH).exists()
    with open(REPORT_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    logger.info("Daily paper-trading report appended to %s", REPORT_PATH)


def main() -> None:
    symbols = WatchlistManager("storage/watchlist/nifty500.json").load()
    if not symbols:
        logger.warning("Watchlist empty; nothing to scan.")
        symbols = []

    engine = PaperTradingEngine()
    summary = engine.run_cycle(symbols)

    ran_cycle = summary.get("status") != "SKIPPED_NON_TRADING_DAY"
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"ran_cycle={'true' if ran_cycle else 'false'}\n")

    write_daily_report(summary, engine.diary)

    if ran_cycle:
        snap = summary["portfolio_snapshot"]
        notify(
            event_type="daily_portfolio_summary",
            message=(
                f"Daily Portfolio Summary — {summary['date']}\n"
                f"Portfolio Value: {snap.get('portfolio_value', 0):.2f}\n"
                f"Realized PnL: {snap.get('total_pnl', 0):.2f} "
                f"({snap.get('portfolio_return_percent', 0):.2f}%)\n"
                f"Opened: {len(summary['opened_today'])} | "
                f"Closed: {len(summary['closed_today'])} | "
                f"Monitored: {len(summary['monitored'])}"
            ),
            dedup_key=f"portfolio_summary::{summary['date']}",
        )

    if summary.get("status") == "SKIPPED_NON_TRADING_DAY":
        print(f"\n=== PAPER TRADING — {summary['date']} ===")
        print("SKIPPED: not an NSE trading day (weekend or holiday). No new entries, no monitoring.")
        return

    print(f"\n=== PAPER TRADING — {summary['date']} ===")
    print(f"Opened today : {len(summary['opened_today'])}")
    for o in summary["opened_today"]:
        print(f"  + {o['symbol']:15s} {o['action']:4s} @ {o['price']}")
    print(f"Closed today : {len(summary['closed_today'])}")
    for c in summary["closed_today"]:
        print(f"  - {c['symbol']:15s} PnL={c['pnl']:.2f}")
    print(f"Monitored (held): {len(summary['monitored'])}")

    snap = summary["portfolio_snapshot"]
    print(f"\nPortfolio value : {snap.get('portfolio_value', 0):.2f}")
    print(f"Cash balance    : {snap.get('available_capital', 0):.2f}")
    print(f"Realized PnL    : {snap.get('total_pnl', 0):.2f}")
    print(f"Return          : {snap.get('portfolio_return_percent', 0):.2f}%")
    if snap.get("win_rate") is not None:
        print(f"Win rate        : {snap['win_rate']}%")


if __name__ == "__main__":
    main()
