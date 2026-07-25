"""
MODULE 3 — RECOMMENDATION OPTIMIZER (CLI)

Thin command-line wrapper around analytics.optimizer_v2.Optimizer (the
single canonical implementation — no logic duplicated here).

Roadmap coverage (Phase 2, Module 3 — "Recommend only"):
    [x] Weight suggestions    — _news/_fundamental/_technical/_sector/_regime/_accuracy_recommendation()
    [x] Threshold suggestions — _threshold_recommendation(): specific margin-band
                                win-rate comparison (near-threshold vs comfortable
                                passes), not just generic accuracy-based text
    [x] Weak rule detection   — _rule_effectiveness_recommendation(): genuine
                                per-rule (not just aggregate score) win-rate correlation
    [x] Redundant rule detection — _redundant_rule_recommendation(): pairwise
                                rule agreement-rate analysis

No automatic production changes — every recommendation is reviewed and
applied manually by a human.

Usage:
    python scripts/optimizer.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics.optimizer_v2 import Optimizer  # noqa: E402


def main() -> None:
    optimizer = Optimizer()
    recommendations = optimizer.recommend()

    Path("reports").mkdir(exist_ok=True)
    with open("reports/optimizer_recommendations_latest.json", "w") as f:
        json.dump([asdict(r) for r in recommendations], f, indent=2, default=str)

    optimizer.print_report()


if __name__ == "__main__":
    main()
