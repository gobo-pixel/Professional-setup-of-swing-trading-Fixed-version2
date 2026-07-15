"""
Ichimoku Cloud Indicators.

Responsibilities:
- Tenkan-sen
- Kijun-sen
- Senkou Span A
- Senkou Span B
- Chikou Span
- Cloud Trend

Adds Ichimoku features to the dataframe.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import IndicatorError
from core.logger import get_logger

logger = get_logger(__name__)


class IchimokuIndicators:
    """Ichimoku Cloud indicator engine."""

    def calculate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise IndicatorError("Empty dataframe received.")

        required = {"high", "low", "close"}
        missing = required.difference(dataframe.columns)
        if missing:
            raise IndicatorError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        high9 = df["high"].rolling(9, min_periods=9).max()
        low9 = df["low"].rolling(9, min_periods=9).min()
        df["tenkan_sen"] = (high9 + low9) / 2

        high26 = df["high"].rolling(26, min_periods=26).max()
        low26 = df["low"].rolling(26, min_periods=26).min()
        df["kijun_sen"] = (high26 + low26) / 2

        df["senkou_span_a"] = ((df["tenkan_sen"] + df["kijun_sen"]) / 2).shift(26)

        high52 = df["high"].rolling(52, min_periods=52).max()
        low52 = df["low"].rolling(52, min_periods=52).min()
        df["senkou_span_b"] = ((high52 + low52) / 2).shift(26)

        df["chikou_span"] = df["close"].shift(-26)

        df["cloud_trend"] = "NEUTRAL"
        bull = df["close"] > df[["senkou_span_a", "senkou_span_b"]].max(axis=1)
        bear = df["close"] < df[["senkou_span_a", "senkou_span_b"]].min(axis=1)
        df.loc[bull, "cloud_trend"] = "BULL"
        df.loc[bear, "cloud_trend"] = "BEAR"

        logger.info("Ichimoku indicators calculated.")
        return df
