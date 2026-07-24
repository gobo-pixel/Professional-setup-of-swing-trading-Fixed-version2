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
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.rejection_classifier import classify_tier4_block
from core.trading_calendar import now_ist


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

    @staticmethod
    def _count_opened_today(direction: str, trade_journal_path: str = "storage/trades/trades_master.csv") -> int:
        path = Path(trade_journal_path)
        if not path.exists():
            return 0
        today_str = now_ist().strftime("%Y-%m-%d")
        count = 0
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("action") != "OPEN" or row.get("direction") != direction:
                    continue
                try:
                    ts = float(row.get("timestamp", 0))
                except ValueError:
                    continue
                row_date = time.strftime("%Y-%m-%d", time.gmtime(ts + 5.5 * 3600))  # UTC -> IST
                if row_date == today_str:
                    count += 1
        return count

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

        # ---------------- SELL Signals vs SELL Trades Opened ----------------
        # Uses the ALREADY-EXISTING trade journal (trades_master.csv) and
        # the ALREADY-EXISTING Tier4Block rejection text — no new storage,
        # no new calculation, just cross-referencing two existing sources.
        sell_signal_rows = [r for r in rows if r.get("Signal") == "SELL"]
        opened_sell_today = self._count_opened_today("SELL")
        gap = len(sell_signal_rows) - opened_sell_today
        sell_rejection_reasons = Counter(
            r.get("Tier4Block", "").strip() for r in sell_signal_rows
            if r.get("Tier4Block", "").strip()
        )
        report["sell_signal_vs_opened"] = {
            "sell_signals": len(sell_signal_rows),
            "sell_trades_opened": opened_sell_today,
            "gap": max(gap, 0),
            "gap_reasons": dict(sell_rejection_reasons.most_common(5)),
        }

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

        # ---------------- Market Regime percentages ----------------
        total_regime_rows = sum(sum(v.values()) for v in sector_stats.values()) or 1
        regime_totals = Counter()
        for r in rows:
            regime_totals[r.get("market_regime") or "UNKNOWN"] += 1
        report["regime_percentages"] = {
            k: round(v / len(rows) * 100, 1) for k, v in regime_totals.items()
        } if rows else {}

        # ---------------- Top / Weakest BUY sectors ----------------
        sector_buy_counts = {k: v.get("BUY", 0) for k, v in sector_stats.items()}
        ranked_sectors = sorted(sector_buy_counts.items(), key=lambda kv: kv[1], reverse=True)
        report["top_buy_sectors"] = ranked_sectors[:3]
        # "Weakest" = lowest BUY activity among sectors that were
        # actually scanned (excludes sectors with 0 total rows, which
        # would trivially "win" this ranking without meaning anything).
        scanned_sectors = [(k, v) for k, v in sector_buy_counts.items() if sector_stats[k]]
        report["weakest_buy_sectors"] = sorted(scanned_sectors, key=lambda kv: kv[1])[:3]

        # ---------------- Rejection Funnel ----------------
        # Scanned -> BUY Candidates -> Rejected by Trend/Risk/Portfolio
        # -> Executed. Uses the SAME shared classifier as Daily Scan's
        # own Rejection Summary — no duplicate categorization logic.
        # NOTE: "Rejected by Fundamentals" is intentionally NOT included
        # — Tier1 is purely technical (trend/EMA/SMA), and fundamentals
        # are blended into Tier3 together with news/market context, so
        # they cannot be cleanly isolated without inventing a new
        # detector/threshold that doesn't exist in the strategy today.
        buy_candidate_rows = [r for r in rows if r.get("Signal") in ("BUY", "NO_TRADE")]
        rejected_trend = sum(1 for r in buy_candidate_rows if r.get("BuyTier1Passed") == "False")
        rejected_risk = rejected_portfolio = 0
        for r in buy_candidate_rows:
            # Non-overlapping with "rejected_by_trend": only count
            # risk/portfolio rejections for rows that already PASSED
            # Tier1, so each row is attributed to exactly one funnel
            # stage instead of being double-counted.
            if r.get("Signal") != "NO_TRADE" or r.get("BuyTier1Passed") != "True":
                continue
            category = classify_tier4_block(r.get("Tier4Block"))
            if category == "risk":
                rejected_risk += 1
            elif category == "portfolio":
                rejected_portfolio += 1
        executed_buy_today = self._count_opened_today("BUY")
        report["rejection_funnel"] = {
            "scanned": len(rows),
            "buy_candidates": signal_counts.get("BUY", 0),
            "rejected_by_trend": rejected_trend,
            "rejected_by_risk": rejected_risk,
            "rejected_by_portfolio": rejected_portfolio,
            "executed": executed_buy_today,
        }

        # ---------------- Execution Summary ----------------
        buy_generated = signal_counts.get("BUY", 0)
        buy_executed = executed_buy_today
        buy_rejected = max(buy_generated - buy_executed, 0)
        reason_buckets = Counter()
        for r in rows:
            if r.get("Signal") != "BUY":
                continue
            category = classify_tier4_block(r.get("Tier4Block"))
            if category == "portfolio":
                reason_buckets["Capital / Portfolio Rules"] += 1
            elif category == "risk":
                reason_buckets["Risk Engine"] += 1
            elif category == "liquidity":
                reason_buckets["Liquidity"] += 1
        report["execution_summary"] = {
            "buy_generated": buy_generated,
            "buy_executed": buy_executed,
            "buy_rejected": buy_rejected,
            "reasons": dict(reason_buckets.most_common(5)),
        }

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
