"""
RUN MARKET INTELLIGENCE (daily research pass)

Independent from the trading pipeline. Reads the currently open Virtual
Portfolio positions (read-only — never modifies them), researches
news/macro context for each, and sends advisory Telegram notifications
for anything significant. Never generates a trading signal.

Usage:
    python scripts/run_market_intelligence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from core.trading_calendar import is_trading_day, now_ist  # noqa: E402
from market_intelligence.market_intelligence_engine import MarketIntelligenceEngine  # noqa: E402
from paper_trading.virtual_portfolio import VirtualPortfolio  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    if not is_trading_day():
        logger.info("Not an NSE trading day — Market Intelligence run skipped.")
        print("Not an NSE trading day. Skipping (no run until the next trading day).")
        return

    portfolio = VirtualPortfolio()
    open_positions = [
        {
            "symbol": symbol,
            "direction": pos.direction,
            "sector": portfolio.sector_for(symbol),
        }
        for symbol, pos in portfolio.engine.state.open_positions.items()
    ]

    if not open_positions:
        logger.info("No open positions — nothing for Market Intelligence to research today.")
        print("No open positions to research.")
        notify(
            event_type="market_intelligence_summary",
            message=(
                "📊 Market Intelligence\n\n"
                "✅ Completed\n\n"
                "Open Positions: 0\n\n"
                "Nothing to research today."
            ),
            dedup_key=f"mi_summary_empty::{now_ist().strftime('%Y-%m-%d %H:%M:%S.%f')}",
        )
        return

    engine = MarketIntelligenceEngine()
    result = engine.run(open_positions)

    print(f"\n=== MARKET INTELLIGENCE — {len(open_positions)} open position(s) researched ===")
    print(f"Overall market sentiment : {result['macro']['overall_market_sentiment_score']}")
    print(f"Macro risk score         : {result['macro']['macro_risk_score']}")
    print(f"Global risk level        : {result['macro']['global_risk_level']}")
    if result["macro"]["critical_events"]:
        print(f"Critical events detected : {result['macro']['critical_events']}")
    print(f"Alerts sent              : {len(result['alerts_sent'])}")
    for msg in result["alerts_sent"]:
        print("  ---")
        print(" ", msg.replace("\n", "\n  "))


if __name__ == "__main__":
    main()
