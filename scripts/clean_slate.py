"""
CLEAN SLATE — Reset all accumulated trading/analysis data.

Deletes the data-accumulation files identified as containing a mix of
pre-fix (buggy) and post-fix trade records, so future analysis starts
from a genuinely clean, consistent baseline.

SAFETY: defaults to a DRY RUN (lists what would be deleted, deletes
nothing). Pass --confirm to actually perform the deletion.

Explicitly protected (never touched by this script):
  - storage/watchlist/nifty500.json   (the stock watchlist — config, not trade data)
  - reports/backtest_baseline.json    (about to be overwritten by a fresh backtest run anyway)
  - reports/backtest_result_latest.json
  - reports/regression_result_latest.json

Usage:
    python scripts/clean_slate.py              # dry run — shows what would be deleted
    python scripts/clean_slate.py --confirm     # actually deletes
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

FILES_TO_DELETE = [
    # Trades / Portfolio
    "storage/trades/trades_master.csv",
    "storage/trades/virtual_portfolio_state.json",
    "storage/trades/learning_exclusions.json",
    # Reports / Analysis
    "reports/full_report.csv",
    "reports/daily_scan_results.csv",
    "reports/paper_trading_daily_report.csv",
    "reports/analysis_history.json",
    "reports/analysis_summary.json",
    "reports/learning_observation_latest.json",
    "reports/learning_picks_history.json",
    "reports/learning_metrics_history.json",
    "reports/optimizer_recommendations_latest.json",
    "reports/sector_performance_latest.json",
    "reports/paper_trading_summary_latest.json",
    # Storage / Reports (logs + caches)
    "storage/reports/learning_observations.json",
    "storage/reports/market_intelligence_log.json",
    "storage/reports/master_report.csv",
    "storage/reports/mi_last_summary_state.json",
    "storage/reports/telegram_dedup.json",
    "storage/reports/macro_headlines_cache.json",
]

DIRECTORIES_TO_DELETE = [
    "storage/trades/diary",
]

# Explicitly never touched, listed here only so it's visible in a diff
# if someone is tempted to add it above.
PROTECTED = [
    "storage/watchlist/nifty500.json",
    "reports/backtest_baseline.json",
    "reports/backtest_result_latest.json",
    "reports/regression_result_latest.json",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually perform the deletion. Without this flag, only a dry-run preview is shown.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("CLEAN SLATE" + (" (DRY RUN — nothing will be deleted)" if not args.confirm else " (LIVE — deleting now)"))
    print("=" * 60)

    found_files = [f for f in FILES_TO_DELETE if Path(f).exists()]
    missing_files = [f for f in FILES_TO_DELETE if not Path(f).exists()]
    found_dirs = [d for d in DIRECTORIES_TO_DELETE if Path(d).exists()]

    print(f"\nFiles to delete ({len(found_files)} found, {len(missing_files)} already absent):")
    for f in found_files:
        size = Path(f).stat().st_size
        print(f"  [{'DELETE' if args.confirm else 'WOULD DELETE'}] {f} ({size:,} bytes)")
    for f in missing_files:
        print(f"  [skip — already absent] {f}")

    print(f"\nDirectories to delete ({len(found_dirs)} found):")
    for d in found_dirs:
        n_files = sum(1 for _ in Path(d).rglob("*") if _.is_file())
        print(f"  [{'DELETE' if args.confirm else 'WOULD DELETE'}] {d}/ ({n_files} files inside)")

    print(f"\nProtected — never touched: {', '.join(PROTECTED)}")

    if not args.confirm:
        print("\nDry run complete. Re-run with --confirm to actually delete these files.")
        return

    print("\nDeleting...")
    for f in found_files:
        Path(f).unlink()
        print(f"  Deleted: {f}")
    for d in found_dirs:
        shutil.rmtree(d)
        print(f"  Deleted: {d}/")

    print("\nDone. All data-accumulation files cleared. Config/watchlist/backtest-baseline untouched.")


if __name__ == "__main__":
    main()
