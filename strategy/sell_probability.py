"""
SELL Probability Engine

Responsibilities
----------------
- Success Probability
- Expected Fall
- Expected Hold Period
- Expected Drawdown
- Confidence Calibration

Consumes:
    SellScore

Produces:
    SellProbability
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from strategy.sell_scoring import SellScore
from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# RESULT MODEL
# ==========================================================


@dataclass(slots=True)
class SellProbability:

    success_probability: float

    expected_fall: float

    expected_hold_days: int

    expected_drawdown: float

    confidence: float


# ==========================================================
# ENGINE
# ==========================================================


class SellProbabilityEngine:
    """
    Converts SELL score into probability estimates.
    """

    def evaluate(
        self,
        score: SellScore,
    ) -> SellProbability:

        probability = self._success_probability(score)

        expected_fall = self._expected_fall(score)

        hold = self._expected_hold(score)

        drawdown = self._expected_drawdown(score)

        confidence = self._confidence(score)

        logger.info(
            "SELL probability %.2f%%",
            probability,
        )

        return SellProbability(
            success_probability=probability,
            expected_fall=expected_fall,
            expected_hold_days=hold,
            expected_drawdown=drawdown,
            confidence=confidence,
        )

    # ==========================================================
    # SUCCESS PROBABILITY
    # ==========================================================

    def _success_probability(
        self,
        score: SellScore,
    ) -> float:

        x = (score.overall - 50) / 10

        probability = 100 / (1 + math.exp(-x))

        return round(
            probability,
            2,
        )

    # ==========================================================
    # EXPECTED FALL
    # ==========================================================

    def _expected_fall(
        self,
        score: SellScore,
    ) -> float:

        probability = self._success_probability(score)

        base_move = (
            score.technical * 0.30
            + score.market * 0.20
            + score.sector * 0.15
            + score.news * 0.10
            + score.fundamental * 0.15
            + score.liquidity * 0.05
            + score.volatility * 0.05
        ) / 100

        expected = base_move * (probability / 100) * 20

        return round(
            expected,
            2,
        )

    # ==========================================================
    # EXPECTED HOLD PERIOD
    # ==========================================================

    def _expected_hold(
        self,
        score: SellScore,
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
        score: SellScore,
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
        score: SellScore,
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
        score: SellScore,
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
        probability: SellProbability,
        score: SellScore,
    ) -> list[str]:

        reasons: list[str] = []

        if probability.success_probability >= 80:
            reasons.append(
                "Historical probability strongly favors a successful SELL trade."
            )

        elif probability.success_probability >= 65:
            reasons.append("Historical probability favors a SELL trade.")

        else:
            reasons.append("Probability advantage is limited.")

        if probability.expected_fall >= 10:
            reasons.append("High downside potential.")

        elif probability.expected_fall >= 5:
            reasons.append("Moderate downside potential.")

        else:
            reasons.append("Limited downside expected.")

        if probability.expected_drawdown <= 3:
            reasons.append("Controlled downside risk.")

        elif probability.expected_drawdown <= 6:
            reasons.append("Acceptable downside risk.")

        else:
            reasons.append("Higher than normal downside risk.")

        if score.market >= 70:
            reasons.append("Overall market supports bearish trades.")

        if score.sector >= 70:
            reasons.append("Sector weakness supports the setup.")

        if score.news >= 70:
            reasons.append("Negative news flow increases conviction.")

        return reasons

    # ==========================================================
    # EXPORT
    # ==========================================================

    @staticmethod
    def to_dict(
        probability: SellProbability,
    ) -> dict:

        return {
            "success_probability": probability.success_probability,
            "expected_fall": probability.expected_fall,
            "expected_hold_days": probability.expected_hold_days,
            "expected_drawdown": probability.expected_drawdown,
            "confidence": probability.confidence,
        }


# ==========================================================
# END OF FILE
# ==========================================================
