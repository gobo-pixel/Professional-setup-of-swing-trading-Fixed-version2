"""
Market Regime Engine.

Responsibilities:
- Classify overall market regime
- Detect volatility state
- Detect gap day
- No strategy or scoring logic
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class MarketRegimeEngine:
    """Determine the current market regime."""

    REQUIRED_COLUMNS = {
        "open",
        "high",
        "low",
        "close",
        "atr_14",
        "ema_50",
        "ema_200",
    }

    def evaluate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise DataError("Empty dataframe received.")

        missing = self.REQUIRED_COLUMNS.difference(dataframe.columns)
        if missing:
            raise DataError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        df["market_regime"] = "SIDEWAYS"

        bull = (df["close"] > df["ema_50"]) & (df["ema_50"] > df["ema_200"])

        bear = (df["close"] < df["ema_50"]) & (df["ema_50"] < df["ema_200"])

        df.loc[bull, "market_regime"] = "BULL"
        df.loc[bear, "market_regime"] = "BEAR"

        atr_ma = df["atr_14"].rolling(20, min_periods=20).mean()

        df["volatility_regime"] = "NORMAL"
        df.loc[df["atr_14"] > atr_ma * 1.20, "volatility_regime"] = "HIGH"
        df.loc[df["atr_14"] < atr_ma * 0.80, "volatility_regime"] = "LOW"

        prev_close = df["close"].shift(1)
        gap = ((df["open"] - prev_close) / prev_close) * 100

        df["gap_day"] = gap.abs() >= 1.0

        logger.info("Market regime evaluated.")

        return df
