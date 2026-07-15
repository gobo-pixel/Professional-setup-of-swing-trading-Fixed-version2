"""
Pattern Indicators.

Responsibilities:
- Inside Bar
- Outside Bar
- Bullish Engulfing
- Bearish Engulfing
- Doji
- Hammer
- Shooting Star

Adds candlestick pattern features to the dataframe.
"""

from __future__ import annotations

import numpy as np

import pandas as pd

from core.exceptions import IndicatorError
from core.logger import get_logger

logger = get_logger(__name__)


class PatternIndicators:
    """Candlestick pattern engine."""

    def calculate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise IndicatorError("Empty dataframe received.")

        required = {"open", "high", "low", "close"}
        missing = required.difference(dataframe.columns)
        if missing:
            raise IndicatorError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        prev_open = df["open"].shift(1)
        prev_close = df["close"].shift(1)
        prev_high = df["high"].shift(1)
        prev_low = df["low"].shift(1)

        body = (df["close"] - df["open"]).abs()
        candle_range = (df["high"] - df["low"]).replace(0, np.nan)
        upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
        lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]

        df["inside_bar"] = (df["high"] < prev_high) & (df["low"] > prev_low)

        df["outside_bar"] = (df["high"] > prev_high) & (df["low"] < prev_low)

        df["bullish_engulfing"] = (
            (prev_close < prev_open)
            & (df["close"] > df["open"])
            & (df["open"] <= prev_close)
            & (df["close"] >= prev_open)
        )

        df["bearish_engulfing"] = (
            (prev_close > prev_open)
            & (df["close"] < df["open"])
            & (df["open"] >= prev_close)
            & (df["close"] <= prev_open)
        )

        df["doji"] = (body / candle_range) <= 0.10

        df["hammer"] = (lower_shadow >= body * 2) & (upper_shadow <= body)

        df["shooting_star"] = (upper_shadow >= body * 2) & (lower_shadow <= body)

        logger.info("Pattern indicators calculated.")
        return df
