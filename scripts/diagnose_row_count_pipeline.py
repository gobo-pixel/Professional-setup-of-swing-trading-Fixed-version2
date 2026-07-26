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
    parser.add_argument("--symbol", default="ICICIBANK.NS")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"=== Tracing row-count through the real pipeline for {symbol} ===\n")

    data_engine = DataEngine()
    bundle = data_engine.fetch(symbol=symbol)
    dataframe = bundle.market
    print(f"Stage 1 — bundle.market (raw fetch): {len(dataframe)} rows")
    print(f"  columns: {list(dataframe.columns)}")
    print(f"  first timestamp: {dataframe.iloc[0].get('timestamp')}")
    print(f"  last timestamp: {dataframe.iloc[-1].get('timestamp')}")

    features = FeatureEngineeringEngine()
    dataframe_2 = features.generate(dataframe)
    print(f"\nStage 2 — after features.generate(): {len(dataframe_2)} rows")
    if len(dataframe_2) != len(dataframe):
        print(f"  !!! ROW COUNT CHANGED: {len(dataframe)} -> {len(dataframe_2)}")

    regime = MarketRegimeEngine()
    dataframe_3 = regime.evaluate(dataframe_2)
    print(f"\nStage 3 — after regime.evaluate(): {len(dataframe_3)} rows")
    if len(dataframe_3) != len(dataframe_2):
        print(f"  !!! ROW COUNT CHANGED: {len(dataframe_2)} -> {len(dataframe_3)}")

    print(f"\n=== FINAL row count reaching validation_engine: {len(dataframe_3)} ===")
    print(f"=== Passes minimum_history (>=250)? {len(dataframe_3) >= 250} ===")


if __name__ == "__main__":
    main()
