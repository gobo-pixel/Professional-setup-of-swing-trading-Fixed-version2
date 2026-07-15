"""
FUNDAMENTAL SCORING (shared)

A single, weighted, bidirectional fundamental health score used across
buy_strategy / sell_strategy / buy_scoring / sell_scoring, instead of each
file duplicating its own all-or-nothing AND condition.

buy_fundamental_score(): 0-100, higher = more BUY-favorable (healthy company)
sell_fundamental_score(): 0-100, higher = more SELL-favorable (weak company)

sell_fundamental_score() is simply 100 - buy_fundamental_score() variant
tuned around the same metrics, so "strong fundamentals" and "weak
fundamentals" are always mirror images of each other rather than two
independently-tuned (and potentially inconsistent) rule sets.
"""

from __future__ import annotations

from typing import Any


def _safe_float(fundamentals: dict[str, Any], key: str, default: float) -> float:
    value = fundamentals.get(key)
    return float(value) if value is not None else default


def buy_fundamental_score(fundamentals: dict[str, Any]) -> float:
    """0-100 weighted fundamental health score. No single missing/weak
    metric can zero out the score — each contributes its own weight."""

    revenue = _safe_float(fundamentals, "revenue_growth", 0.0)
    earnings = _safe_float(fundamentals, "earnings_growth", 0.0)
    roe = _safe_float(fundamentals, "roe", 0.0)
    pe = _safe_float(fundamentals, "pe", 999.0)
    pb = _safe_float(fundamentals, "pb", 999.0)
    peg = _safe_float(fundamentals, "peg", 999.0)
    debt = _safe_float(fundamentals, "debt_to_equity", 999.0)
    cash = _safe_float(fundamentals, "operating_cashflow", 0.0)

    weights = {
        "revenue": 15, "earnings": 15, "roe": 20, "pe": 10,
        "pb": 10, "peg": 10, "debt": 10, "cash": 10,
    }

    score = 0.0
    score += weights["revenue"] if revenue > 0 else weights["revenue"] * 0.3
    score += weights["earnings"] if earnings > 0 else weights["earnings"] * 0.3
    score += weights["roe"] * min(max(roe / 20.0, 0.0), 1.0)
    score += weights["pe"] if 0 < pe < 30 else weights["pe"] * 0.3
    score += weights["pb"] if 0 < pb < 5 else weights["pb"] * 0.3
    score += weights["peg"] if 0 < peg < 2 else weights["peg"] * 0.3
    score += weights["debt"] if 0 <= debt < 1.5 else weights["debt"] * 0.2
    score += weights["cash"] if cash > 0 else weights["cash"] * 0.2

    return round(min(max(score, 0.0), 100.0), 2)


def sell_fundamental_score(fundamentals: dict[str, Any]) -> float:
    """0-100, higher = weaker company = more SELL-favorable. Mirror of
    buy_fundamental_score() rather than an independently tuned rule set."""
    return round(100.0 - buy_fundamental_score(fundamentals), 2)
