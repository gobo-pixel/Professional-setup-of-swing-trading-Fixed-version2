"""
Portfolio Engine

Single Source of Truth for:
• Capital allocation
• Open positions
• Realized / unrealized PnL
• Exposure tracking
• Risk aggregation

This replaces scattered portfolio dict usage.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# POSITION RECORD
# ==========================================================


@dataclass(slots=True)
class PortfolioPosition:

    symbol: str

    quantity: int

    entry_price: float

    current_price: float

    direction: str  # BUY / SELL

    unrealized_pnl: float = 0.0

    unrealized_pnl_percent: float = 0.0

    realized_pnl: float = 0.0

    realized_pnl_percent: float = 0.0

    highest_price: float = 0.0

    lowest_price: float = 0.0

    max_profit_percent: float = 0.0

    max_drawdown_percent: float = 0.0

    status: str = "OPEN"

    updated_at: float = field(default_factory=time.time)


# ==========================================================
# PORTFOLIO STATE
# ==========================================================


@dataclass(slots=True)
class PortfolioState:

    total_capital: float

    available_capital: float

    used_capital: float = 0.0

    open_positions: dict[str, PortfolioPosition] = field(default_factory=dict)

    closed_positions: list[PortfolioPosition] = field(default_factory=list)

    total_pnl: float = 0.0

    total_pnl_percent: float = 0.0

    exposure: float = 0.0

    risk_score: float = 0.0

    updated_at: float = field(default_factory=time.time)


# ==========================================================
# ADD POSITION
# ==========================================================


class PortfolioEngine:

    def __init__(self, state: PortfolioState):

        self.state = state

    def add_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        direction: str,
    ) -> bool:

        if symbol in self.state.open_positions:

            logger.warning(
                "Position already exists %s",
                symbol,
            )

            return False

        position_value = quantity * entry_price

        if position_value > self.state.available_capital:

            logger.warning(
                "Insufficient capital for %s",
                symbol,
            )

            return False

        self.state.open_positions[symbol] = PortfolioPosition(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            direction=direction,
            highest_price=entry_price,
            lowest_price=entry_price,
        )

        self.state.used_capital += position_value

        self.state.available_capital -= position_value

        self.state.updated_at = time.time()

        return True

    def _track_extremes(self, pos: "PortfolioPosition") -> None:
        """Update running highest/lowest price seen while a position is
        open, and derive max favorable/adverse excursion (MaxProfit /
        MaxDrawdown) from them. Called on every price update so these
        reflect the full path of the trade, not just entry vs exit."""
        pos.highest_price = max(pos.highest_price or pos.current_price, pos.current_price)
        pos.lowest_price = min(pos.lowest_price or pos.current_price, pos.current_price)

        entry = max(pos.entry_price, 1e-9)
        if pos.direction == "SELL":
            # For a short, profit comes from price falling, so the best
            # favorable move is the lowest price seen, and the worst
            # adverse move is the highest price seen.
            pos.max_profit_percent = ((entry - pos.lowest_price) / entry) * 100
            pos.max_drawdown_percent = ((pos.highest_price - entry) / entry) * 100
        else:
            pos.max_profit_percent = ((pos.highest_price - entry) / entry) * 100
            pos.max_drawdown_percent = ((entry - pos.lowest_price) / entry) * 100

    # ==========================================================
    # UPDATE POSITION
    # ==========================================================

    def update_position(
        self,
        symbol: str,
        current_price: float,
    ) -> None:

        if symbol not in self.state.open_positions:

            return

        pos = self.state.open_positions[symbol]

        pos.current_price = current_price

        price_diff = current_price - pos.entry_price

        if pos.direction == "SELL":

            price_diff *= -1

        pos.unrealized_pnl = price_diff * pos.quantity

        pos.unrealized_pnl_percent = (price_diff / max(pos.entry_price, 1e-9)) * 100

        self._track_extremes(pos)

        pos.updated_at = time.time()

    # ==========================================================
    # CLOSE POSITION
    # ==========================================================

    def close_position(
        self,
        symbol: str,
        exit_price: float,
    ) -> "PortfolioPosition | None":

        if symbol not in self.state.open_positions:

            return None

        pos = self.state.open_positions.pop(symbol)

        price_diff = exit_price - pos.entry_price

        if pos.direction == "SELL":

            price_diff *= -1

        realized_pnl = price_diff * pos.quantity

        realized_pnl_percent = (price_diff / max(pos.entry_price, 1e-9)) * 100

        pos.current_price = exit_price

        pos.realized_pnl = realized_pnl

        pos.realized_pnl_percent = realized_pnl_percent

        pos.unrealized_pnl = 0.0

        pos.unrealized_pnl_percent = 0.0

        pos.status = "CLOSED"

        pos.updated_at = time.time()

        self.state.closed_positions.append(pos)

        self.state.total_pnl += realized_pnl

        self._recalculate_capital()

        return pos

    # ==========================================================
    # PARTIAL EXIT
    # ==========================================================

    def partial_exit(
        self,
        symbol: str,
        quantity: int,
        exit_price: float,
    ) -> None:

        if symbol not in self.state.open_positions:

            return

        pos = self.state.open_positions[symbol]

        quantity = min(quantity, pos.quantity)

        price_diff = exit_price - pos.entry_price

        if pos.direction == "SELL":

            price_diff *= -1

        realized_pnl = price_diff * quantity

        pos.quantity -= quantity

        pos.realized_pnl += realized_pnl

        pos.updated_at = time.time()

        self.state.total_pnl += realized_pnl

        if pos.quantity == 0:

            self.close_position(symbol, exit_price)

        self._recalculate_capital()

    # ==========================================================
    # CAPITAL REBALANCE
    # ==========================================================

    def _recalculate_capital(self) -> None:

        used = 0.0

        for pos in self.state.open_positions.values():

            used += pos.quantity * pos.entry_price

        self.state.used_capital = used

        self.state.available_capital = self.state.total_capital + self.state.total_pnl - used

        self.state.exposure = used / max(self.state.total_capital, 1e-9)

        self.state.updated_at = time.time()

    # ==========================================================
    # PORTFOLIO VALUATION
    # ==========================================================

    def mark_to_market(self) -> None:

        total_unrealized = 0.0

        total_unrealized_percent = 0.0

        for pos in self.state.open_positions.values():

            price_diff = pos.current_price - pos.entry_price

            if pos.direction == "SELL":

                price_diff *= -1

            pos.unrealized_pnl = price_diff * pos.quantity

            pos.unrealized_pnl_percent = (price_diff / max(pos.entry_price, 1e-9)) * 100

            self._track_extremes(pos)

            total_unrealized += pos.unrealized_pnl

            total_unrealized_percent += pos.unrealized_pnl_percent

        # NaN-safe: a historical closed position with an unrecoverable
        # (NaN) realized_pnl must not poison this SUM forever — exclude
        # it from the total rather than letting a single old corrupted
        # record propagate NaN through every future day's total_pnl.
        # The corrupted record itself is left untouched (not fabricated
        # or zeroed) — it's simply excluded from this aggregate, the
        # same way a NULL is excluded from a SQL SUM().
        known_realized_pnl = [
            p.realized_pnl for p in self.state.closed_positions
            if not (isinstance(p.realized_pnl, float) and math.isnan(p.realized_pnl))
        ]
        self.state.total_pnl = sum(known_realized_pnl) + total_unrealized

        self.state.total_pnl_percent = (
            self.state.total_pnl / max(self.state.total_capital, 1e-9)
        ) * 100

        self.state.updated_at = time.time()

    # ==========================================================
    # RISK SCORE CALCULATION
    # ==========================================================

    def update_risk_score(self) -> None:

        if not self.state.open_positions:

            self.state.risk_score = 0.0

            return

        exposure_ratio = self.state.exposure

        drawdown = 0.0

        if self.state.total_capital > 0:

            peak_value = self.state.total_capital + max(
                self.state.total_pnl,
                0.0,
            )

            current_value = self.state.total_capital + self.state.total_pnl

            drawdown = max(
                0.0,
                (peak_value - current_value) / max(peak_value, 1e-9),
            )

        concentration_risk = max(
            (
                pos.quantity * pos.current_price
                for pos in self.state.open_positions.values()
            ),
            default=0.0,
        ) / max(self.state.total_capital, 1e-9)

        self.state.risk_score = min(
            100.0,
            (exposure_ratio * 40 + drawdown * 40 + concentration_risk * 20) * 100,
        )

    # ==========================================================
    # PORTFOLIO SUMMARY
    # ==========================================================

    def summary(self) -> str:

        open_count = len(self.state.open_positions)

        closed_count = len(self.state.closed_positions)

        return (
            f"Capital={self.state.total_capital:.2f} | "
            f"Used={self.state.used_capital:.2f} | "
            f"Avail={self.state.available_capital:.2f} | "
            f"Exposure={self.state.exposure:.4f} | "
            f"PnL={self.state.total_pnl:.2f} | "
            f"Open={open_count} | "
            f"Closed={closed_count} | "
            f"Risk={self.state.risk_score:.2f}"
        )

    # ==========================================================
    # PORTFOLIO HEALTH CHECK
    # ==========================================================

    def health_check(self) -> dict[str, Any]:

        self.update_risk_score()

        status = "HEALTHY"

        if self.state.risk_score > 80:

            status = "CRITICAL"

        elif self.state.risk_score > 60:

            status = "DEGRADED"

        return {
            "status": status,
            "risk_score": round(self.state.risk_score, 2),
            "exposure": round(self.state.exposure, 4),
            "total_pnl": round(self.state.total_pnl, 2),
            "open_positions": len(self.state.open_positions),
        }

    # ==========================================================
    # POSITION SNAPSHOT
    # ==========================================================

    def snapshot(self) -> dict[str, Any]:

        return {
            "total_capital": self.state.total_capital,
            "available_capital": self.state.available_capital,
            "used_capital": self.state.used_capital,
            "exposure": self.state.exposure,
            "total_pnl": self.state.total_pnl,
            "total_pnl_percent": self.state.total_pnl_percent,
            "risk_score": self.state.risk_score,
            "open_positions": {
                k: {
                    "quantity": v.quantity,
                    "entry_price": v.entry_price,
                    "current_price": v.current_price,
                    "unrealized_pnl": v.unrealized_pnl,
                    "status": v.status,
                }
                for k, v in self.state.open_positions.items()
            },
            "closed_positions_count": len(self.state.closed_positions),
        }

    # ==========================================================
    # PORTFOLIO LIMIT GUARDS
    # ==========================================================

    def check_limits(self) -> dict[str, Any]:

        violations = []

        if self.state.exposure > 0.95:

            violations.append("EXCESS_EXPOSURE")

        if self.state.risk_score > 85:

            violations.append("HIGH_RISK_SCORE")

        if self.state.available_capital < 0:

            violations.append("NEGATIVE_CAPITAL")

        if self.state.total_pnl < -0.2 * self.state.total_capital:

            violations.append("MAX_DRAWDOWN_BREACH")

        return {
            "violations": violations,
            "blocked": len(violations) > 0,
        }

    # ==========================================================
    # STRESS TEST SIMULATION
    # ==========================================================

    def stress_test(
        self,
        shock_percent: float = 5.0,
    ) -> dict[str, Any]:

        shocked_pnl = 0.0

        for pos in self.state.open_positions.values():

            shock_move = pos.current_price * (shock_percent / 100)

            if pos.direction == "BUY":

                shocked_pnl += -shock_move * pos.quantity

            else:

                shocked_pnl += shock_move * pos.quantity

        stressed_value = self.state.total_pnl + shocked_pnl

        stressed_drawdown = (stressed_value / max(self.state.total_capital, 1e-9)) * 100

        return {
            "shock_percent": shock_percent,
            "shocked_pnl": round(shocked_pnl, 2),
            "stressed_pnl": round(stressed_value, 2),
            "stressed_drawdown_percent": round(stressed_drawdown, 2),
        }

    # ==========================================================
    # CAPITAL SAFETY CHECK
    # ==========================================================

    def is_tradable(self) -> bool:

        limits = self.check_limits()

        if limits["blocked"]:

            return False

        if self.state.available_capital <= 0:

            return False

        return True

    # ==========================================================
    # EXPORT TO DICTIONARY
    # ==========================================================

    def to_dict(self) -> dict[str, Any]:

        return {
            "total_capital": self.state.total_capital,
            "available_capital": self.state.available_capital,
            "used_capital": self.state.used_capital,
            "exposure": self.state.exposure,
            "total_pnl": self.state.total_pnl,
            "total_pnl_percent": self.state.total_pnl_percent,
            "risk_score": self.state.risk_score,
            "open_positions_count": len(self.state.open_positions),
            "closed_positions_count": len(self.state.closed_positions),
        }

    # ==========================================================
    # EXPORT OPEN POSITIONS
    # ==========================================================

    def export_open_positions(self) -> list[dict[str, Any]]:

        return [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "direction": pos.direction,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_percent": pos.unrealized_pnl_percent,
                "status": pos.status,
            }
            for pos in self.state.open_positions.values()
        ]

    # ==========================================================
    # EXPORT CLOSED POSITIONS
    # ==========================================================

    def export_closed_positions(self) -> list[dict[str, Any]]:

        return [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "exit_price": pos.current_price,
                "direction": pos.direction,
                "realized_pnl": pos.realized_pnl,
                "status": pos.status,
            }
            for pos in self.state.closed_positions
        ]

    # ==========================================================
    # RESET PORTFOLIO
    # ==========================================================

    def reset(self) -> None:

        self.state.open_positions.clear()

        self.state.closed_positions.clear()

        self.state.used_capital = 0.0

        self.state.available_capital = self.state.total_capital

        self.state.exposure = 0.0

        self.state.total_pnl = 0.0

        self.state.total_pnl_percent = 0.0

        self.state.risk_score = 0.0

        self.state.updated_at = time.time()

    # ==========================================================
    # PORTFOLIO DEBUG REPORT
    # ==========================================================

    def debug_report(self) -> str:

        lines = []

        lines.append("=" * 120)
        lines.append("PORTFOLIO DEBUG REPORT")
        lines.append("=" * 120)
        lines.append("")

        lines.append(self.summary())
        lines.append("")

        lines.append("-" * 120)
        lines.append("OPEN POSITIONS")
        lines.append("-" * 120)

        for pos in self.state.open_positions.values():

            lines.append(
                f"{pos.symbol:<15}"
                f"{pos.direction:<8}"
                f"{pos.quantity:<8}"
                f"{pos.entry_price:<12.4f}"
                f"{pos.current_price:<12.4f}"
                f"{pos.unrealized_pnl:<12.2f}"
                f"{pos.status:<10}"
            )

        lines.append("")
        lines.append("-" * 120)
        lines.append("CLOSED POSITIONS")
        lines.append("-" * 120)

        for pos in self.state.closed_positions:

            lines.append(
                f"{pos.symbol:<15}"
                f"{pos.direction:<8}"
                f"{pos.quantity:<8}"
                f"{pos.entry_price:<12.4f}"
                f"{pos.current_price:<12.4f}"
                f"{pos.realized_pnl:<12.2f}"
                f"{pos.status:<10}"
            )

        lines.append("")
        lines.append("-" * 120)
        lines.append("RISK SNAPSHOT")
        lines.append("-" * 120)

        lines.append(f"Risk Score        : {self.state.risk_score:.2f}")

        lines.append(f"Exposure          : {self.state.exposure:.4f}")

        lines.append(f"Total PnL         : {self.state.total_pnl:.2f}")

        lines.append(f"PnL %             : {self.state.total_pnl_percent:.2f}")

        lines.append("")
        lines.append("=" * 120)
        lines.append("END PORTFOLIO REPORT")
        lines.append("=" * 120)

        return "\n".join(lines)

    # ==========================================================
    # PORTFOLIO HEALTH REPORT
    # ==========================================================

    def health_report(self) -> dict[str, Any]:

        limits = self.check_limits()

        stress = self.stress_test()

        health_score = (
            (1 - min(self.state.exposure, 1.0)) * 40
            + (1 - min(self.state.risk_score / 100, 1.0)) * 30
            + (1 - max(abs(self.state.total_pnl_percent) / 100, 0.0)) * 30
        )

        health_score = max(0.0, min(100.0, health_score))

        status = "HEALTHY"

        if health_score < 50:

            status = "CRITICAL"

        elif health_score < 75:

            status = "DEGRADED"

        return {
            "status": status,
            "health_score": round(health_score, 2),
            "limits": limits,
            "stress_test": stress,
        }


# ==========================================================
# END OF FILE
# ==========================================================
