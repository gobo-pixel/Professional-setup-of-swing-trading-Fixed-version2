"""
Feature Engineering Engine.

Responsibilities:
- Validate market data
- Generate all technical features
- Merge features into a single dataframe
- No BUY/SELL logic
- No scoring
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger
from features.technical_features import TechnicalFeatureEngine
from features.multi_timeframe import MultiTimeframeEngine

logger = get_logger(__name__)


class FeatureEngineeringEngine:
    """Coordinates feature generation."""

    REQUIRED_COLUMNS = (
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    def __init__(
        self,
        technical_engine: TechnicalFeatureEngine | None = None,
        mtf_engine: MultiTimeframeEngine | None = None,
    ) -> None:
        self._technical = technical_engine or TechnicalFeatureEngine()
        self._mtf = mtf_engine or MultiTimeframeEngine()

    def generate(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate all engineered features.

        Args:
            market_data: Normalized OHLCV dataframe.

        Returns:
            DataFrame containing original columns plus engineered features.
        """
        self._validate(market_data)

        logger.info("Generating technical features...")
        df = self._technical.generate(market_data.copy())

        logger.info("Generating multi-timeframe features...")
        df = self._mtf.generate(df)

        logger.info("Feature engineering complete.")

        return df

    def _validate(self, dataframe: pd.DataFrame) -> None:
        if dataframe.empty:
            raise DataError("Market dataframe is empty.")

        missing = [
            column
            for column in self.REQUIRED_COLUMNS
            if column not in dataframe.columns
        ]

        if missing:
            raise DataError(f"Missing required market columns: {missing}")
