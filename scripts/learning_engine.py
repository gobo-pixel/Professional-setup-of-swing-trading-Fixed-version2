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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from core.trading_calendar import now_ist  # noqa: E402
from analytics.learning_engine import LearningEngine  # noqa: E402

logger = get_logger(__name__)

OUTPUT_PATH = "reports/learning_observation_latest.json"


def _pct(value) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def _confidence_label(n: int) -> str:
    if n < 50:
        return "LOW"
    if n < 150:
        return "MEDIUM"
    return "HIGH"


def _render_side(accuracy: dict, side: str) -> list[str]:
    n = accuracy.get("trades", 0)
    if n == 0:
        return [f"{side} Trades Closed", "0", "(no closed trades to report yet)"]

    lines = [
        f"{side} Trades Closed",
        f"{n}",
        "Wins",
        f"{accuracy.get('wins', 0)}",
        "Losses",
        f"{accuracy.get('losses', 0)}",
        "Win Rate",
        f"{accuracy.get('win_rate', 0)}%",
        "Average Winner",
        _pct(accuracy.get("avg_winner_pct")),
        "Average Loser",
        _pct(accuracy.get("avg_loser_pct")),
        "Largest Winner",
        _pct(accuracy.get("largest_winner_pct")),
        "Largest Loser",
        _pct(accuracy.get("largest_loser_pct")),
        "Average Holding",
        f"{accuracy.get('avg_holding_days')} Days" if accuracy.get("avg_holding_days") is not None else "N/A",
    ]

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("Observation")
    observations = []
    winner_hold = accuracy.get("avg_winner_holding_days")
    loser_hold = accuracy.get("avg_loser_holding_days")
    if winner_hold is not None and loser_hold is not None:
        if winner_hold > loser_hold * 1.2:
            observations.append("Winning trades generally run much longer than losing trades.")
        elif loser_hold > winner_hold * 1.2:
            observations.append("Losing trades are being held longer than winners — consider tighter stop discipline.")
    largest_loser = accuracy.get("largest_loser_pct")
    if largest_loser is not None:
        if largest_loser >= -5:
            observations.append("Losses remain controlled below 5%.")
        else:
            observations.append(f"Largest loss ({largest_loser}%) exceeds 5% — worth reviewing stop-loss discipline.")
    win_rate = accuracy.get("win_rate", 0)
    if win_rate < 40:
        observations.append("Current win rate is low and requires further investigation.")
    elif win_rate >= 55:
        observations.append("Win rate is currently strong.")
    if not observations:
        observations.append("No strong pattern detected yet — needs more closed trades.")
    for obs in observations:
        lines.append(f"• {obs}")

    lines.append("Dataset Confidence")
    lines.append(_confidence_label(n))
    if n < 50:
        lines.append(f"({n} closed trades only)")

    profit_factor = accuracy.get("profit_factor")
    if profit_factor is not None:
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("Profit Factor")
        lines.append("Gross Profit")
        lines.append(f"₹{accuracy.get('gross_profit', 0)}")
        lines.append("Gross Loss")
        lines.append(f"₹{accuracy.get('gross_loss', 0)}")
        lines.append("Profit Factor")
        lines.append(f"{profit_factor}")

    return lines


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

    if observation["closed_trades_observed"] == 0:
        return

    message_lines = ["🧠 LEARNING SUMMARY", "━━━━━━━━━━━━━━━━━━"]
    message_lines.extend(_render_side(observation["buy_accuracy"], "BUY"))

    sell_acc = observation.get("sell_accuracy", {})
    if sell_acc.get("trades", 0) > 0:
        message_lines.append("")
        message_lines.extend(_render_side(sell_acc, "SELL"))

    notify(
        event_type="learning_summary",
        message="\n".join(message_lines),
        dedup_key=f"learning_summary::{time.strftime('%Y-%m-%d')}::{now_ist().strftime('%H:%M:%S.%f')}",
    )


if __name__ == "__main__":
    main()
