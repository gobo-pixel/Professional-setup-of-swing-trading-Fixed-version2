"""
Fundamental Analysis Engine.

Responsibilities:
- Evaluate company fundamentals
- Generate normalized scores
- No BUY/SELL decisions
- No portfolio logic
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.exceptions import DataError

logger = get_logger(__name__)


class FundamentalEngine:
    """Evaluate fundamental health of a company."""

    DEFAULT_WEIGHTS = {
        "revenue_growth": 15,
        "earnings_growth": 15,
        "roe": 15,
        "pe": 10,
        "pb": 10,
        "peg": 10,
        "debt_to_equity": 10,
        "operating_cashflow": 15,
    }

    def evaluate(self, fundamentals: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluate normalized fundamental metrics.

        Returns:
            Dictionary containing individual scores and overall score.
        """
        if not fundamentals:
            raise DataError("Fundamental data is empty.")

        scores: dict[str, float] = {}

        scores["revenue_growth"] = self._positive(fundamentals.get("revenue_growth"))
        scores["earnings_growth"] = self._positive(fundamentals.get("earnings_growth"))
        scores["roe"] = self._positive(fundamentals.get("roe"))
        scores["pe"] = self._inverse(fundamentals.get("pe"))
        scores["pb"] = self._inverse(fundamentals.get("pb"))
        scores["peg"] = self._inverse(fundamentals.get("peg"))
        scores["debt_to_equity"] = self._inverse(fundamentals.get("debt_to_equity"))
        scores["operating_cashflow"] = self._positive(
            fundamentals.get("operating_cashflow")
        )

        total_weight = sum(self.DEFAULT_WEIGHTS.values())

        overall = (
            sum(scores[key] * self.DEFAULT_WEIGHTS[key] for key in self.DEFAULT_WEIGHTS)
            / total_weight
        )

        logger.info("Fundamental score calculated.")

        return {
            "scores": scores,
            "overall_score": round(overall, 2),
        }

    @staticmethod
    def _positive(value: Any) -> float:
        if value is None:
            return 50.0
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 50.0

        return max(0.0, min(100.0, 50.0 + value * 50.0))

    @staticmethod
    def _inverse(value: Any) -> float:
        if value is None:
            return 50.0
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 50.0

        if value <= 0:
            return 100.0

        score = 100.0 / (1.0 + value / 10.0)
        return max(0.0, min(100.0, score))
