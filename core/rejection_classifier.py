"""
REJECTION CLASSIFIER (shared)

Categorizes a Tier4Block rejection-reason string into a small set of
buckets, using ONLY text that already exists in the report (the
underlying ValidationEngine/RiskManager/PortfolioRulesEngine reason
strings) — no new detection logic, purely a text categorization.

Shared by scripts/generate_full_report.py's Rejection Summary and
analytics/analysis_engine.py's Rejection Funnel / Execution Summary,
so both use the exact same classification instead of two copies.
"""

from __future__ import annotations

CATEGORY_RISK = "risk"
CATEGORY_LIQUIDITY = "liquidity"
CATEGORY_PORTFOLIO = "portfolio"
CATEGORY_SCORE_THRESHOLD = "score_threshold"
CATEGORY_INSUFFICIENT_HISTORY = "insufficient_history"
CATEGORY_OTHER = "other"


def classify_tier4_block(block_text: str) -> str:
    block = (block_text or "").lower()
    if not block:
        return CATEGORY_OTHER
    if "historical candles" in block or "insufficient history" in block:
        return CATEGORY_INSUFFICIENT_HISTORY
    if ("risk" in block or "unsafe" in block or "nan" in block or "circuit" in block
            or "drawdown" in block or "daily loss" in block):
        return CATEGORY_RISK
    if "volume" in block or "liquidity" in block:
        return CATEGORY_LIQUIDITY
    if (
        "exposure" in block or "capital" in block or "position" in block
        or "reserve" in block or "correlation" in block or "already exists" in block
        or "concentration" in block or "maximum portfolio" in block
    ):
        return CATEGORY_PORTFOLIO
    if "decision engine rejected" in block or "validation failed" in block:
        return CATEGORY_SCORE_THRESHOLD
    return CATEGORY_OTHER
