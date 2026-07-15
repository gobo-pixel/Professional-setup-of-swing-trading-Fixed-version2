"""
NEWS BIAS (shared)

Converts a 0-100 news sentiment score into a directional bias in [-1, +1]:
  +1  strongly positive news -> favors BUY
   0  neutral / NO NEWS -> no directional opinion (never blocks a trade)
  -1  strongly negative news -> favors SELL

This replaces the old `news_score >= 60` mandatory gate, which silently
rejected almost every trade on days with no fresh company news (the
scanner defaults to a neutral 50 when no news is found, and 50 < 60).
"""

from __future__ import annotations

NEUTRAL = 50.0


def news_bias(news_score: float | None) -> float:
    if news_score is None:
        return 0.0
    return round(max(-1.0, min(1.0, (news_score - NEUTRAL) / NEUTRAL)), 3)


def news_component(news_score: float | None) -> float:
    """0-100 scale version of the bias, centered on 50 — convenient for
    blending directly into a weighted 0-100 score."""
    return round(50.0 + news_bias(news_score) * 50.0, 2)
