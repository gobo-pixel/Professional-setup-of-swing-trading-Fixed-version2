"""
Sector Rotation Engine.

Responsibilities:
- Rank sectors
- Calculate sector momentum
- Classify leaders and laggards
- Compute rotation score

Input:
    DataFrame indexed by date with one column per sector ETF/index
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class SectorRotationEngine:
    """Analyze sector strength and rotation."""

    def evaluate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise DataError("Sector dataframe is empty.")

        returns = dataframe.pct_change(20)

        latest = returns.iloc[-1].dropna()

        ranking = latest.sort_values(ascending=False).rename("momentum").to_frame()

        ranking["rank"] = range(1, len(ranking) + 1)

        top_n = max(1, len(ranking) // 5)

        ranking["leader"] = False
        ranking["laggard"] = False

        ranking.iloc[:top_n, ranking.columns.get_loc("leader")] = True
        ranking.iloc[-top_n:, ranking.columns.get_loc("laggard")] = True

        max_m = ranking["momentum"].max()
        min_m = ranking["momentum"].min()

        if max_m == min_m:
            ranking["rotation_score"] = 50.0
        else:
            ranking["rotation_score"] = (
                (ranking["momentum"] - min_m) / (max_m - min_m)
            ) * 100

        logger.info("Sector rotation calculated.")

        return ranking
