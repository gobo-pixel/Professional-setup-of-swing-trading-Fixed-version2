"""
DIAGNOSTIC — Trace row-count through the REAL production pipeline.

We've confirmed the raw fetch returns 273 rows (comfortably above the
250 threshold) for symbols like ICICIBANK.NS, yet validation_engine.py
still rejects them for "Insufficient historical candles." This
instruments the ACTUAL pipeline (data_engine.fetch -> features.generate
-> regime.evaluate -> the exact dataframe validation_engine sees) for
one real symbol, printing the row count at every single stage, to
pinpoint exactly where (if anywhere) rows get dropped.

Usage:
    python scripts/diagnose_row_count_pipeline.py
    python scripts/diagnose_row_count_pipeline.py --symbol RELIANCE.NS
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.data_engine import DataEngine  # noqa: E402
from features.feature_engineering import FeatureEngineeringEngine  # noqa: E402
from market.market_regime import MarketRegimeEngine  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Single symbol to trace")
    parser.add_argument(
        "--symbols", default=None,
        help="Comma-separated list of symbols to trace (overrides --symbol)",
    )
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = [args.symbol or "ICICIBANK.NS"]

    data_engine = DataEngine()
    features = FeatureEngineeringEngine()
    regime = MarketRegimeEngine()

    for symbol in symbols:
        print(f"\n{'=' * 20} {symbol} {'=' * 20}")
        try:
            bundle = data_engine.fetch(symbol=symbol)
            dataframe = bundle.market
            print(f"Stage 1 — bundle.market (raw fetch): {len(dataframe)} rows")

            dataframe_2 = features.generate(dataframe)
            if len(dataframe_2) != len(dataframe):
                print(f"  !!! ROW COUNT CHANGED after features: {len(dataframe)} -> {len(dataframe_2)}")
            else:
                print(f"Stage 2 — after features.generate(): {len(dataframe_2)} rows (unchanged)")

            dataframe_3 = regime.evaluate(dataframe_2)
            if len(dataframe_3) != len(dataframe_2):
                print(f"  !!! ROW COUNT CHANGED after regime: {len(dataframe_2)} -> {len(dataframe_3)}")
            else:
                print(f"Stage 3 — after regime.evaluate(): {len(dataframe_3)} rows (unchanged)")

            passes = len(dataframe_3) >= 250
            print(f"FINAL: {len(dataframe_3)} rows — passes minimum_history(>=250)? {passes}")
        except Exception as exc:
            print(f"  EXCEPTION for {symbol}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
