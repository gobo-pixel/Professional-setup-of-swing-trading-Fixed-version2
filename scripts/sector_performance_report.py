"""
SECTOR PERFORMANCE REPORT

Two independent sections, both requested explicitly by the user:

PART A — Paper Trading's OWN sector performance
    Groups this system's actual closed trades (storage/trades/trades_master.csv,
    cross-referenced with virtual_portfolio_state.json's symbol_sector map) by
    sector, and reports total realized P&L / win rate per sector.
    Only covers however much real trading history this system has
    accumulated so far — NOT a market-wide historical view.

PART B — Broader stock market sector performance (1y / 6mo)
    Fetches REAL historical closing prices via yfinance for a
    representative set of symbols per sector, computes each symbol's
    price return over the requested period, and averages by sector.
    Requires internet — run via GitHub Actions, not offline.

Usage:
    python scripts/sector_performance_report.py --period 1y
    python scripts/sector_performance_report.py --period 6mo
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf  # noqa: E402

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402

logger = get_logger(__name__)

PORTFOLIO_STATE_PATH = "storage/trades/virtual_portfolio_state.json"
TRADE_STORE_PATH = "storage/trades/trades_master.csv"


def _part_a_paper_trading_sectors() -> dict:
    """Group this system's own closed trades by sector — existing
    data only, no network calls."""
    if not Path(PORTFOLIO_STATE_PATH).exists():
        return {}
    with open(PORTFOLIO_STATE_PATH) as f:
        state = json.load(f)
    symbol_sector = state.get("symbol_sector", {})

    sector_stats = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for pos in state.get("closed_positions", []):
        pnl = pos.get("realized_pnl")
        if pnl is None or (isinstance(pnl, float) and pnl != pnl):  # skip NaN
            continue
        sector = symbol_sector.get(pos["symbol"], "UNKNOWN")
        sector_stats[sector]["pnl"] += pnl
        sector_stats[sector]["trades"] += 1
        if pnl > 0:
            sector_stats[sector]["wins"] += 1

    return dict(sector_stats)


def _part_b_market_sector_performance(period: str) -> dict:
    """Fetch REAL historical price data per sector's representative
    symbols and compute average return — requires internet. Uses
    full_report.csv's Sector column (covers all scanned symbols, not
    just traded ones) for broader, more representative sector coverage."""
    sector_symbols: dict[str, list[str]] = defaultdict(list)
    report_path = Path("reports/full_report.csv")
    if report_path.exists():
        with open(report_path, newline="") as f:
            seen = set()
            for row in csv.DictReader(f):
                symbol = row.get("Stock") or row.get("Symbol")
                sector = row.get("Sector")
                if symbol and sector and symbol not in seen:
                    sector_symbols[sector].append(symbol)
                    seen.add(symbol)

    # Cap at a representative sample per sector to keep fetch time
    # reasonable — this is a REAL average of REAL stocks, just not
    # exhaustively every single symbol in that sector.
    MAX_PER_SECTOR = 5
    sector_returns: dict[str, list[float]] = defaultdict(list)

    for sector, symbols in sector_symbols.items():
        for symbol in symbols[:MAX_PER_SECTOR]:
            try:
                df = yf.download(symbol, period=period, progress=False, auto_adjust=False)
                if df.empty or len(df) < 2:
                    continue
                close_col = df["Close"] if "Close" in df.columns else df.iloc[:, 3]
                close_col = close_col.dropna()
                if len(close_col) < 2:
                    continue
                start_price = float(close_col.iloc[0])
                end_price = float(close_col.iloc[-1])
                if start_price <= 0:
                    continue
                pct_return = (end_price - start_price) / start_price * 100
                sector_returns[sector].append(pct_return)
            except Exception as exc:
                logger.warning("Historical fetch failed for %s: %s", symbol, exc)
                continue

    return {
        sector: round(sum(returns) / len(returns), 2)
        for sector, returns in sector_returns.items() if returns
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="1y", choices=["1mo", "3mo", "6mo", "1y", "2y"])
    args = parser.parse_args()

    part_a = _part_a_paper_trading_sectors()
    part_b = _part_b_market_sector_performance(args.period)

    lines = ["📊 Sector Performance Report", ""]

    lines.append("Part A — Paper Trading's Own Sector Performance")
    if part_a:
        ranked = sorted(part_a.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
        for sector, stats in ranked:
            win_rate = round(stats["wins"] / stats["trades"] * 100, 1) if stats["trades"] else 0.0
            sign = "+" if stats["pnl"] >= 0 else ""
            lines.append(
                f"{sector}: {sign}₹{stats['pnl']:.2f} "
                f"({stats['trades']} trades, {win_rate}% win rate)"
            )
    else:
        lines.append("No closed trades yet.")

    lines.append("")
    lines.append(f"Part B — Market Sector Performance ({args.period})")
    if part_b:
        ranked_b = sorted(part_b.items(), key=lambda kv: kv[1], reverse=True)
        for sector, ret in ranked_b:
            sign = "+" if ret >= 0 else ""
            lines.append(f"{sector}: {sign}{ret}%")
    else:
        lines.append("Could not fetch market data (no internet, or no symbol_sector map available).")

    message = "\n".join(lines)
    print(message)

    notify(
        event_type="sector_performance_report",
        message=message,
        dedup_key=f"sector_performance::{time.strftime('%Y-%m-%d')}",
    )


if __name__ == "__main__":
    main()
