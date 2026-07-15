"""
Sentiment Engine.

Responsibilities:
- Score news sentiment
- Assign confidence
- Compute impact score
- Apply time decay

No BUY/SELL decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


class SentimentEngine:
    POSITIVE = {
        "beat",
        "growth",
        "upgrade",
        "buyback",
        "record",
        "profit",
        "expansion",
        "contract",
        "approval",
        "surge",
        "strong",
        "award",
    }

    NEGATIVE = {
        "miss",
        "downgrade",
        "fraud",
        "loss",
        "litigation",
        "sebi",
        "penalty",
        "fall",
        "decline",
        "weak",
        "recall",
        "bankruptcy",
    }

    def evaluate(self, news: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for item in news:
            title = str(item.get("title", ""))
            sentiment, score = self._sentiment(title)
            decay = self._decay(item.get("published_at"))

            impact = round(score * decay, 2)

            results.append(
                {
                    **item,
                    "sentiment": sentiment,
                    "confidence": abs(score),
                    "impact_score": impact,
                    "event_weight": impact,
                    "decay_factor": round(decay, 3),
                }
            )

        logger.info("Processed sentiment for %d news items.", len(results))
        return results

    def _sentiment(self, text: str) -> tuple[str, float]:
        text = text.lower()

        pos = sum(word in text for word in self.POSITIVE)
        neg = sum(word in text for word in self.NEGATIVE)

        if pos > neg:
            return "POSITIVE", min(100.0, 50.0 + pos * 15.0)
        if neg > pos:
            return "NEGATIVE", min(100.0, 50.0 + neg * 15.0)
        return "NEUTRAL", 50.0

    def _decay(self, published_at: Any) -> float:
        if not published_at:
            return 1.0

        try:
            dt = datetime.fromisoformat(str(published_at))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = max(
                0.0,
                (datetime.now(timezone.utc) - dt).total_seconds() / 86400,
            )
        except Exception:
            return 1.0

        return max(0.2, 1.0 - age_days / 30.0)
