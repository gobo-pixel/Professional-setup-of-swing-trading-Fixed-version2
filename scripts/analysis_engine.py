"""
MODULE 1 — ANALYSIS ENGINE (CLI)

Thin command-line wrapper around analytics.analysis_engine.AnalysisEngine
(the single canonical implementation — no logic is duplicated here).

Roadmap coverage (Phase 2, Module 1):
    [x] BUY/SELL statistics — signal_counts
    [x] NO_TRADE analysis   — no_trade_stats
    [x] Rule contribution   — tier_contribution
    [x] Tier analysis       — tier1_pass_rate, tier_contribution
    [x] Sector statistics   — sector_stats, top_buy_sectors, weakest_buy_sectors
    [x] Regime statistics   — regime_stats, regime_percentages
    [x] Daily summaries     — daily_summary
    [x] Rejection analysis  — top_rejection_reasons, rejection_funnel

Reads reports/full_report.csv and produces a complete statistical
breakdown: BUY/SELL/NO_TRADE counts, Tier-1/2/3 contribution, Tier-4
rejection reasons, sector-wise stats, regime stats, top rejection reasons.

This module only OBSERVES and REPORTS — it never changes strategy code
or production settings.

Usage:
    python scripts/analysis_engine.py [--csv path]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from core.trading_calendar import now_ist  # noqa: E402
from analytics.analysis_engine import AnalysisEngine  # noqa: E402

logger = get_logger(__name__)

OUTPUT_PATH = "reports/analysis_summary.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="reports/full_report.csv")
    args = parser.parse_args()

    engine = AnalysisEngine(report_path=args.csv)
    n = engine.load()
    print(f"Loaded {n} rows from {args.csv}")

    engine.print_report()

    result = engine.analyze()
    Path("reports").mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Analysis summary written to %s", OUTPUT_PATH)

    signal_counts = result.get("signal_counts", {})
    sell_gap = result.get("sell_signal_vs_opened", {})
    regime_pct = result.get("regime_percentages", {})
    top_sectors = result.get("top_buy_sectors", [])
    weak_sectors = result.get("weakest_buy_sectors", [])
    funnel = result.get("rejection_funnel", {})
    execution = result.get("execution_summary", {})
    tier_contrib = result.get("tier_contribution", {})

    message_lines = [
        f"Analysis Summary — {result.get('total_scans', 0)} scans analyzed.",
        f"BUY: {signal_counts.get('BUY', 0)} | SELL: {signal_counts.get('SELL', 0)} | "
        f"NO_TRADE: {signal_counts.get('NO_TRADE', 0)}",
        f"Tier-1 pass rate: {result.get('tier1_pass_rate', {})}",
    ]

    if tier_contrib:
        message_lines.append(
            f"Rule contribution (avg score) — BUY: Tier2={tier_contrib.get('buy_tier2_avg', 0)}, "
            f"Tier3={tier_contrib.get('buy_tier3_avg', 0)} | SELL: Tier2={tier_contrib.get('sell_tier2_avg', 0)}, "
            f"Tier3={tier_contrib.get('sell_tier3_avg', 0)}"
        )

    if regime_pct:
        message_lines.append("")
        message_lines.append("Market Regime")
        emoji = {"BULL": "🟢", "SIDEWAYS": "🟡", "BEAR": "🔴"}
        for regime in ("BULL", "SIDEWAYS", "BEAR"):
            if regime in regime_pct:
                label = {"BULL": "Bullish", "SIDEWAYS": "Sideways", "BEAR": "Bearish"}[regime]
                message_lines.append(f"{emoji[regime]} {label}: {regime_pct[regime]}%")

    def _sector_label(sector: str) -> str:
        return "Unknown sector" if sector == "UNKNOWN" else sector

    if top_sectors:
        message_lines.append("")
        message_lines.append("Top BUY Sectors")
        for i, (sector, count) in enumerate(top_sectors, 1):
            if count > 0:
                message_lines.append(f"{i}. {_sector_label(sector)} ({count} BUY)")
    if weak_sectors:
        message_lines.append("")
        message_lines.append("Weakest Sectors")
        for i, (sector, count) in enumerate(weak_sectors, 1):
            message_lines.append(f"{i}. {_sector_label(sector)}")

    if funnel:
        message_lines.append("")
        message_lines.append("Rejection Funnel (BUY-side only — SELL tracked separately below)")
        message_lines.append(f"{funnel.get('buy_side_scanned', 0)} Scanned")
        message_lines.append(f"├── BUY Candidates: {funnel.get('buy_candidates', 0)}")
        message_lines.append(f"├── Rejected by Trend: {funnel.get('rejected_by_trend', 0)}")
        message_lines.append(f"├── Rejected by Risk Engine (signal stage): {funnel.get('rejected_by_risk', 0)}")
        message_lines.append(f"├── Rejected by Portfolio: {funnel.get('rejected_by_portfolio', 0)}")
        message_lines.append(f"├── Rejected by Liquidity: {funnel.get('rejected_by_liquidity', 0)}")
        message_lines.append(f"├── Rejected by Score Threshold: {funnel.get('rejected_by_score_threshold', 0)}")
        message_lines.append(f"├── Rejected — Other: {funnel.get('rejected_by_other', 0)}")
        message_lines.append(f"└── Executed: {funnel.get('executed', 0)}")

    if execution:
        message_lines.append("")
        message_lines.append("Execution Summary")
        message_lines.append(f"BUY Signals Generated: {execution.get('buy_generated', 0)}")
        message_lines.append(f"BUY Executed: {execution.get('buy_executed', 0)}")
        message_lines.append(f"BUY Rejected: {execution.get('buy_rejected', 0)}")
        if execution.get("reasons"):
            message_lines.append("Reasons")
            for reason, count in execution["reasons"].items():
                message_lines.append(f"  {reason}: {count}")

    if sell_gap.get("sell_signals", 0) > 0 and sell_gap.get("gap", 0) > 0:
        message_lines.append("")
        message_lines.append(f"SELL Signals: {sell_gap['sell_signals']}")
        message_lines.append(f"SELL Trades Opened: {sell_gap['sell_trades_opened']}")
        message_lines.append("Reason:")
        if sell_gap.get("gap_reasons"):
            for reason, count in sell_gap["gap_reasons"].items():
                message_lines.append(f"  {reason} ({count})")
        else:
            message_lines.append("  All SELL candidates failed final portfolio/risk validation.")

    notify(
        event_type="analysis_summary",
        message="\n".join(message_lines),
        dedup_key=f"analysis_summary::{time.strftime('%Y-%m-%d')}::{now_ist().strftime('%H:%M:%S.%f')}",
    )


if __name__ == "__main__":
    main()
