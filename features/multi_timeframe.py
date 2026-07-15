"""
Multi-Timeframe Feature Engine.

Responsibilities:
- Generate higher timeframe context from normalized OHLCV data.
- Add derived columns only.
- No strategy, scoring, or decision logic.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class MultiTimeframeEngine:
    """Generate higher-timeframe trend features."""

    def generate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich a dataframe with higher-timeframe features.

        Args:
            dataframe: Normalized OHLCV dataframe.

        Returns:
            DataFrame with additional multi-timeframe columns.
        """
        if dataframe.empty:
            raise DataError(
                "Cannot generate multi-timeframe features from empty dataframe."
            )

        if "close" not in dataframe.columns:
            raise DataError("Required column 'close' is missing.")

        df = dataframe.copy()

        # Higher timeframe trend approximations.
        df["mtf_sma_20"] = df["close"].rolling(20, min_periods=20).mean()
        df["mtf_sma_50"] = df["close"].rolling(50, min_periods=50).mean()
        df["mtf_sma_200"] = df["close"].rolling(200, min_periods=200).mean()

        df["mtf_trend"] = "SIDEWAYS"
        df.loc[
            (df["mtf_sma_20"] > df["mtf_sma_50"])
            & (df["mtf_sma_50"] > df["mtf_sma_200"]),
            "mtf_trend",
        ] = "BULL"

        df.loc[
            (df["mtf_sma_20"] < df["mtf_sma_50"])
            & (df["mtf_sma_50"] < df["mtf_sma_200"]),
            "mtf_trend",
        ] = "BEAR"

        logger.info("Multi-timeframe features generated.")

        return df
