"""
SELL Scoring Engine

Professional Production Version

Responsibilities
----------------
- Technical Score
- Fundamental Score
- News Score
- Market Score
- Sector Score
- Liquidity Score
- Volatility Score
- Risk Score
- Overall SELL Score
- Confidence
- Reasons
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core.logger import get_logger
from core.exceptions import StrategyError
from strategy.fundamental_scoring import sell_fundamental_score

logger = get_logger(__name__)


# ==========================================================
# CONFIGURATION
# ==========================================================

TECHNICAL_WEIGHT = 0.35
FUNDAMENTAL_WEIGHT = 0.15
NEWS_WEIGHT = 0.10
MARKET_WEIGHT = 0.10
SECTOR_WEIGHT = 0.10
LIQUIDITY_WEIGHT = 0.05
VOLATILITY_WEIGHT = 0.05
RISK_WEIGHT = 0.10

MAX_SCORE = 100.0


# ==========================================================
# RESULT MODEL
# ==========================================================


@dataclass(slots=True)
class SellScore:

    technical: float = 0.0

    fundamental: float = 0.0

    news: float = 0.0

    market: float = 0.0

    sector: float = 0.0

    liquidity: float = 0.0

    volatility: float = 0.0

    risk: float = 0.0

    overall: float = 0.0

    confidence: float = 0.0

    reasons: list[str] = field(default_factory=list)


# ==========================================================
# ENGINE
# ==========================================================


class SellScoringEngine:
    """
    Calculates the complete SELL score.
    """

    def score(
        self,
        dataframe: pd.DataFrame,
        fundamentals: dict[str, Any],
        news_score: float | None,
        market_score: float,
        sector_score: float,
    ) -> SellScore:

        if dataframe.empty:
            raise StrategyError("Empty dataframe.")

        latest = dataframe.iloc[-1]

        result = SellScore()

        result.technical = self._technical_score(latest)

        result.fundamental = self._fundamental_score(fundamentals)

        has_news = news_score is not None
        result.news = self._normalize(news_score) if has_news else 0.0

        result.market = self._normalize(market_score)

        result.sector = self._normalize(sector_score)

        result.liquidity = self._liquidity_score(latest)

        result.volatility = self._volatility_score(latest)

        result.risk = self._risk_score(latest)

        scale = 1.0 if has_news else 1.0 / (1.0 - NEWS_WEIGHT)
        news_w = NEWS_WEIGHT if has_news else 0.0

        result.overall = (
            result.technical * TECHNICAL_WEIGHT * scale
            + result.fundamental * FUNDAMENTAL_WEIGHT * scale
            + result.news * news_w
            + result.market * MARKET_WEIGHT * scale
            + result.sector * SECTOR_WEIGHT * scale
            + result.liquidity * LIQUIDITY_WEIGHT * scale
            + result.volatility * VOLATILITY_WEIGHT * scale
            + result.risk * RISK_WEIGHT * scale
        )

        result.overall = round(result.overall, 2)

        result.confidence = self._confidence(result)

        result.reasons = self._reason_generator(
            latest,
            result,
        )

        logger.info(
            "SELL SCORE = %.2f",
            result.overall,
        )

        return result

    # ==========================================================
    # TECHNICAL SCORE
    # ==========================================================

    def _technical_score(
        self,
        row: pd.Series,
    ) -> float:

        score = 0.0

        max_points = 22  # CONFIRMED BUG FIX: this method awards up to 22
        # raw points (14 checks totaling 22, including the Ichimoku
        # cloud_trend check below) but was dividing by 20 — proven via
        # direct test to let the final score reach 110.0 (all-bearish
        # inputs), uncapped, since result.technical = self._technical_score(...)
        # is assigned directly without going through _normalize(). The
        # BUY-side equivalent has no Ichimoku check in its technical
        # score (14 checks totaling 20 points) so its max_points=20 is
        # correctly calibrated and does not need this fix.
        # --------------------------------------------------
        # EMA Trend
        # --------------------------------------------------

        if row["ema_20"] < row["ema_50"]:
            score += 2

        if row["ema_50"] < row["ema_200"]:
            score += 2

        # --------------------------------------------------
        # SMA Trend
        # --------------------------------------------------

        if row["sma_20"] < row["sma_50"]:
            score += 1

        if row["sma_50"] < row["sma_200"]:
            score += 1

        # --------------------------------------------------
        # RSI
        # --------------------------------------------------

        rsi = row["rsi_14"]

        if 30 <= rsi <= 45:
            score += 2

        elif 45 < rsi <= 55:
            score += 1

        elif rsi < 30:
            score += 1

        # --------------------------------------------------
        # MACD
        # --------------------------------------------------

        if row["macd"] < row["macd_signal"]:
            score += 2

        if row["macd_histogram"] < 0:
            score += 1

        # --------------------------------------------------
        # Volume
        # --------------------------------------------------

        if row["volume"] > row["volume_sma_20"]:
            score += 2

        # --------------------------------------------------
        # VWAP
        # --------------------------------------------------

        if row["close"] < row["vwap"]:
            score += 1

        # --------------------------------------------------
        # OBV
        # --------------------------------------------------

        if row["obv"] < 0:
            score += 1

        # --------------------------------------------------
        # CMF
        # --------------------------------------------------

        if row["cmf_20"] < 0:
            score += 1

        # --------------------------------------------------
        # Bollinger
        # --------------------------------------------------

        if row["close"] < row["bb_middle"]:
            score += 1

        # --------------------------------------------------
        # Breakdown
        # --------------------------------------------------

        if row["is_breakdown"]:
            score += 2

        # --------------------------------------------------
        # Failed Breakout
        # --------------------------------------------------

        if row.get("failed_breakout", False):
            score += 1

        # --------------------------------------------------
        # Ichimoku
        # --------------------------------------------------

        if row.get("cloud_trend") == "BEAR":
            score += 2

        return round(
            (score / max_points) * 100,
            2,
        )

    # ==========================================================
    # FUNDAMENTAL SCORE
    # ==========================================================

    def _fundamental_score(
        self,
        fundamentals: dict[str, Any],
    ) -> float:
        return sell_fundamental_score(fundamentals)

    # ==========================================================
    # LIQUIDITY SCORE
    # ==========================================================

    def _liquidity_score(
        self,
        row: pd.Series,
    ) -> float:

        score = 0.0

        volume = float(row.get("volume", 0))
        avg_volume = float(row.get("volume_sma_20", 0))

        if avg_volume <= 0:
            return 50.0

        ratio = volume / avg_volume

        if ratio >= 2.00:
            score = 100

        elif ratio >= 1.50:
            score = 90

        elif ratio >= 1.20:
            score = 80

        elif ratio >= 1.00:
            score = 70

        elif ratio >= 0.80:
            score = 55

        else:
            score = 35

        return round(score, 2)

    # ==========================================================
    # VOLATILITY SCORE
    # ==========================================================

    def _volatility_score(
        self,
        row: pd.Series,
    ) -> float:

        atr = float(row.get("atr_14", 0))
        bb_width = float(row.get("bb_width", 0))

        score = 50.0

        # Higher volatility favors SELL opportunities
        if atr >= 3:
            score += 15

        elif atr >= 2:
            score += 10

        elif atr >= 1:
            score += 5

        if bb_width >= 0.30:
            score += 15

        elif bb_width >= 0.20:
            score += 10

        elif bb_width >= 0.10:
            score += 5

        return min(
            round(score, 2),
            100.0,
        )

    # ==========================================================
    # RISK SCORE
    # ==========================================================

    def _risk_score(
        self,
        row: pd.Series,
    ) -> float:

        score = 100.0

        if row.get("gap_up", False):
            score -= 25

        if row.get("market_regime") == "BULL":
            score -= 25

        if row.get("cloud_trend") == "BULL":
            score -= 20

        if row.get("rsi_14", 50) < 20:
            score -= 10

        if row.get("volume", 0) < row.get(
            "volume_sma_20",
            0,
        ):
            score -= 5

        return max(
            round(score, 2),
            0.0,
        )

    # ==========================================================
    # CONFIDENCE
    # ==========================================================

    def _confidence(
        self,
        result: SellScore,
    ) -> float:

        values = np.array(
            [
                result.technical,
                result.fundamental,
                result.news,
                result.market,
                result.sector,
                result.liquidity,
                result.volatility,
                result.risk,
            ],
            dtype=float,
        )

        mean = values.mean()

        consistency = 100 - values.std()

        confidence = mean * 0.60 + consistency * 0.40

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
    # REASON GENERATOR
    # ==========================================================

    def _reason_generator(
        self,
        row: pd.Series,
        result: SellScore,
    ) -> list[str]:

        reasons: list[str] = []

        # ---------- Trend ----------
        if row.get("ema_20", 0) < row.get("ema_50", 0):
            reasons.append("EMA20 is below EMA50 (short-term downtrend).")

        if row.get("ema_50", 0) < row.get("ema_200", 0):
            reasons.append("EMA50 is below EMA200 (long-term bearish trend).")

        # ---------- Momentum ----------
        if row.get("macd", 0) < row.get("macd_signal", 0):
            reasons.append("MACD bearish crossover.")

        rsi = row.get("rsi_14", 50)

        if 30 <= rsi <= 45:
            reasons.append("RSI indicates bearish momentum.")

        elif rsi < 30:
            reasons.append("RSI is oversold. Watch for possible bounce.")

        # ---------- Breakdown ----------
        if row.get("is_breakdown", False):
            reasons.append("Price breakdown confirmed.")

        if row.get("failed_breakout", False):
            reasons.append("Failed breakout detected.")

        # ---------- Ichimoku ----------
        if row.get("cloud_trend") == "BEAR":
            reasons.append("Price is below Ichimoku Cloud.")

        # ---------- Volume ----------
        if row.get("volume", 0) > row.get("volume_sma_20", 0):
            reasons.append("High selling volume detected.")

        # ---------- VWAP ----------
        if row.get("close", 0) < row.get("vwap", 0):
            reasons.append("Price trading below VWAP.")

        # ---------- Market ----------
        if row.get("market_regime") == "BEAR":
            reasons.append("Overall market regime is bearish.")

        # ---------- Risk ----------
        if result.risk < 60:
            reasons.append("High downside risk environment.")

        # ---------- Overall ----------
        if result.overall >= 85:
            reasons.append("Excellent SELL setup.")

        elif result.overall >= 70:
            reasons.append("Strong SELL setup.")

        elif result.overall >= 55:
            reasons.append("Moderate SELL setup.")

        else:
            reasons.append("Weak SELL setup.")

        return reasons

    # ==========================================================
    # UTILITIES
    # ==========================================================

    @staticmethod
    def _normalize(value: Any) -> float:

        try:
            value = float(value)
        except (TypeError, ValueError):
            return 50.0

        return max(0.0, min(100.0, value))

    # ==========================================================
    # PUBLIC SUMMARY
    # ==========================================================

    @staticmethod
    def to_dict(result: SellScore) -> dict[str, Any]:

        return {
            "technical": result.technical,
            "fundamental": result.fundamental,
            "news": result.news,
            "market": result.market,
            "sector": result.sector,
            "liquidity": result.liquidity,
            "volatility": result.volatility,
            "risk": result.risk,
            "overall": result.overall,
            "confidence": result.confidence,
            "reasons": result.reasons,
        }


# ==========================================================
# END OF FILE
# ==================================================
