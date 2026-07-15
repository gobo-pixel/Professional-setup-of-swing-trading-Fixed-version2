"""
Technical Feature Engine.

Responsibilities:
- Execute all indicator groups
- Merge indicator outputs
- No strategy/risk/decision logic
"""

from __future__ import annotations

import pandas as pd

from core.logger import get_logger
from features.indicators.moving_average import MovingAverageIndicators
from features.indicators.momentum import MomentumIndicators
from features.indicators.volatility import VolatilityIndicators
from features.indicators.volume import VolumeIndicators
from features.indicators.breakout import BreakoutIndicators
from features.indicators.ichimoku import IchimokuIndicators
from features.indicators.pattern import PatternIndicators

logger = get_logger(__name__)


class TechnicalFeatureEngine:
    """Generate technical indicator features."""

    def __init__(self) -> None:
        self._engines = (
            MovingAverageIndicators(),
            MomentumIndicators(),
            VolatilityIndicators(),
            VolumeIndicators(),
            BreakoutIndicators(),
            IchimokuIndicators(),
            PatternIndicators(),
        )

    def generate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Execute all technical indicator engines.

        Args:
            dataframe: Normalized OHLCV dataframe.

        Returns:
            DataFrame with technical features added.
        """
        df = dataframe.copy()

        for engine in self._engines:
            logger.info("Running %s", engine.__class__.__name__)
            df = engine.calculate(df)

        return df
