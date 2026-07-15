"""
BUY Probability Engine

Responsibilities
----------------
- Win Probability
- Expected Return
- Expected Hold Period
- Expected Drawdown
- Confidence Calibration

Consumes:
    BuyScore

Produces:
    BuyProbability
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from strategy.buy_scoring import BuyScore
from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# RESULT MODEL
# ==========================================================


@dataclass(slots=True)
class BuyProbability:

    win_probability: float

    expected_return: float

    expected_hold_days: int

    expected_drawdown: float

    confidence: float


# ==========================================================
# ENGINE
# ==========================================================


class BuyProbabilityEngine:
    """
    Converts BUY score into probability estimates.
    """

    def evaluate(
        self,
        score: BuyScore,
    ) -> BuyProbability:

        probability = self._win_probability(score)

        expected_return = self._expected_return(score)

        hold = self._expected_hold(score)

        drawdown = self._expected_drawdown(score)

        confidence = self._confidence(score)

        logger.info(
            "BUY probability %.2f%%",
            probability,
        )

        return BuyProbability(
            win_probability=probability,
            expected_return=expected_return,
            expected_hold_days=hold,
            expected_drawdown=drawdown,
            confidence=confidence,
        )

    # ==========================================================
    # WIN PROBABILITY
    # ==========================================================

    def _win_probability(
        self,
        score: BuyScore,
    ) -> float:

        x = (score.overall - 50) / 10

        probability = 100 / (1 + math.exp(-x))

        return round(
            probability,
            2,
        )

    # ==========================================================
    # EXPECTED RETURN
    # ==========================================================

    def _expected_return(
        self,
        score: BuyScore,
    ) -> float:

        probability = self._win_probability(score)

        base_return = (
            score.technical * 0.30
            + score.market * 0.20
            + score.sector * 0.15
            + score.news * 0.10
            + score.fundamental * 0.15
            + score.liquidity * 0.05
            + score.volatility * 0.05
        ) / 100

        expected = base_return * (probability / 100) * 20

        return round(
            expected,
            2,
        )

    # ==========================================================
    # EXPECTED HOLD PERIOD
    # ==========================================================

    def _expected_hold(
        self,
        score: BuyScore,
    ) -> int:

        overall = score.overall

        if overall >= 90:
            return 30

        if overall >= 80:
            return 20

        if overall >= 70:
            return 15

        if overall >= 60:
            return 10

        return 5

    # ==========================================================
    # EXPECTED DRAWDOWN
    # ==========================================================

    def _expected_drawdown(
        self,
        score: BuyScore,
    ) -> float:

        risk = score.risk

        volatility = score.volatility

        drawdown = (100 - risk) * 0.08 + volatility * 0.03

        drawdown = max(
            drawdown,
            1.0,
        )

        return round(
            drawdown,
            2,
        )

    # ==========================================================
    # CONFIDENCE
    # ==========================================================

    def _confidence(
        self,
        score: BuyScore,
    ) -> float:

        weights = {
            "technical": 0.30,
            "fundamental": 0.15,
            "news": 0.10,
            "market": 0.10,
            "sector": 0.10,
            "liquidity": 0.05,
            "volatility": 0.05,
            "risk": 0.15,
        }

        confidence = (
            score.technical * weights["technical"]
            + score.fundamental * weights["fundamental"]
            + score.news * weights["news"]
            + score.market * weights["market"]
            + score.sector * weights["sector"]
            + score.liquidity * weights["liquidity"]
            + score.volatility * weights["volatility"]
            + score.risk * weights["risk"]
        )

        return round(
            max(
                0.0,
                min(
                    confidence,
                    100.0,
                ),
            ),
            2,
        )

    # ==========================================================
    # PROBABILITY BAND
    # ==========================================================

    def probability_band(
        self,
        probability: float,
    ) -> str:

        if probability >= 90:
            return "VERY_HIGH"

        if probability >= 80:
            return "HIGH"

        if probability >= 65:
            return "MODERATE"

        if probability >= 50:
            return "LOW"

        return "VERY_LOW"

    # ==========================================================
    # RISK CLASSIFICATION
    # ==========================================================

    def risk_level(
        self,
        score: BuyScore,
    ) -> str:

        if score.risk >= 85:
            return "LOW"

        if score.risk >= 70:
            return "MODERATE"

        if score.risk >= 50:
            return "HIGH"

        return "EXTREME"

    # ==========================================================
    # EXPLANATION GENERATOR
    # ==========================================================

    def explanation(
        self,
        probability: BuyProbability,
        score: BuyScore,
    ) -> list[str]:

        reasons: list[str] = []

        if probability.win_probability >= 80:
            reasons.append(
                "Historical probability strongly favors a successful BUY trade."
            )

        elif probability.win_probability >= 65:
            reasons.append("Historical probability favors a BUY trade.")

        else:
            reasons.append("Probability advantage is limited.")

        if probability.expected_return >= 10:
            reasons.append("High expected return.")

        elif probability.expected_return >= 5:
            reasons.append("Moderate expected return.")

        else:
            reasons.append("Limited upside expected.")

        if probability.expected_drawdown <= 3:
            reasons.append("Low expected drawdown.")

        elif probability.expected_drawdown <= 6:
            reasons.append("Acceptable drawdown.")

        else:
            reasons.append("Higher than normal drawdown risk.")

        if score.market >= 70:
            reasons.append("Market environment supports long trades.")

        if score.sector >= 70:
            reasons.append("Sector strength supports the setup.")

        if score.news >= 70:
            reasons.append("Positive news flow improves conviction.")

        return reasons

    # ==========================================================
    # EXPORT
    # ==========================================================

    @staticmethod
    def to_dict(
        probability: BuyProbability,
    ) -> dict:

        return {
            "win_probability": probability.win_probability,
            "expected_return": probability.expected_return,
            "expected_hold_days": probability.expected_hold_days,
            "expected_drawdown": probability.expected_drawdown,
            "confidence": probability.confidence,
        }


# ==========================================================
# END OF FILE
# ==========================================================
