"""
PHASE 2 — MODULE 5: REGRESSION VALIDATION

Compares two BacktestResult metric dicts (baseline "previous version" vs
"current version") across Win Rate, Profit Factor, Drawdown, CAGR,
Expectancy, Sharpe, and trade count — and recommends ROLLBACK, KEEP, or
NEEDS MORE DATA.

Run this after every future feature change, using analytics/backtest_engine.py
to produce both the baseline and current metric sets on the SAME historical
data (so the comparison is apples-to-apples).

Usage:
    from analytics.regression_validator import RegressionValidator
    validator = RegressionValidator()
    verdict = validator.compare(baseline_metrics, current_metrics)
    print(validator.report(verdict))
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.notifications import notify


@dataclass
class MetricComparison:
    name: str
    previous: float
    current: float
    delta: float
    delta_percent: float
    better: bool  # True if current is an improvement over previous


class RegressionValidator:

    # For each metric: whether higher is better, and the minimum
    # meaningful delta (percentage points / ratio units) before we call
    # a change "measurable" rather than noise.
    METRIC_DIRECTIONS = {
        "win_rate": (True, 2.0),        # +2pp
        "profit_factor": (True, 0.1),
        "max_drawdown": (False, 1.0),   # lower is better, 1pp
        "cagr": (True, 1.0),
        "expectancy": (True, 0.5),
        "sharpe": (True, 0.1),
        "sortino": (True, 0.1),
        "avg_rr": (True, 0.1),
        "total_trades": (True, 0.0),    # informational only, not scored
    }

    MIN_TRADES_FOR_VERDICT = 30

    def compare(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        comparisons = {}
        for metric, (higher_is_better, min_delta) in self.METRIC_DIRECTIONS.items():
            prev_val = float(previous.get(metric, 0) or 0)
            curr_val = float(current.get(metric, 0) or 0)
            delta = curr_val - prev_val
            delta_pct = (delta / abs(prev_val) * 100) if prev_val else 0.0

            if metric == "total_trades":
                better = True  # informational
            else:
                meaningful = round(abs(delta), 6) >= min_delta
                better = (delta > 0 if higher_is_better else delta < 0) and meaningful

            comparisons[metric] = MetricComparison(
                name=metric, previous=prev_val, current=curr_val,
                delta=round(delta, 3), delta_percent=round(delta_pct, 2), better=better,
            )

        scored_metrics = [m for name, m in comparisons.items() if name != "total_trades"]
        improved = sum(1 for m in scored_metrics if m.better)
        worsened = sum(
            1 for name, m in comparisons.items()
            if name != "total_trades" and not m.better and round(abs(m.delta), 6) >= self.METRIC_DIRECTIONS[name][1]
        )

        trade_count = current.get("total_trades", 0)
        if trade_count < self.MIN_TRADES_FOR_VERDICT:
            verdict = "NEEDS_MORE_DATA"
            verdict_reason = (
                f"Only {trade_count} trades in the current run — need at least "
                f"{self.MIN_TRADES_FOR_VERDICT} for a statistically meaningful verdict."
            )
        elif worsened > improved:
            verdict = "ROLLBACK"
            verdict_reason = f"{worsened} metric(s) got measurably worse vs {improved} that improved."
        elif improved > 0 and worsened == 0:
            verdict = "KEEP"
            verdict_reason = f"{improved} metric(s) improved with no measurable regressions."
        elif improved > worsened:
            verdict = "KEEP_WITH_TRADEOFFS"
            verdict_reason = (
                f"{improved} metric(s) improved vs {worsened} that got worse — net positive, "
                "but review the regressed metric(s) before fully committing."
            )
        else:
            verdict = "NO_MEASURABLE_CHANGE"
            verdict_reason = "No metric moved by more than its noise threshold — treat as neutral."

        result = {
            "comparisons": comparisons,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "improved_count": improved,
            "worsened_count": worsened,
        }

        if verdict != "NEEDS_MORE_DATA":
            severity_map = {
                "ROLLBACK": "🔴 CRITICAL",
                "KEEP_WITH_TRADEOFFS": "🟡 MEDIUM",
                "NO_MEASURABLE_CHANGE": "🟢 LOW",
                "KEEP": "🟢 LOW",
            }
            notify(
                event_type="regression_result",
                message=f"Regression Result: {verdict}\n{verdict_reason}",
                severity=severity_map.get(verdict, "🟡 MEDIUM"),
                dedup_key=f"regression_result::{time.strftime('%Y-%m-%d')}",
            )

        return result

    def report(self, result: dict[str, Any]) -> str:
        lines = ["=" * 60, "REGRESSION VALIDATION REPORT", "=" * 60, ""]
        lines.append(f"{'Metric':<16}{'Previous':>12}{'Current':>12}{'Delta':>12}  Verdict")
        for name, m in result["comparisons"].items():
            mark = "better" if m.better else "worse/flat"
            lines.append(f"{name:<16}{m.previous:>12.2f}{m.current:>12.2f}{m.delta:>+12.2f}  {mark}")
        lines.append("")
        lines.append(f"FINAL VERDICT: {result['verdict']}")
        lines.append(f"Reason: {result['verdict_reason']}")
        if result["verdict"] == "ROLLBACK":
            lines.append("\n-> Recommend reverting this change, or shipping it with a")
            lines.append("   lower weight/allocation until more data supports it.")
        return "\n".join(lines)


if __name__ == "__main__":
    # Example usage with placeholder numbers.
    baseline = {"win_rate": 52.0, "profit_factor": 1.3, "max_drawdown": 18.0,
                "cagr": 12.0, "expectancy": 0.8, "sharpe": 0.9, "total_trades": 120}
    current = {"win_rate": 55.0, "profit_factor": 1.4, "max_drawdown": 20.0,
               "cagr": 14.0, "expectancy": 1.1, "sharpe": 1.0, "total_trades": 118}
    validator = RegressionValidator()
    print(validator.report(validator.compare(baseline, current)))
