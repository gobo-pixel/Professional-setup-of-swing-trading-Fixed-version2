"""
PHASE 2 — MODULE 1: ANALYSIS ENGINE

Reads the full_report.csv history (which now carries Tier1/2/3 explainability
data from every scan) and produces a complete statistical breakdown:
BUY/SELL/NO_TRADE stats, rule pass/fail counts, Tier-1 pass rate, Tier-2/3
contribution, Tier-4 rejection reasons, sector stats, regime stats, top
rejection reasons, and a daily performance summary.

This module ONLY reads and reports — it never changes strategy behavior.

Usage:
    python -m analytics.analysis_engine
    (reads reports/full_report.csv by default)
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


class AnalysisEngine:

    def __init__(self, report_path: str = "reports/full_report.csv"):
        self.report_path = report_path
        self.rows: list[dict[str, Any]] = []

    def load(self) -> int:
        path = Path(self.report_path)
        if not path.exists():
            self.rows = []
            return 0
        with open(path, newline="") as f:
            self.rows = list(csv.DictReader(f))
        return len(self.rows)

    @staticmethod
    def _f(row: dict, key: str, default: float = 0.0) -> float:
        v = row.get(key, "")
        try:
            return float(v) if v not in ("", None) else default
        except ValueError:
            return default

    def analyze(self) -> dict[str, Any]:
        rows = self.rows
        if not rows:
            return {"error": "No data loaded — call load() first, or the report file is empty."}

        report: dict[str, Any] = {}

        # ---------------- BUY / SELL / NO_TRADE stats ----------------
        signal_counts = Counter(r.get("Signal", "") for r in rows)
        report["signal_counts"] = dict(signal_counts)
        report["total_scans"] = len(rows)

        for side in ("BUY", "SELL"):
            side_rows = [r for r in rows if r.get("Signal") == side]
            confidences = [self._f(r, "Confidence") for r in side_rows]
            report[f"{side.lower()}_stats"] = {
                "count": len(side_rows),
                "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
                "min_confidence": round(min(confidences), 2) if confidences else 0.0,
                "max_confidence": round(max(confidences), 2) if confidences else 0.0,
            }

        no_trade_rows = [r for r in rows if r.get("Signal") == "NO_TRADE"]
        report["no_trade_stats"] = {"count": len(no_trade_rows)}

        # ---------------- Tier-1 pass rate ----------------
        buy_tier1 = [r.get("BuyTier1Passed") for r in rows if "BuyTier1Passed" in r]
        sell_tier1 = [r.get("SellTier1Passed") for r in rows if "SellTier1Passed" in r]
        report["tier1_pass_rate"] = {
            "buy": self._rate(buy_tier1),
            "sell": self._rate(sell_tier1),
        }

        # ---------------- Tier-2 / Tier-3 contribution ----------------
        buy_t2 = [self._f(r, "BuyTier2Score") for r in rows if r.get("BuyTier2Score")]
        buy_t3 = [self._f(r, "BuyTier3Score") for r in rows if r.get("BuyTier3Score")]
        sell_t2 = [self._f(r, "SellTier2Score") for r in rows if r.get("SellTier2Score")]
        sell_t3 = [self._f(r, "SellTier3Score") for r in rows if r.get("SellTier3Score")]
        report["tier_contribution"] = {
            "buy_tier2_avg": self._avg(buy_t2),
            "buy_tier3_avg": self._avg(buy_t3),
            "sell_tier2_avg": self._avg(sell_t2),
            "sell_tier3_avg": self._avg(sell_t3),
        }

        # ---------------- Tier-4 rejection reasons ----------------
        tier4_reasons = Counter(
            r.get("Tier4Block", "") for r in rows if r.get("Tier4Block", "").strip()
        )
        report["tier4_rejection_reasons"] = dict(tier4_reasons.most_common(10))

        # ---------------- Sector-wise stats ----------------
        sector_stats = defaultdict(lambda: Counter())
        for r in rows:
            sector = r.get("Sector") or "UNKNOWN"
            sector_stats[sector][r.get("Signal", "")] += 1
        report["sector_stats"] = {k: dict(v) for k, v in sector_stats.items()}

        # ---------------- Market-regime stats ----------------
        regime_stats = defaultdict(lambda: Counter())
        for r in rows:
            regime = r.get("market_regime") or "UNKNOWN"
            regime_stats[regime][r.get("Signal", "")] += 1
        report["regime_stats"] = {k: dict(v) for k, v in regime_stats.items()}

        # ---------------- Top rejection reasons ----------------
        # Pull the specific "engine validation failed" / "Trend not
        # confirmed" style phrases out of the Reason text.
        reason_counter = Counter()
        for r in no_trade_rows:
            reason_text = r.get("Reason", "")
            for phrase in reason_text.split(" | "):
                phrase = phrase.strip()
                if phrase and ("failed" in phrase.lower() or "not confirmed" in phrase.lower() or "rejected" in phrase.lower()):
                    reason_counter[phrase] += 1
        report["top_rejection_reasons"] = dict(reason_counter.most_common(10))

        # ---------------- Daily performance summary ----------------
        daily = defaultdict(lambda: Counter())
        for r in rows:
            date = r.get("Date", "UNKNOWN")
            daily[date][r.get("Signal", "")] += 1
        report["daily_summary"] = {k: dict(v) for k, v in sorted(daily.items())}

        return report

    @staticmethod
    def _rate(values: list) -> float:
        vals = [str(v).lower() == "true" for v in values if v not in ("", None)]
        return round(sum(vals) / len(vals) * 100, 2) if vals else 0.0

    @staticmethod
    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    def print_report(self) -> None:
        r = self.analyze()
        if "error" in r:
            print(r["error"])
            return

        print("=" * 60)
        print("ANALYSIS ENGINE REPORT")
        print("=" * 60)
        print(f"\nTotal scans: {r['total_scans']}")
        print(f"Signal distribution: {r['signal_counts']}")

        print(f"\n--- BUY ---\n{r['buy_stats']}")
        print(f"\n--- SELL ---\n{r['sell_stats']}")
        print(f"\n--- NO_TRADE ---\n{r['no_trade_stats']}")

        print(f"\n--- Tier-1 pass rate ---\n{r['tier1_pass_rate']}")
        print(f"\n--- Tier-2/3 contribution (avg score) ---\n{r['tier_contribution']}")
        print("\n--- Tier-4 rejection reasons (top 10) ---")
        for reason, count in r["tier4_rejection_reasons"].items():
            print(f"  {count:5d}  {reason}")

        print("\n--- Top rejection reasons (top 10) ---")
        for reason, count in r["top_rejection_reasons"].items():
            print(f"  {count:5d}  {reason}")

        print("\n--- Sector-wise signal counts ---")
        for sector, counts in sorted(r["sector_stats"].items()):
            print(f"  {sector:20s} {counts}")

        print("\n--- Market-regime signal counts ---")
        for regime, counts in r["regime_stats"].items():
            print(f"  {regime:12s} {counts}")

        print("\n--- Daily summary ---")
        for date, counts in r["daily_summary"].items():
            print(f"  {date:12s} {counts}")


if __name__ == "__main__":
    engine = AnalysisEngine()
    n = engine.load()
    print(f"Loaded {n} rows from {engine.report_path}")
    engine.print_report()
