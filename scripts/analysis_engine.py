"""
MODULE 1 — ANALYSIS ENGINE

Reads reports/full_report.csv (and storage/trades/trades_master.csv, if
present) and produces a complete statistical breakdown of the most recent
scan: BUY/SELL/NO_TRADE counts, Tier-1/2/3 contribution, Tier-4 rejection
reasons, sector-wise stats, regime stats, top rejection reasons.

This module only OBSERVES and REPORTS — it never changes strategy code
or production settings.

Usage:
    python scripts/analysis_engine.py [--date DD-MM-YYYY] [--csv path]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

DEFAULT_REPORT = "reports/full_report.csv"
OUTPUT_PATH = "reports/analysis_summary.json"


def _f(row: dict, key: str, default: float = 0.0) -> float:
    v = row.get(key, "")
    try:
        return float(v) if v not in ("", None) else default
    except (TypeError, ValueError):
        return default


def load_rows(csv_path: str, date_filter: str | None) -> list[dict]:
    if not Path(csv_path).exists():
        raise FileNotFoundError(
            f"{csv_path} not found — run scripts/generate_full_report.py first."
        )
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    if date_filter:
        rows = [r for r in rows if r.get("Date") == date_filter]
    return rows


def signal_stats(rows: list[dict]) -> dict:
    counts = Counter(r["Signal"] for r in rows)
    total = len(rows)
    return {
        "total_scanned": total,
        "buy_count": counts.get("BUY", 0),
        "sell_count": counts.get("SELL", 0),
        "no_trade_count": counts.get("NO_TRADE", 0),
        "buy_rate_pct": round(100 * counts.get("BUY", 0) / max(total, 1), 2),
        "sell_rate_pct": round(100 * counts.get("SELL", 0) / max(total, 1), 2),
    }


def tier_stats(rows: list[dict]) -> dict:
    buy_tier1_pass = sum(1 for r in rows if r.get("BuyTier1Passed") == "True")
    sell_tier1_pass = sum(1 for r in rows if r.get("SellTier1Passed") == "True")
    total = max(len(rows), 1)

    avg = lambda key: round(sum(_f(r, key) for r in rows) / total, 2)  # noqa: E731

    return {
        "buy_tier1_pass_rate_pct": round(100 * buy_tier1_pass / total, 2),
        "sell_tier1_pass_rate_pct": round(100 * sell_tier1_pass / total, 2),
        "buy_tier2_avg_contribution": avg("BuyTier2Score"),
        "buy_tier3_avg_contribution": avg("BuyTier3Score"),
        "sell_tier2_avg_contribution": avg("SellTier2Score"),
        "sell_tier3_avg_contribution": avg("SellTier3Score"),
    }


def tier4_rejections(rows: list[dict]) -> dict:
    blocks = [r["Tier4Block"] for r in rows if r.get("Tier4Block")]
    return dict(Counter(blocks).most_common(10))


def sector_stats(rows: list[dict]) -> dict:
    by_sector: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        sector = r.get("Sector") or "Unknown"
        by_sector[sector][r["Signal"]] += 1
    return {
        sector: dict(counts) for sector, counts in sorted(by_sector.items())
    }


def regime_stats(rows: list[dict]) -> dict:
    by_regime: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        regime = r.get("market_regime") or "Unknown"
        by_regime[regime][r["Signal"]] += 1
    return {regime: dict(counts) for regime, counts in by_regime.items()}


def top_rejection_reasons(rows: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    reasons = Counter()
    for r in rows:
        if r["Signal"] != "NO_TRADE":
            continue
        for part in str(r.get("Reason", "")).split("|"):
            part = part.strip()
            if part and not part.startswith("=") and "Strength" not in part:
                reasons[part] += 1
    return reasons.most_common(top_n)


def daily_summary(rows: list[dict]) -> dict:
    by_date: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_date[r.get("Date", "unknown")][r["Signal"]] += 1
    return {date: dict(counts) for date, counts in sorted(by_date.items())}


def run_analysis(csv_path: str = DEFAULT_REPORT, date_filter: str | None = None) -> dict:
    rows = load_rows(csv_path, date_filter)

    result = {
        "rows_analyzed": len(rows),
        "date_filter": date_filter or "ALL",
        "signal_stats": signal_stats(rows),
        "tier_stats": tier_stats(rows),
        "tier4_rejections": tier4_rejections(rows),
        "sector_stats": sector_stats(rows),
        "regime_stats": regime_stats(rows),
        "top_rejection_reasons": top_rejection_reasons(rows),
        "daily_summary": daily_summary(rows),
    }
    return result


def print_report(result: dict) -> None:
    print("\n" + "=" * 60)
    print("ANALYSIS ENGINE — SCAN SUMMARY")
    print("=" * 60)
    print(f"Rows analyzed: {result['rows_analyzed']}  (date filter: {result['date_filter']})")

    s = result["signal_stats"]
    print(f"\nBUY: {s['buy_count']} ({s['buy_rate_pct']}%)  "
          f"SELL: {s['sell_count']} ({s['sell_rate_pct']}%)  "
          f"NO_TRADE: {s['no_trade_count']}")

    t = result["tier_stats"]
    print(f"\nTier-1 pass rate  -> BUY: {t['buy_tier1_pass_rate_pct']}%  SELL: {t['sell_tier1_pass_rate_pct']}%")
    print(f"Tier-2 avg score  -> BUY: {t['buy_tier2_avg_contribution']}  SELL: {t['sell_tier2_avg_contribution']}")
    print(f"Tier-3 avg score  -> BUY: {t['buy_tier3_avg_contribution']}  SELL: {t['sell_tier3_avg_contribution']}")

    print("\nTop Tier-4 (hard risk) rejections:")
    for reason, count in result["tier4_rejections"].items():
        print(f"  {count:4d}x  {reason}")

    print("\nTop rejection reasons (NO_TRADE):")
    for reason, count in result["top_rejection_reasons"]:
        print(f"  {count:4d}x  {reason}")

    print("\nSector-wise signal distribution:")
    for sector, counts in result["sector_stats"].items():
        print(f"  {sector:20s} {counts}")

    print("\nMarket-regime signal distribution:")
    for regime, counts in result["regime_stats"].items():
        print(f"  {regime:12s} {counts}")

    print("\nDaily summary:")
    for date, counts in result["daily_summary"].items():
        print(f"  {date:12s} {counts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Filter to one Date (DD-MM-YYYY)")
    parser.add_argument("--csv", default=DEFAULT_REPORT)
    args = parser.parse_args()

    result = run_analysis(args.csv, args.date)
    print_report(result)

    Path("reports").mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Analysis summary written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
