"""
MODULE 2 — LEARNING ENGINE (CLI)

Thin command-line wrapper around analytics.learning_engine.LearningEngine
(the single canonical implementation — no logic duplicated here).

Roadmap coverage (Phase 2, Module 2 — "Observe only"):
    [x] Rule effectiveness       — _rule_effectiveness(): genuine per-rule (all ~39
                                    individual technical checks) win-rate correlation
    [x] Sector performance       — _sector_performance()
    [x] Regime performance       — _regime_performance()
    [x] Technical effectiveness  — _technical_effectiveness()
    [x] Fundamental effectiveness — _fundamental_effectiveness()
    [x] News effectiveness       — _news_effectiveness()
    [x] Historical learning database — _append_observation() (append-only JSONL)
    (also computes _redundant_rule_pairs() and _threshold_sensitivity(),
    feeding Module 3's Optimizer recommendations)

This module ONLY observes — it never changes strategy code or
production settings.

Usage:
    python scripts/learning_engine.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from analytics.learning_engine import LearningEngine  # noqa: E402

logger = get_logger(__name__)

OUTPUT_PATH = "reports/learning_observation_latest.json"


def main() -> None:
    engine = LearningEngine()
    observation = engine.observe()

    Path("reports").mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(observation, f, indent=2, default=str)
    logger.info("Learning observation written to %s", OUTPUT_PATH)

    print("=" * 60)
    print("LEARNING ENGINE — OBSERVATION SUMMARY")
    print("=" * 60)
    print(f"Closed trades observed : {observation['closed_trades_observed']}")
    print(f"BUY accuracy           : {observation['buy_accuracy']}")
    print(f"SELL accuracy          : {observation['sell_accuracy']}")
    print(f"Sector performance     : {observation['sector_performance']}")
    print(f"Regime performance     : {observation['regime_performance']}")
    print(f"News effectiveness     : {observation['news_effectiveness']}")
    print(f"Fundamental effectiveness: {observation['fundamental_effectiveness']}")
    print(f"Technical effectiveness : {observation['technical_effectiveness']}")


if __name__ == "__main__":
    main()
