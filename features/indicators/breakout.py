"""
Breakout & Price Action Indicators.

Responsibilities:
- Pivot Points
- Breakout Detection
- Pullback Detection
- Gap Detection
- Relative Strength (vs benchmark placeholder column)

Adds price-action features to the dataframe.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import IndicatorError
from core.logger import get_logger

logger = get_logger(__name__)


class BreakoutIndicators:
    """Breakout indicator engine."""

    def calculate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise IndicatorError("Empty dataframe received.")

        required = {"open", "high", "low", "close", "volume"}
        missing = required.difference(dataframe.columns)

        if missing:
            raise IndicatorError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        # ---------- Classic Pivot ----------
        df["pivot"] = (
            df["high"].shift(1) + df["low"].shift(1) + df["close"].shift(1)
        ) / 3

        df["resistance_1"] = (2 * df["pivot"]) - df["low"].shift(1)

        df["support_1"] = (2 * df["pivot"]) - df["high"].shift(1)

        # ---------- 20-Day High / Low ----------
        previous_high = df["high"].rolling(20, min_periods=20).max().shift(1)

        previous_low = df["low"].rolling(20, min_periods=20).min().shift(1)

        # ---------- Breakout ----------
        df["is_breakout"] = df["close"] > previous_high

        # ---------- Breakdown ----------
        df["is_breakdown"] = df["close"] < previous_low

        # ---------- Pullback ----------
        ema20 = df["close"].ewm(span=20, adjust=False).mean()

        df["is_pullback"] = (df["low"] <= ema20) & (df["close"] > ema20)

        # ---------- Gap ----------
        prev_close = df["close"].shift(1)

        df["gap_pct"] = ((df["open"] - prev_close) / prev_close) * 100

        df["gap_up"] = df["gap_pct"] >= 1.0
        df["gap_down"] = df["gap_pct"] <= -1.0

        # ---------- Relative Strength ----------
        # Benchmark integration will be added by Data Engine later.
        df["relative_strength"] = df["close"] / df["close"].rolling(20).mean()

        logger.info("Breakout indicators calculated.")

        return df
