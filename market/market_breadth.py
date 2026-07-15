"""
Market Breadth Engine.

Responsibilities:
- Advance/Decline statistics
- Advance/Decline Ratio
- Advance/Decline Line
- New High / New Low counts
- Breadth classification

No strategy or decision logic.
"""

from __future__ import annotations

import numpy as np

import pandas as pd

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class MarketBreadthEngine:
    """Compute market breadth metrics."""

    REQUIRED_COLUMNS = {
        "advance",
        "decline",
        "new_high",
        "new_low",
    }

    def evaluate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise DataError("Breadth dataframe is empty.")

        missing = self.REQUIRED_COLUMNS.difference(dataframe.columns)
        if missing:
            raise DataError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        total = (df["advance"] + df["decline"]).replace(0, np.nan)

        df["ad_ratio"] = df["advance"] / df["decline"].replace(0, np.nan)
        df["ad_percent"] = (df["advance"] / total) * 100
        df["ad_line"] = (df["advance"] - df["decline"]).cumsum()

        df["nh_nl_ratio"] = df["new_high"] / df["new_low"].replace(0, np.nan)

        df["breadth"] = "NEUTRAL"
        df.loc[df["ad_percent"] >= 60, "breadth"] = "STRONG"
        df.loc[df["ad_percent"] <= 40, "breadth"] = "WEAK"

        logger.info("Market breadth calculated.")

        return df
