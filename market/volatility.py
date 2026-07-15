"""
Market Volatility Engine.

Responsibilities:
- Historical Volatility
- ATR Regime
- Volatility Percentile
- Volatility State

No strategy or decision logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class MarketVolatilityEngine:
    """Analyze market volatility."""

    REQUIRED_COLUMNS = {"close", "atr_14"}

    def evaluate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise DataError("Empty dataframe received.")

        missing = self.REQUIRED_COLUMNS.difference(dataframe.columns)
        if missing:
            raise DataError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        returns = np.log(df["close"] / df["close"].shift(1))
        df["historical_volatility"] = returns.rolling(
            20, min_periods=20
        ).std() * np.sqrt(252)

        atr_mean = df["atr_14"].rolling(50, min_periods=50).mean()
        df["atr_ratio"] = df["atr_14"] / atr_mean

        df["volatility_percentile"] = (
            df["historical_volatility"].rolling(252, min_periods=20).rank(pct=True)
            * 100
        )

        df["volatility_state"] = "NORMAL"
        df.loc[df["atr_ratio"] >= 1.20, "volatility_state"] = "HIGH"
        df.loc[df["atr_ratio"] <= 0.80, "volatility_state"] = "LOW"

        logger.info("Market volatility evaluated.")

        return df
