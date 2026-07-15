"""
PHASE 2 — MODULE 3: OPTIMIZER (recommendations only)

Reads the Learning Engine's historical observation log and produces
recommendations: better weights, weak/redundant rules, confidence
adjustments. It NEVER writes to any production config or strategy file —
it only prints/returns a recommendation report for a human to review and
apply manually.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from analytics.learning_engine import LearningEngine
from core.notifications import notify


@dataclass
class Recommendation:
    category: str
    finding: str
    suggestion: str
    confidence: str  # LOW / MEDIUM / HIGH, based on sample size


class Optimizer:

    MIN_SAMPLE_FOR_HIGH_CONFIDENCE = 30
    MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE = 10

    def __init__(self, learning_engine: LearningEngine | None = None):
        self.learning_engine = learning_engine or LearningEngine()

    def _confidence_for_n(self, n: int) -> str:
        if n >= self.MIN_SAMPLE_FOR_HIGH_CONFIDENCE:
            return "HIGH"
        if n >= self.MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE:
            return "MEDIUM"
        return "LOW"

    def recommend(self) -> list[Recommendation]:
        """IMPORTANT: this only returns suggestions. Nothing here is ever
        auto-applied to buy_strategy.py / sell_strategy.py / any weight
        constant. A human reviews these and edits the code manually."""
        history = self.learning_engine.get_history()
        if not history:
            return [Recommendation(
                category="DATA",
                finding="No learning observations recorded yet.",
                suggestion="Run analytics/learning_engine.py after enough closed trades exist "
                           "(recommend at least 30 for statistically meaningful recommendations).",
                confidence="LOW",
            )]

        latest = history[-1]
        recs: list[Recommendation] = []

        recs.extend(self._news_recommendation(latest))
        recs.extend(self._fundamental_recommendation(latest))
        recs.extend(self._technical_recommendation(latest))
        recs.extend(self._sector_recommendation(latest))
        recs.extend(self._regime_recommendation(latest))
        recs.extend(self._accuracy_recommendation(latest))

        return recs

    def _news_recommendation(self, obs: dict) -> list[Recommendation]:
        eff = obs.get("news_effectiveness", {})
        with_wr, without_wr = eff.get("with_news_win_rate"), eff.get("without_news_win_rate")
        if with_wr is None or without_wr is None:
            return []
        diff = with_wr - without_wr
        if abs(diff) < 5:
            return [Recommendation(
                "NEWS", f"News-present win rate ({with_wr}%) vs no-news win rate ({without_wr}%) "
                        f"differ by only {diff:.1f}pp.",
                "News weight (currently ~15-30% of Tier 3) looks roughly right — no change suggested.",
                "MEDIUM",
            )]
        direction = "increasing" if diff > 0 else "decreasing"
        return [Recommendation(
            "NEWS", f"News-present trades win {with_wr}% vs {without_wr}% without news ({diff:+.1f}pp).",
            f"Consider {direction} the news weight in Tier 3 — it appears to carry real signal.",
            "MEDIUM",
        )]

    def _fundamental_recommendation(self, obs: dict) -> list[Recommendation]:
        eff = obs.get("fundamental_effectiveness", {})
        strong, weak = eff.get("strong_fundamentals_win_rate"), eff.get("weak_fundamentals_win_rate")
        if strong is None or weak is None:
            return []
        diff = strong - weak
        return [Recommendation(
            "FUNDAMENTAL",
            f"Strong-fundamental trades win {strong}% vs {weak}% for weak-fundamental trades ({diff:+.1f}pp).",
            "This matches the audit finding: SELL's heavy fundamental_weakness weighting may be "
            "over/under-tuned — cross-check against the Tier-3 rebalance decision from the audit."
            if diff < 10 else
            "Fundamentals appear to carry real predictive signal — current weighting looks reasonable.",
            "MEDIUM",
        )]

    def _technical_recommendation(self, obs: dict) -> list[Recommendation]:
        eff = obs.get("technical_effectiveness", {})
        high, low = eff.get("high_technical_win_rate"), eff.get("low_technical_win_rate")
        if high is None or low is None:
            return []
        diff = high - low
        return [Recommendation(
            "TECHNICAL",
            f"High-Tier2-score trades win {high}% vs {low}% for low-Tier2-score trades ({diff:+.1f}pp).",
            "Technical (Tier 2) weight looks well-calibrated." if diff > 10 else
            "Technical score shows weak correlation with outcome — consider re-examining which "
            "of the 39 checks actually contribute vs just adding noise.",
            "MEDIUM",
        )]

    def _sector_recommendation(self, obs: dict) -> list[Recommendation]:
        perf = obs.get("sector_performance", {})
        recs = []
        for sector, stats in perf.items():
            n = stats.get("trades", 0)
            wr = stats.get("win_rate")
            if wr is None:
                continue
            conf = self._confidence_for_n(n)
            if wr <= 35 and n >= self.MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE:
                recs.append(Recommendation(
                    "SECTOR", f"{sector}: {wr}% win rate over {n} trades.",
                    f"Consider a sector-specific confidence penalty for {sector} "
                    "(this is exactly what Phase 3's Sector Templates would formalize).",
                    conf,
                ))
        return recs

    def _regime_recommendation(self, obs: dict) -> list[Recommendation]:
        perf = obs.get("regime_performance", {})
        recs = []
        for regime, stats in perf.items():
            n = stats.get("trades", 0)
            wr = stats.get("win_rate")
            if wr is None or n < self.MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE:
                continue
            recs.append(Recommendation(
                "REGIME", f"{regime} regime: {wr}% win rate over {n} trades.",
                "Feed this into Phase 3's Dynamic Regime Weights once sample size is HIGH confidence.",
                self._confidence_for_n(n),
            ))
        return recs

    def _accuracy_recommendation(self, obs: dict) -> list[Recommendation]:
        recs = []
        for side in ("buy_accuracy", "sell_accuracy"):
            stats = obs.get(side, {})
            n = stats.get("trades", 0)
            wr = stats.get("win_rate")
            if wr is None:
                continue
            recs.append(Recommendation(
                side.upper().replace("_", " "),
                f"{n} trades, {wr}% win rate.",
                "Below 45% with a decent sample would suggest the qualify threshold is too "
                "loose for this side; above 65% may mean it's too strict and missing volume."
                if n >= self.MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE else
                "Sample too small to recommend a threshold change yet.",
                self._confidence_for_n(n),
            ))
        return recs

    def print_report(self) -> None:
        recs = self.recommend()
        print("=" * 60)
        print("OPTIMIZER RECOMMENDATIONS (review only — nothing auto-applied)")
        print("=" * 60)
        for r in recs:
            print(f"\n[{r.category}] (confidence: {r.confidence})")
            print(f"  Finding    : {r.finding}")
            print(f"  Suggestion : {r.suggestion}")

        actionable = [r for r in recs if r.confidence in ("MEDIUM", "HIGH")]
        if actionable:
            import time
            summary_lines = "\n".join(f"[{r.category}] {r.finding}" for r in actionable)
            notify(
                event_type="optimizer_recommendation",
                message=f"Optimizer Recommendation(s) available (review only):\n{summary_lines}",
                severity="🟡 MEDIUM",
                dedup_key=f"optimizer_recommendation::{time.strftime('%Y-%m-%d')}",
            )


if __name__ == "__main__":
    Optimizer().print_report()
