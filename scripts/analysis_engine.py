"""
MODULE 1 — ANALYSIS ENGINE (CLI)

Thin command-line wrapper around analytics.analysis_engine.AnalysisEngine
(the single canonical implementation — no logic is duplicated here).

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
    message_lines = [
        f"Analysis Summary — {result.get('total_scans', 0)} scans analyzed.",
        f"BUY: {signal_counts.get('BUY', 0)} | SELL: {signal_counts.get('SELL', 0)} | "
        f"NO_TRADE: {signal_counts.get('NO_TRADE', 0)}",
        f"Tier-1 pass rate: {result.get('tier1_pass_rate', {})}",
    ]
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
        dedup_key=f"analysis_summary::{time.strftime('%Y-%m-%d')}",
    )


if __name__ == "__main__":
    main()
