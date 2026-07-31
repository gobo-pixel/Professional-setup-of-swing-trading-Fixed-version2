"""
DIAGNOSTIC - Before/After Confidence and Probability for the News=100 bug.

Read-only, evidence-only calculator. Does NOT touch any strategy code.
Uses the EXACT production formulas (copied verbatim, not reimplemented
differently) from:
  - strategy/buy_scoring.py   -> BuyScoringEngine._confidence()
  - strategy/buy_probability.py -> BuyProbabilityEngine._win_probability()

IMPORTANT LIMITATION (by design, not an oversight):
Confidence is computed from 8 raw components: technical, fundamental,
news, market, sector, liquidity, volatility, risk. Only technical,
fundamental, and news are persisted in reports/full_report.csv - the
other 5 (market/sector/liquidity/volatility/risk) are never written
anywhere accessible after a scan completes. This script uses the 3
available components plus a labeled approximation for the missing 5
(each assumed equal to OverallScore, the closest available proxy for
"what the rest of the profile looks like"). Treat the Confidence
numbers as directionally indicative, not exact - the Probability
numbers (which depend only on OverallScore) ARE exact.

Usage:
    Edit the STOCKS list below with rows of:
        (symbol, signal, overall_score, technical_score, fundamental_score)
    then run:
        python scripts/diagnose_confidence_probability_impact.py
"""

from __future__ import annotations

import math
import statistics

NEWS_WEIGHT = 0.10
NEWS_BEFORE = 100.0   # proven: always 100.0 under the current bug
NEWS_AFTER_WORST = 0.0  # worst case: news was actually fully negative

# Fill in rows as: (symbol, signal, overall_score, technical_score, fundamental_score)
# overall_score / technical_score / fundamental_score come straight from
# full_report.csv's OverallScore / TechnicalScore / FundamentalScore columns.
STOCKS: list[tuple[str, str, float, float, float]] = [
    ("DATAPATTNS.NS", "BUY", 67.8, 75.0, 48.67),
    ("NUVAMA.NS", "BUY", 69.49, 70.0, 43.27),
    ("CROMPTON.NS", "SELL", 70.17, 95.0, 40.5),
    ("ANANDRATHI.NS", "BUY", 62.7, 65.0, 43.0),
    # ... jitни bhi chahiए utni add karo
]


def _win_probability(overall_score: float) -> float:
    """Verbatim from strategy/buy_probability.py's _win_probability()."""
    x = (overall_score - 50) / 10
    return round(100 / (1 + math.exp(-x)), 2)


def _confidence(technical: float, fundamental: float, news: float, proxy_for_rest: float) -> float:
    """Verbatim structure from strategy/buy_scoring.py's _confidence().
    market/sector/liquidity/volatility/risk are approximated with
    `proxy_for_rest` (see module docstring for why)."""
    values = [technical, fundamental, news] + [proxy_for_rest] * 5
    mean = statistics.mean(values)
    consistency = 100 - statistics.pstdev(values)
    confidence = mean * 0.60 + consistency * 0.40
    return round(max(0.0, min(confidence, 100.0)), 2)


def main() -> None:
    if not STOCKS:
        print("STOCKS list is empty - edit this file and add rows, then re-run.")
        return

    print(f"{'Symbol':<15}{'Sig':<6}{'Overall(B->W)':<16}{'Prob(B->W)':<18}{'Confidence(B->W, approx)':<28}")
    print("-" * 85)

    for symbol, signal, overall, technical, fundamental in STOCKS:
        overall_worst = overall - NEWS_BEFORE * NEWS_WEIGHT + NEWS_AFTER_WORST * NEWS_WEIGHT

        prob_before = _win_probability(overall)
        prob_worst = _win_probability(overall_worst)

        conf_before = _confidence(technical, fundamental, NEWS_BEFORE, overall)
        conf_worst = _confidence(technical, fundamental, NEWS_AFTER_WORST, overall_worst)

        print(
            f"{symbol:<15}{signal:<6}"
            f"{f'{overall}->{overall_worst:.2f}':<16}"
            f"{f'{prob_before}%->{prob_worst}%':<18}"
            f"{f'{conf_before}->{conf_worst} (approx)':<28}"
        )


if __name__ == "__main__":
    main()
