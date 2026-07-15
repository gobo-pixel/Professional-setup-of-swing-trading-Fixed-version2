"""
Position Tracker Engine

Institutional Production Version

Responsibilities
----------------
• Track all open positions in real time
• Update price, PnL, highs/lows
• Maintain trade state
• Feed exit strategy engine
• Trigger risk updates
• Generate portfolio-level position snapshot

This engine does NOT:
• Open trades
• Close trades directly
• Modify strategy logic
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.logger import get_logger

from risk.exit_strategy import ExitStrategyEngine
from risk.risk_manager import RiskManager
from risk.position_sizing import PositionSizingEngine

logger = get_logger(__name__)


# ==========================================================
# POSITION STATE
# ==========================================================


@dataclass(slots=True)
class PositionState:

    symbol: str

    entry_price: float

    quantity: int

    direction: str  # BUY / SELL

    entry_time: str

    current_price: float = 0.0

    pnl_percent: float = 0.0

    pnl_absolute: float = 0.0

    highest_price: float = 0.0

    lowest_price: float = 0.0

    holding_days: int = 0

    stop_loss: float = 0.0

    take_profit: float = 0.0

    trailing_stop: float = 0.0

    status: str = "OPEN"  # OPEN / CLOSED / SUSPENDED

    diagnostics: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# TRACKER RESULT
# ==========================================================


@dataclass(slots=True)
class TrackerResult:

    symbol: str

    action: str  # HOLD / EXIT / REDUCE / TRAIL

    status: str

    pnl_percent: float

    pnl_absolute: float

    current_price: float

    stop_loss: float

    take_profit: float

    warnings: list[str] = field(default_factory=list)

    diagnostics: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# TRACKER SYSTEM
# ==========================================================


class PositionTracker:

    def __init__(self):

        self.positions: dict[str, PositionState] = {}

        self.exit_engine = ExitStrategyEngine()

        self.risk_manager = RiskManager()

        self.sizer = PositionSizingEngine()

        logger.info("Position Tracker Engine initialized successfully.")

    # ==========================================================
    # ADD POSITION
    # ==========================================================

    def add_position(self, state: PositionState) -> bool:

        if state.symbol in self.positions:

            logger.warning("Position for %s already exists. Overwriting.", state.symbol)

        self.positions[state.symbol] = state

        logger.info(
            "Tracked new position: %s | Qty=%d | Entry=%s",
            state.symbol,
            state.quantity,
            state.entry_price,
        )

        return True

    # ==========================================================
    # REMOVE POSITION
    # ==========================================================

    def remove_position(self, symbol: str) -> bool:

        if symbol in self.positions:

            del self.positions[symbol]

            logger.info("Removed %s from tracker database.", symbol)

            return True

        logger.warning("Attempted to remove non-existent symbol: %s", symbol)

        return False

    # ==========================================================
    # UPDATE SYSTEM
    # ==========================================================

    def update(
        self,
        dataframe_map: dict[str, pd.DataFrame],
        portfolio: dict[str, Any],
        market: dict[str, Any],
    ) -> list[TrackerResult]:

        results: list[TrackerResult] = []

        if not self.positions:

            logger.debug("No open positions to track.")

            return results

        logger.info("Updating %d active positions.", len(self.positions))

        for symbol, pos in list(self.positions.items()):

            if pos.status == "CLOSED":

                continue

            df = dataframe_map.get(symbol, None)

            if df is None or df.empty:

                logger.error("No historical dataframe found for %s", symbol)

                continue

            latest = df.iloc[-1]

            close = float(latest.get("close", pos.entry_price))

            high = float(latest.get("high", close))

            low = float(latest.get("low", close))

            # --------------------------------------------------
            # MATH ENGINE
            # --------------------------------------------------

            pos.current_price = close

            pos.highest_price = max(pos.highest_price, high)

            pos.lowest_price = (
                min(pos.lowest_price, low) if pos.lowest_price > 0 else low
            )

            pos.holding_days += 1

            # --------------------------------------------------
            # PNL CALCULATOR
            # --------------------------------------------------

            if pos.direction == "BUY":

                pos.pnl_absolute = (close - pos.entry_price) * pos.quantity

                pos.pnl_percent = ((close / pos.entry_price) - 1.0) * 100.0

            else:

                pos.pnl_absolute = (pos.entry_price - close) * pos.quantity

                pos.pnl_percent = ((pos.entry_price / close) - 1.0) * 100.0

            # --------------------------------------------------
            # RISK PIPELINE INTEGRATION
            # --------------------------------------------------

            from decision.validation_engine import ValidationResult
            from decision.decision_engine import FinalDecision

            v = ValidationResult(passed=True)

            d = FinalDecision(signal="HOLD", confidence=100.0)

            # <--- FIXED: Change risk_engine to self.risk_manager
            risk_result = self.risk_manager.evaluate(
                validation=v,
                decision=d,
                dataframe=df,
                portfolio=portfolio,
                market=market,
            )

            # --------------------------------------------------
            # EXIT STRATEGY ENGINE
            # --------------------------------------------------

            exit_result = self.exit_engine.evaluate(
                position=pos,
                dataframe=df,
                risk=risk_result,
            )

            # --------------------------------------------------
            # PROCESS ACTIONS
            # --------------------------------------------------

            if exit_result.action in {"EXIT", "FORCE_EXIT"}:

                pos.status = "CLOSED"

                logger.info("Exit trigger detected for %s.", symbol)

            elif exit_result.action == "TRAIL":

                if exit_result.new_stop > 0:

                    pos.trailing_stop = exit_result.new_stop

                    pos.stop_loss = exit_result.new_stop

            # --------------------------------------------------
            # COMPILE RESULT
            # --------------------------------------------------

            results.append(
                TrackerResult(
                    symbol=symbol,
                    action=exit_result.action,
                    status=pos.status,
                    pnl_percent=round(pos.pnl_percent, 2),
                    pnl_absolute=round(pos.pnl_absolute, 2),
                    current_price=close,
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    warnings=exit_result.warnings,
                    diagnostics={
                        "holding_days": pos.holding_days,
                        "highest": pos.highest_price,
                        "lowest": pos.lowest_price,
                        "risk_grade": risk_result.risk_grade,
                        "exit_reason": exit_result.reason,
                    },
                )
            )

        logger.info("Completed position tracker cycle.")

        return results

    # ==========================================================
    # GET SNAPSHOT
    # ==========================================================

    def get_snapshot(self) -> dict[str, Any]:

        open_count = sum(1 for p in self.positions.values() if p.status == "OPEN")

        total_pnl = sum(p.pnl_absolute for p in self.positions.values())

        return {
            "total_tracked_positions": len(self.positions),
            "open_positions_count": open_count,
            "total_portfolio_pnl_absolute": round(total_pnl, 2),
            "symbols": list(self.positions.keys()),
        }

    # ==========================================================
    # SUMMARY BUILDER
    # ==========================================================

    @staticmethod
    def summary(results: list[TrackerResult]) -> str:

        if not results:

            return "Tracker Summary: No active tracking items."

        total_items = len(results)

        exits = sum(1 for r in results if r.action in {"EXIT", "FORCE_EXIT"})

        holds = sum(1 for r in results if r.action == "HOLD")

        trails = sum(1 for r in results if r.action == "TRAIL")

        avg_pnl = sum(r.pnl_percent for r in results) / total_items

        return (
            f"Tracker Sync Report | Total={total_items}"
            f" | HOLDS={holds}"
            f" | EXITS={exits}"
            f" | TRAILS={trails}"
            f" | Avg PnL={avg_pnl:.2f}%"
        )

    # ==========================================================
    # TOP MOVERS
    # ==========================================================

    @staticmethod
    def top_movers(
        results: list[TrackerResult],
        limit: int = 10,
    ) -> list[TrackerResult]:

        return sorted(
            results,
            key=lambda r: r.pnl_percent,
            reverse=True,
        )[:limit]

    # ==========================================================
    # DEBUG REPORT
    # ==========================================================

    @staticmethod
    def debug_report(
        results: list[TrackerResult],
    ) -> str:

        report: list[str] = []

        report.append("=" * 120)
        report.append("TRACKER SYSTEM REPORT")
        report.append("=" * 120)
        report.append("")

        # <--- FIXED: Change Tracker to PositionTracker
        report.append(PositionTracker.summary(results))

        report.append("")
        report.append("-" * 120)

        for r in results:

            report.append(
                f"{r.symbol:<15}"
                f"{r.action:<10}"
                f"{r.status:<12}"
                f"{r.pnl_percent:>10.2f}%"
                f"{r.pnl_absolute:>15.2f}"
            )

        report.append("")
        report.append("=" * 120)

        return "\n".join(report)


# ==========================================================
# END OF FILE
# ==========================================================
