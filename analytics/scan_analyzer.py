"""
PHASE 2 — MODULE 1: ANALYSIS ENGINE

Reads reports/full_report.csv (the scan journal) and produces a complete
statistical breakdown of the most recent scan (or any date range):

- BUY / SELL / NO_TRADE statistics
- Rule pass/fail counts (Tier 1/2/3)
- Tier-1 pass rate
- Tier-2 contribution (avg score)
- Tier-3 contribution (avg score)
- Tier-4 rejection reasons (what actually blocked trades)
- Sector-wise statistics
- Market-regime statistics
- Top rejection reasons
- Daily performance summary

This module ONLY reads and reports — it never modifies strategy behavior.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def _f(row: dict, key: str, default: float = 0.0) -> float:
    v = row.get(key, "")
    try:
        return float(v) if v not in ("", None) else default
    except (ValueError, TypeError):
        return default


class ScanAnalyzer:
    """Module 1 — Analysis Engine."""

    def __init__(self, report_path: str = "reports/full_report.csv"):
        self.report_path = report_path

    def load(self, date: str | None = None) -> list[dict]:
        path = Path(self.report_path)
        if not path.exists():
            logger.warning("No report found at %s", self.report_path)
            return []
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if date:
            rows = [r for r in rows if r.get("Date") == date]
        return rows

    def analyze(self, date: str | None = None) -> dict:
        rows = self.load(date)
        if not rows:
            return {"error": "No data available for the requested date."}

        total = len(rows)
        signals = Counter(r["Signal"] for r in rows)

        # --- Tier 1 pass rates (BUY and SELL separately) ---
        buy_tier1_pass = sum(1 for r in rows if r.get("BuyTier1Passed") == "True")
        sell_tier1_pass = sum(1 for r in rows if r.get("SellTier1Passed") == "True")

        # --- Tier 2 / Tier 3 average contribution ---
        buy_tier2_avg = self._avg(rows, "BuyTier2Score")
        buy_tier3_avg = self._avg(rows, "BuyTier3Score")
        sell_tier2_avg = self._avg(rows, "SellTier2Score")
        sell_tier3_avg = self._avg(rows, "SellTier3Score")

        # --- Tier 4 rejection reasons ---
        tier4_reasons = Counter(
            r["Tier4Block"] for r in rows if r.get("Tier4Block")
        )

        # --- Sector-wise stats ---
        sector_stats: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            sector = r.get("Sector") or "Unknown"
            sector_stats[sector][r["Signal"]] += 1

        # --- Market regime stats ---
        regime_stats = Counter(r.get("market_regime", "UNKNOWN") for r in rows)

        # --- Rule pass/fail counts (from BuyTier1Detail / SellTier1Detail) ---
        buy_rule_counts: Counter = Counter()
        sell_rule_counts: Counter = Counter()
        for r in rows:
            for pair in (r.get("BuyTier1Detail") or "").split("; "):
                if "=" in pair:
                    rule, val = pair.split("=", 1)
                    if val == "True":
                        buy_rule_counts[rule] += 1
            for pair in (r.get("SellTier1Detail") or "").split("; "):
                if "=" in pair:
                    rule, val = pair.split("=", 1)
                    if val == "True":
                        sell_rule_counts[rule] += 1

        # --- Top rejection reasons (from the Reason field, NO_TRADE only) ---
        rejection_reasons: Counter = Counter()
        for r in rows:
            if r["Signal"] == "NO_TRADE":
                for part in (r.get("Reason") or "").split(" | "):
                    part = part.strip()
                    if part:
                        rejection_reasons[part] += 1

        # --- Daily performance summary ---
        daily: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            daily[r.get("Date", "unknown")][r["Signal"]] += 1

        return {
            "total_scanned": total,
            "signal_distribution": dict(signals),
            "buy_tier1_pass_rate": round(buy_tier1_pass / total * 100, 2),
            "sell_tier1_pass_rate": round(sell_tier1_pass / total * 100, 2),
            "buy_tier2_avg_contribution": buy_tier2_avg,
            "buy_tier3_avg_contribution": buy_tier3_avg,
            "sell_tier2_avg_contribution": sell_tier2_avg,
            "sell_tier3_avg_contribution": sell_tier3_avg,
            "tier4_rejection_reasons": dict(tier4_reasons.most_common(10)),
            "sector_stats": {k: dict(v) for k, v in sector_stats.items()},
            "market_regime_stats": dict(regime_stats),
            "buy_rule_pass_counts": dict(buy_rule_counts),
            "sell_rule_pass_counts": dict(sell_rule_counts),
            "top_rejection_reasons": dict(rejection_reasons.most_common(10)),
            "daily_summary": {k: dict(v) for k, v in daily.items()},
        }

    @staticmethod
    def _avg(rows: list[dict], key: str) -> float:
        vals = [_f(r, key) for r in rows if r.get(key) not in ("", None)]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    def print_report(self, date: str | None = None) -> None:
        stats = self.analyze(date)
        if "error" in stats:
            print(stats["error"])
            return

        print("=" * 60)
        print(f"SCAN ANALYSIS REPORT{' — ' + date if date else ' — ALL DATES'}")
        print("=" * 60)
        print(f"Total scanned: {stats['total_scanned']}")
        print(f"Signal distribution: {stats['signal_distribution']}")
        print()
        print(f"BUY  Tier-1 pass rate: {stats['buy_tier1_pass_rate']}%")
        print(f"SELL Tier-1 pass rate: {stats['sell_tier1_pass_rate']}%")
        print(f"BUY  Tier-2 avg / Tier-3 avg: {stats['buy_tier2_avg_contribution']} / {stats['buy_tier3_avg_contribution']}")
        print(f"SELL Tier-2 avg / Tier-3 avg: {stats['sell_tier2_avg_contribution']} / {stats['sell_tier3_avg_contribution']}")
        print()
        print("Tier-4 (hard risk) rejection reasons:")
        for reason, count in stats["tier4_rejection_reasons"].items():
            print(f"  {reason}: {count}")
        print()
        print("Top NO_TRADE rejection reasons:")
        for reason, count in stats["top_rejection_reasons"].items():
            print(f"  {reason}: {count}")
        print()
        print("Market regime distribution:", stats["market_regime_stats"])
        print()
        print("Sector-wise signal distribution:")
        for sector, dist in stats["sector_stats"].items():
            print(f"  {sector}: {dist}")


if __name__ == "__main__":
    ScanAnalyzer().print_report()
