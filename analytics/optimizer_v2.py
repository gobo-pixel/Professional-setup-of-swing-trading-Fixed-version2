"""
PHASE 2 — MODULE 3: OPTIMIZER (recommendations only)

Reads the Learning Engine's historical observation log and produces
recommendations: better weights, weak/redundant rules, confidence
adjustments. It NEVER writes to any production config or strategy file —
it only prints/returns a recommendation report for a human to review and
apply manually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from analytics.learning_engine import LearningEngine


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
        recs.extend(self._rule_effectiveness_recommendation(latest))
        recs.extend(self._redundant_rule_recommendation(latest))
        recs.extend(self._threshold_recommendation(latest))
        recs.extend(self._sector_recommendation(latest))
        recs.extend(self._regime_recommendation(latest))
        recs.extend(self._accuracy_recommendation(latest))

        return recs

    def _rule_effectiveness_recommendation(self, obs: dict) -> list[Recommendation]:
        """Flags individual rules whose pass/fail differential is weak
        or backwards (rule passing correlates with LOSING, not
        winning) — genuine per-rule granularity, not just the aggregate
        technical score used by _technical_recommendation above."""
        rules = obs.get("rule_effectiveness", {})
        recs = []
        for rule_name, stats in rules.items():
            diff = stats.get("differential")
            n_total = stats.get("sample_passed", 0) + stats.get("sample_failed", 0)
            if diff is None or n_total < self.MIN_SAMPLE_FOR_MEDIUM_CONFIDENCE:
                continue
            if diff < 0:
                recs.append(Recommendation(
                    "RULE (weak/backwards)",
                    f"'{rule_name}': passing this rule wins {stats['win_rate_when_passed']}% vs "
                    f"{stats['win_rate_when_failed']}% when it fails ({diff:+.1f}pp) — backwards.",
                    "Re-examine this rule's logic/direction — it currently correlates with losses, "
                    "not wins.",
                    self._confidence_for_n(n_total),
                ))
            elif diff < 5:
                recs.append(Recommendation(
                    "RULE (weak)",
                    f"'{rule_name}': only {diff:+.1f}pp win-rate difference between passing and failing.",
                    "Weak predictive value — candidate for removal or re-weighting.",
                    self._confidence_for_n(n_total),
                ))
        return recs

    def _redundant_rule_recommendation(self, obs: dict) -> list[Recommendation]:
        """Uses LearningEngine's pairwise agreement-rate analysis to
        flag rules that nearly always agree with another rule — little
        marginal signal beyond one another."""
        pairs = obs.get("redundant_rule_pairs", [])
        recs = []
        for pair in pairs[:5]:  # cap noise — only the strongest redundancies
            recs.append(Recommendation(
                "RULE (redundant)",
                f"'{pair['rule_a']}' and '{pair['rule_b']}' agree {pair['agreement_rate']}% of the "
                f"time (n={pair['sample_size']}).",
                "These two rules likely measure the same thing — consider dropping one to "
                "simplify the checklist without losing signal.",
                self._confidence_for_n(pair["sample_size"]),
            ))
        return recs

    def _threshold_recommendation(self, obs: dict) -> list[Recommendation]:
        """Uses the margin-band win-rate data from LearningEngine to
        give a SPECIFIC, evidence-based threshold suggestion, instead
        of the generic accuracy-based note in _accuracy_recommendation."""
        bands = obs.get("threshold_sensitivity", {})
        near = bands.get("0-5", {})
        far = bands.get("20+", {})
        near_wr, far_wr = near.get("win_rate"), far.get("win_rate")
        near_n, far_n = near.get("trades", 0), far.get("trades", 0)

        if near_wr is None or far_wr is None or near_n < 5 or far_n < 5:
            return []

        diff = far_wr - near_wr
        n_total = near_n + far_n
        if diff >= 15:
            return [Recommendation(
                "THRESHOLD",
                f"Trades that barely passed (margin 0-5pts, n={near_n}) win {near_wr}% vs "
                f"{far_wr}% for comfortable passes (margin 20+pts, n={far_n}).",
                "Raise the qualify threshold — near-threshold passes are meaningfully weaker "
                "than confident ones, suggesting the current cutoff lets in too many marginal trades.",
                self._confidence_for_n(n_total),
            )]
        return [Recommendation(
            "THRESHOLD",
            f"Near-threshold win rate ({near_wr}%, n={near_n}) is close to comfortable-pass "
            f"win rate ({far_wr}%, n={far_n}).",
            "Current threshold looks reasonably well-calibrated — no adjustment indicated yet.",
            self._confidence_for_n(n_total),
        )]

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


if __name__ == "__main__":
    Optimizer().print_report()
