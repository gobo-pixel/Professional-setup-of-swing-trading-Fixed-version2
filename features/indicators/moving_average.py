"""
Moving Average Indicators.

Responsibilities:
- SMA
- EMA
- WMA
- VWMA

Adds columns to the incoming dataframe.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import IndicatorError
from core.logger import get_logger

logger = get_logger(__name__)


class MovingAverageIndicators:
    """Moving average indicator engine."""

    def calculate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise IndicatorError("Empty dataframe received.")

        required = {"close", "volume"}
        missing = required.difference(dataframe.columns)
        if missing:
            raise IndicatorError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        # Simple Moving Averages
        for period in (20, 50, 100, 200):
            df[f"sma_{period}"] = (
                df["close"].rolling(window=period, min_periods=period).mean()
            )

        # Exponential Moving Averages
        for period in (9, 20, 50, 100, 200):
            df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()

        # Weighted Moving Average
        for period in (20, 50):
            weights = pd.Series(range(1, period + 1), dtype="float64")

            df[f"wma_{period}"] = (
                df["close"]
                .rolling(period)
                .apply(
                    lambda prices: (prices * weights).sum() / weights.sum(),
                    raw=False,
                )
            )

        # Volume Weighted Moving Average
        for period in (20, 50):
            pv = df["close"] * df["volume"]
            df[f"vwma_{period}"] = (
                pv.rolling(period).sum() / df["volume"].rolling(period).sum()
            )

        logger.info("Moving average indicators calculated.")

        return df
