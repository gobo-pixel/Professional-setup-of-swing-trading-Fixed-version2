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

    total_scans = result.get("total_scans", 0)
    buy_n = signal_counts.get("BUY", 0)
    sell_n = signal_counts.get("SELL", 0)
    no_trade_n = signal_counts.get("NO_TRADE", 0)
    tier1 = result.get("tier1_pass_rate", {})

    def _sector_label(sector: str) -> str:
        return "Unknown sector" if sector == "UNKNOWN" else sector

    def _health_emoji(level: str) -> str:
        return {"healthy": "🟢", "watch": "🟡", "investigate": "🔴"}.get(level, "🟡")

    # ---------------- 1. Header ----------------
    message_lines = [
        "📊 Daily Scan Summary",
        "",
        f"Universe Scanned : {total_scans}",
        f"BUY Signals      : {buy_n}",
        f"SELL Signals     : {sell_n}",
        f"NO TRADE         : {no_trade_n}",
        "",
        "Tier-1 Pass Rate",
        f"BUY  : {tier1.get('buy', 0)}%",
        f"SELL : {tier1.get('sell', 0)}%",
    ]

    if tier_contrib:
        message_lines.append("")
        message_lines.append("Rule Contribution (avg score)")
        message_lines.append("(Tier2 = technical indicators score, Tier3 = fundamentals+news+market score)")
        message_lines.append(
            f"BUY  — Tier2: {tier_contrib.get('buy_tier2_avg', 0)}, Tier3: {tier_contrib.get('buy_tier3_avg', 0)}"
        )
        message_lines.append(
            f"SELL — Tier2: {tier_contrib.get('sell_tier2_avg', 0)}, Tier3: {tier_contrib.get('sell_tier3_avg', 0)}"
        )

    # ---------------- 2. Market Regime (unchanged) ----------------
    if regime_pct:
        message_lines.append("")
        message_lines.append("Market Regime")
        emoji = {"BULL": "🟢", "SIDEWAYS": "🟡", "BEAR": "🔴"}
        for regime in ("BULL", "SIDEWAYS", "BEAR"):
            if regime in regime_pct:
                label = {"BULL": "Bullish", "SIDEWAYS": "Sideways", "BEAR": "Bearish"}[regime]
                message_lines.append(f"{emoji[regime]} {label}: {regime_pct[regime]}%")

    # ---------------- 3. Sector Analysis ----------------
    if top_sectors:
        message_lines.append("")
        message_lines.append("Top BUY Sectors")
        for i, (sector, count) in enumerate(top_sectors, 1):
            if count > 0:
                message_lines.append(f"{i}. {_sector_label(sector)} ({count} BUY)")
    if weak_sectors:
        message_lines.append("")
        message_lines.append("Weakest BUY Sectors")
        for i, (sector, count) in enumerate(weak_sectors, 1):
            message_lines.append(f"{i}. {_sector_label(sector)} ({count} BUY)")
        unknown_symbols = result.get("unknown_sector_symbols", [])
        if unknown_symbols:
            message_lines.append(
                "Note: \"Unknown sector\" means yfinance didn't return a sector "
                "for that stock (data gap, not a strategy issue). Affected:"
            )
            message_lines.append("  " + ", ".join(unknown_symbols[:10]))

    # ---------------- 4. Rejection Funnel ----------------
    # Honest note: these are the categories the classifier can actually
    # tell apart (Trend/Risk/Portfolio/Liquidity/Score-Threshold/Other).
    # A Momentum/News/Fundamental-specific split isn't derivable from
    # current data without new, separate detector work — not fabricated
    # here.
    if funnel:
        message_lines.append("")
        message_lines.append("Rejection Funnel (BUY-side only)")
        message_lines.append(
            f"{funnel.get('buy_side_scanned', 0)} Scanned "
            f"({total_scans} total scanned − {sell_n} SELL, tracked separately below)"
        )
        message_lines.append(f"├── BUY Candidates: {funnel.get('buy_candidates', 0)}")
        message_lines.append(f"├── Rejected — Trend: {funnel.get('rejected_by_trend', 0)}")
        message_lines.append(f"├── Rejected — Risk (signal stage): {funnel.get('rejected_by_risk', 0)}")
        message_lines.append(f"├── Rejected — Portfolio: {funnel.get('rejected_by_portfolio', 0)}")
        message_lines.append(f"├── Rejected — Liquidity: {funnel.get('rejected_by_liquidity', 0)}")
        message_lines.append(f"├── Rejected — Score Threshold: {funnel.get('rejected_by_score_threshold', 0)}")
        message_lines.append(
            f"├── Rejected — Insufficient Historical Candles: {funnel.get('rejected_by_insufficient_history', 0)}"
        )
        other_n = funnel.get("rejected_by_other", 0)
        message_lines.append(f"├── Rejected — Other: {other_n}")
        other_breakdown = funnel.get("other_reasons_breakdown", {})
        if other_breakdown:
            for reason, count in other_breakdown.items():
                message_lines.append(f"│     • {reason}: {count}")
        message_lines.append(f"└── Executed: {funnel.get('executed', 0)}")

    # ---------------- 5. Execution Summary (with Eligible) ----------------
    if execution:
        reasons = execution.get("reasons", {})
        # "Eligible" = candidates that were genuinely close to executing
        # (blocked only by capital/liquidity/risk at the execution
        # stage) — as opposed to score-threshold/other rejections,
        # which were disqualified well before execution was even considered.
        eligible = (
            reasons.get("Capital / Portfolio Rules", 0)
            + reasons.get("Risk Engine (execution stage)", 0)
            + reasons.get("Liquidity", 0)
        )
        message_lines.append("")
        message_lines.append("BUY Execution")
        message_lines.append(f"Signals Generated : {execution.get('buy_generated', 0)}")
        message_lines.append(f"Eligible           : {eligible}")
        message_lines.append(f"Executed           : {execution.get('buy_executed', 0)}")
        message_lines.append(f"Not Executed       : {execution.get('buy_rejected', 0)}")
        if reasons:
            message_lines.append("Reason")
            for reason, count in reasons.items():
                message_lines.append(f"  {reason}: {count}")

    # ---------------- 6. SELL Summary (reconciled) ----------------
    if sell_gap.get("sell_signals", 0) > 0:
        message_lines.append("")
        message_lines.append("SELL Execution")
        message_lines.append(f"Signals Generated : {sell_gap['sell_signals']}")
        message_lines.append(f"Opened            : {sell_gap['sell_trades_opened']}")
        message_lines.append(f"Rejected          : {sell_gap.get('gap', 0)}")
        if sell_gap.get("gap_reasons"):
            message_lines.append("Reason")
            for reason, count in sell_gap["gap_reasons"].items():
                message_lines.append(f"  {reason}: {count}")

    # ---------------- 7. AI Observation ----------------
    # Rule-based, derived directly from the numbers above — not a
    # separate LLM call, just plain-language sentences built from real
    # computed values so the report is skimmable at a glance.
    observations = []
    if regime_pct:
        dominant = max(regime_pct, key=regime_pct.get)
        dominant_label = {"BULL": "bullish", "SIDEWAYS": "mixed/sideways", "BEAR": "bearish"}[dominant]
        observations.append(f"Market regime was predominantly {dominant_label} today ({regime_pct[dominant]}%).")
    if top_sectors and top_sectors[0][1] > 0:
        observations.append(f"{_sector_label(top_sectors[0][0])} generated the most BUY opportunities ({top_sectors[0][1]}).")
    if funnel:
        biggest_reason = max(
            [
                ("Trend", funnel.get("rejected_by_trend", 0)),
                ("Risk", funnel.get("rejected_by_risk", 0)),
                ("Portfolio", funnel.get("rejected_by_portfolio", 0)),
                ("Liquidity", funnel.get("rejected_by_liquidity", 0)),
                ("Score Threshold", funnel.get("rejected_by_score_threshold", 0)),
                ("Insufficient Historical Candles", funnel.get("rejected_by_insufficient_history", 0)),
            ],
            key=lambda kv: kv[1],
        )
        if biggest_reason[1] > 0:
            observations.append(f"Most rejected candidates failed on {biggest_reason[0]} ({biggest_reason[1]}).")
    if execution and execution.get("buy_executed", 0) == 0 and execution.get("buy_generated", 0) > 0:
        observations.append("No BUY trades executed today — all eligible candidates were blocked at capital/liquidity/risk checks.")
    if observations:
        message_lines.append("")
        message_lines.append("AI Observation")
        for obs in observations:
            message_lines.append(f"• {obs}")

    # ---------------- 8. Strategy Health ----------------
    exec_rate = (
        round(execution.get("buy_executed", 0) / execution.get("buy_generated", 1) * 100, 1)
        if execution.get("buy_generated") else 0.0
    )
    buy_opportunities_level = "healthy" if buy_n >= 50 else ("watch" if buy_n >= 15 else "investigate")
    regime_spread = max(regime_pct.values()) - min(regime_pct.values()) if len(regime_pct) > 1 else 100
    trend_level = "healthy" if regime_spread >= 40 else "watch"
    exec_level = "healthy" if exec_rate >= 5 else ("watch" if exec_rate > 0 else "investigate")

    message_lines.append("")
    message_lines.append("Strategy Health")
    message_lines.append(f"{_health_emoji(buy_opportunities_level)} BUY Opportunities : {buy_opportunities_level.title()} ({buy_n})")
    message_lines.append("   Rule: Healthy ≥50, Watch 15-49, Investigate <15")
    message_lines.append(f"{_health_emoji(trend_level)} Market Trend      : {trend_level.title()}")
    message_lines.append("   Rule: Healthy if regime spread ≥40pp (clear dominant regime)")
    message_lines.append(f"{_health_emoji(exec_level)} Execution Rate    : {exec_level.title()} ({exec_rate}%)")
    message_lines.append("   Rule: Healthy ≥5%, Watch 0-5%, Investigate at 0%")
    if exec_level == "investigate":
        message_lines.append("Recommendation: review execution filters (capital/liquidity/risk) before touching strategy logic.")

    # ---------------- 8b. Scan Efficiency ----------------
    message_lines.append("")
    message_lines.append("⭐ Scan Efficiency")
    message_lines.append(f"{total_scans} Stocks")
    if total_scans:
        message_lines.append(f"↓ {buy_n} BUY  ({round(buy_n / total_scans * 100, 1)}%)")
        message_lines.append(f"↓ {sell_n} SELL  ({round(sell_n / total_scans * 100, 1)}%)")
        message_lines.append(f"↓ {no_trade_n} NO TRADE  ({round(no_trade_n / total_scans * 100, 1)}%)")

    # ---------------- 8c. Pipeline Health ----------------
    # Explicit rules, shown so the classification isn't a black box:
    #  Trend Filter: healthy if it's genuinely discriminating (rejecting
    #    somewhere between 10-90% of candidates) — 0% means it never
    #    rejects anything (suspicious), ~100% means nothing ever passes.
    #  Execution Filter: healthy if at least one BUY actually executed;
    #    "needs investigation" if signals were generated but zero executed.
    #  Portfolio Filter: "idle" if it never had a chance to reject anything
    #    (0 portfolio-rejections) — not necessarily broken, just unused
    #    this run; "working" if it's genuinely rejecting when triggered.
    message_lines.append("")
    message_lines.append("⭐ Pipeline Health")
    buy_side_scanned = funnel.get("buy_side_scanned", 1) or 1
    trend_rejection_rate = funnel.get("rejected_by_trend", 0) / buy_side_scanned * 100
    trend_status = "Working" if 10 <= trend_rejection_rate <= 90 else "Needs Investigation"
    trend_emoji = "🟢" if trend_status == "Working" else "🔴"
    message_lines.append(f"Trend Filter       : {trend_status} {trend_emoji}")

    exec_status = "Working" if execution.get("buy_executed", 0) > 0 else (
        "Needs Investigation" if execution.get("buy_generated", 0) > 0 else "Idle"
    )
    exec_emoji = {"Working": "🟢", "Needs Investigation": "🔴", "Idle": "⚪"}[exec_status]
    message_lines.append(f"Execution Filter   : {exec_status} {exec_emoji}")

    portfolio_status = "Working" if funnel.get("rejected_by_portfolio", 0) > 0 else "Idle"
    portfolio_emoji = "🟢" if portfolio_status == "Working" else "⚪"
    message_lines.append(f"Portfolio Filter   : {portfolio_status} {portfolio_emoji}")

    # ---------------- 9. Numbers Consistency Check ----------------
    # Mandatory reconciliation — verifies the report's own numbers add
    # up before it's presented as trustworthy, instead of silently
    # shipping a report whose totals don't match (which is exactly what
    # was happening before this was added).
    errors = []
    if funnel:
        funnel_sum = (
            funnel.get("buy_candidates", 0) + funnel.get("rejected_by_trend", 0)
            + funnel.get("rejected_by_risk", 0) + funnel.get("rejected_by_portfolio", 0)
            + funnel.get("rejected_by_liquidity", 0) + funnel.get("rejected_by_score_threshold", 0)
            + funnel.get("rejected_by_insufficient_history", 0) + funnel.get("rejected_by_other", 0)
        )
        if funnel_sum != funnel.get("buy_side_scanned", 0):
            errors.append(f"BUY funnel: parts sum to {funnel_sum}, expected {funnel.get('buy_side_scanned', 0)}")
    if execution and execution.get("reasons"):
        reasons_sum = sum(execution["reasons"].values())
        if reasons_sum != execution.get("buy_rejected", 0):
            errors.append(f"BUY execution reasons: sum to {reasons_sum}, expected {execution.get('buy_rejected', 0)}")
    if sell_gap.get("gap_reasons"):
        sell_reasons_sum = sum(sell_gap["gap_reasons"].values())
        if sell_reasons_sum != sell_gap.get("gap", 0):
            errors.append(f"SELL reasons: sum to {sell_reasons_sum}, expected {sell_gap.get('gap', 0)}")

    message_lines.append("")
    message_lines.append("Numbers Consistency Check")
    if errors:
        message_lines.append("❌ ERROR — totals do not reconcile:")
        for e in errors:
            message_lines.append(f"  • {e}")
    else:
        message_lines.append("✓ OK — all totals reconcile.")

    notify(
        event_type="analysis_summary",
        message="\n".join(message_lines),
        dedup_key=f"analysis_summary::{time.strftime('%Y-%m-%d')}::{now_ist().strftime('%H:%M:%S.%f')}",
    )


if __name__ == "__main__":
    main()
