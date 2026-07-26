"""
MODULE 3 — RECOMMENDATION OPTIMIZER (CLI)

Thin command-line wrapper around analytics.optimizer_v2.Optimizer /
analytics.learning_engine.LearningEngine (canonical implementations —
no logic duplicated here, this file only formats the Telegram message).

Roadmap coverage (Phase 2, Module 3 — "Recommend only"):
    [x] Weight suggestions    — per-dimension observations below
    [x] Threshold suggestions — _threshold_recommendation() (JSON output only)
    [x] Weak rule detection   — _rule_effectiveness_recommendation() (JSON output only)
    [x] Redundant rule detection — _redundant_rule_recommendation() (JSON output only)

No automatic production changes — every recommendation is reviewed and
applied manually by a human. Every number in this report is followed by
a plain-language "matlab" explaining what it means, not left as a raw
statistic.

Usage:
    python scripts/optimizer.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from core.trading_calendar import now_ist  # noqa: E402
from analytics.learning_engine import LearningEngine  # noqa: E402
from analytics.optimizer_v2 import Optimizer  # noqa: E402

logger = get_logger(__name__)

MIN_TRADES_FOR_DECENT_SAMPLE = 10


def _wr(value) -> str:
    return "N/A" if value is None else f"{value}%"


def _news_section(obs: dict, flags: list) -> list[str]:
    news = obs.get("news_effectiveness", {})
    with_n = news.get("with_news_trades", 0)
    without_n = news.get("without_news_trades", 0)
    with_wr = news.get("with_news_win_rate")
    without_wr = news.get("without_news_win_rate")
    if with_n + without_n == 0:
        return []

    lines = ["📰 NEWS", f"{obs.get('closed_trades_observed', 0)} closed trades me..."]
    lines.append(f"• News wali trades ({with_n}) sirf {_wr(with_wr)} jeeti." if with_wr is not None
                 else f"• News wali trades: {with_n} (win rate N/A, sample nahi hai).")
    lines.append(f"• News ke bina trades ({without_n}) {_wr(without_wr)} jeeti." if without_wr is not None
                 else f"• News ke bina trades: {without_n} (win rate N/A, sample nahi hai).")

    lines.append("👉 Observation:")
    low_sample = min(with_n, without_n) < MIN_TRADES_FOR_DECENT_SAMPLE
    if with_wr is not None and without_wr is not None:
        if without_wr - with_wr > 20:
            lines.append("Abhi lag raha hai News score decision improve nahi kar raha.")
            flags.append(("WATCH", f"News ka impact doubtful hai ({_wr(with_wr)} vs {_wr(without_wr)})."))
        elif with_wr - without_wr > 20:
            lines.append("News wali trades genuinely better perform kar rahi hain.")
            flags.append(("GOOD", "News score decision improve kar raha hai."))
        else:
            lines.append("News ka clear impact abhi nahi dikh raha, dono similar hain.")
    else:
        lines.append("Ek side ka data itna kam hai ki comparison nahi ho sakta.")

    if low_sample:
        lines.append("⚠️ Confidence: LOW")
        smaller_side = "Without-news" if without_n < with_n else "With-news"
        lines.append(f"({smaller_side} trades bahut kam hain, isliye abhi conclusion final nahi.)")
    return lines


def _technical_section(obs: dict, flags: list) -> list[str]:
    tech = obs.get("technical_effectiveness", {})
    high_n = tech.get("high_technical_trades", 0)
    low_n = tech.get("low_technical_trades", 0)
    high_wr = tech.get("high_technical_win_rate")
    low_wr = tech.get("low_technical_win_rate")
    if high_n + low_n == 0:
        return []

    lines = ["📈 TECHNICAL SCORE"]
    lines.append(f"• High Technical Score wali trades ({high_n})")
    lines.append(f"  Win Rate: {_wr(high_wr)}")
    lines.append(f"• Low Technical Score wali trades ({low_n})")
    lines.append(f"  Win Rate: {_wr(low_wr)}")

    lines.append("👉 Observation:")
    if high_wr is not None and low_wr is not None:
        if high_wr > low_wr:
            lines.append("Technical score useful lag raha hai.")
            lines.append("High score wali trades better perform kar rahi hain.")
            flags.append(("GOOD", "Technical Score useful lag raha hai."))
        elif low_wr > high_wr:
            lines.append("Ulta pattern dikh raha hai — high-score trades better perform nahi kar rahi.")
            flags.append(("WATCH", "Technical Score ka signal ulta dikh raha hai."))
        else:
            lines.append("High aur low score wali trades me koi bada farak nahi.")
    else:
        lines.append("Ek side ka data itna kam hai ki comparison nahi ho sakta.")
    return lines


def _sector_section(obs: dict, flags: list) -> list[str]:
    sectors = obs.get("sector_performance", {})
    if not sectors:
        return []
    lines = ["🏦 SECTOR"]
    for i, (sector, stats) in enumerate(sorted(sectors.items(), key=lambda kv: kv[1]["trades"], reverse=True)):
        if i > 0:
            lines.append("")
        trades, wins, wr = stats["trades"], stats.get("wins", 0), stats["win_rate"]
        lines.append(sector)
        lines.append(f"Trades: {trades}")
        lines.append(f"Wins: {wins}")
        lines.append(f"Win Rate: {wr}%")
        lines.append("👉 Observation:")
        if trades >= 5 and wr == 0:
            lines.append(f"Is period me {sector} sector bahut weak raha.")
            flags.append(("INVESTIGATE", f"{sector} me {trades} me se {wins} trade jeeti."))
        elif trades >= 5 and wr >= 60:
            lines.append(f"{sector} sector achha perform kar raha hai.")
            flags.append(("GOOD", f"{sector} sector strong hai ({wr}% win rate)."))
        elif trades < 5:
            lines.append(f"Sirf {trades} trades hain — abhi conclusion nikalna jaldbaazi hogi.")
        else:
            lines.append(f"{sector} sector ka performance average hai.")
    return lines


def _regime_section(obs: dict, flags: list) -> list[str]:
    regimes = obs.get("regime_performance", {})
    if not regimes:
        return []
    label_map = {"BULL": "Bull Market", "BEAR": "Bear Market", "SIDEWAYS": "Sideways Market"}
    lines = ["📊 MARKET REGIME"]
    for i, (regime, stats) in enumerate(regimes.items()):
        if i > 0:
            lines.append("")
        trades, wins, wr = stats["trades"], stats.get("wins", 0), stats["win_rate"]
        label = label_map.get(regime, regime)
        lines.append(label)
        lines.append(f"Trades: {trades}")
        lines.append(f"Win Rate: {wr}%")
        lines.append("👉 Observation:")
        if trades >= 5 and wr == 0:
            lines.append(f"Current strategy {label.lower()} me struggle kar rahi hai.")
            flags.append(("INVESTIGATE", f"{label} me {trades} trades, 0 wins."))
        elif trades >= 5 and wr < 20:
            lines.append(f"{label} me performance expected se kaafi kam hai.")
            flags.append(("WATCH", f"{label} me sirf {wr}% win rate."))
        elif trades >= 5 and wr >= 40:
            lines.append(f"{label} me performance expected se achhi/zyada hai.")
        else:
            lines.append(f"Sirf {trades} trades hain — abhi conclusion nikalna jaldbaazi hogi.")
    return lines


def _overall_section(obs: dict, flags: list) -> list[str]:
    lines = []
    for direction, label in (("buy_accuracy", "BUY"), ("sell_accuracy", "SELL")):
        acc = obs.get(direction, {})
        n = acc.get("trades", 0)
        if n == 0:
            continue
        wins, losses, wr = acc.get("wins", 0), acc.get("losses", 0), acc.get("win_rate", 0)
        data_issues = acc.get("data_quality_issues", 0)
        lines.append(f"🎯 OVERALL {label} PERFORMANCE")
        lines.append(f"{label} Trades Closed: {n}")
        lines.append(f"Wins: {wins}")
        lines.append(f"Losses: {losses}")
        if data_issues:
            lines.append(f"Data Quality Issues: {data_issues} (PnL unavailable/NaN — excluded from win/loss)")
        lines.append(f"Win Rate: {wr}%" if wr is not None else "Win Rate: N/A")
        lines.append("👉 Matlab:")
        classifiable = wins + losses
        extra_note = f" ({data_issues} aur trades ka data missing/NaN tha)." if data_issues else "."
        lines.append(f"{classifiable} classifiable {label} trades me sirf {wins} profitable rahi{extra_note}")
        lines.append("👉 Observation:")
        if wr is not None and n >= MIN_TRADES_FOR_DECENT_SAMPLE and wr < 20:
            lines.append(f"Current {label} strategy ki performance bahut weak dikh rahi hai.")
            flags.append(("CRITICAL", f"{label} strategy — {n} trades, sirf {wins} winners."))
        elif wr is not None and n >= MIN_TRADES_FOR_DECENT_SAMPLE and wr >= 55:
            lines.append(f"Current {label} strategy ki performance strong dikh rahi hai.")
            flags.append(("GOOD", f"{label} strategy — {wr}% win rate over {n} trades."))
        else:
            lines.append(f"{label} strategy abhi average perform kar rahi hai.")
        lines.append("")
    return lines[:-1] if lines else lines  # drop trailing blank


def main() -> None:
    optimizer = Optimizer()
    recommendations = optimizer.recommend()

    Path("reports").mkdir(exist_ok=True)
    with open("reports/optimizer_recommendations_latest.json", "w") as f:
        json.dump([asdict(r) for r in recommendations], f, indent=2, default=str)

    optimizer.print_report()

    learning_engine = LearningEngine()
    history = learning_engine.get_history()
    if not history:
        return
    obs = history[-1]
    if obs.get("closed_trades_observed", 0) == 0:
        return

    flags: list[tuple[str, str]] = []
    message_lines = ["🟡 OPTIMIZER OBSERVATIONS", "━━━━━━━━━━━━━━━━━━━━━━"]

    for section_fn in (_news_section, _technical_section, _sector_section, _regime_section, _overall_section):
        section = section_fn(obs, flags)
        if section:
            message_lines.extend(section)
            message_lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    message_lines.append("⚠️ IMPORTANT")
    message_lines.append("Ye sirf observations hain.")
    message_lines.append("❌ Strategy automatically change nahi ki gayi.")
    message_lines.append("Current dataset:")
    message_lines.append(f"{obs.get('closed_trades_observed', 0)} closed trades")
    message_lines.append("Recommendation:")
    message_lines.append("Aur data collect hone do, uske baad hi weights ya strategy modify karo.")

    if flags:
        message_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        emoji_map = {"GOOD": "🟢", "WATCH": "🟡", "INVESTIGATE": "🔴", "CRITICAL": "🔴"}
        for level in ("GOOD", "WATCH", "INVESTIGATE", "CRITICAL"):
            level_flags = [reason for lvl, reason in flags if lvl == level]
            if not level_flags:
                continue
            message_lines.append(f"{emoji_map[level]} {level}")
            for reason in level_flags:
                message_lines.append(reason)
            message_lines.append("-----------------------")

    notify(
        event_type="optimizer_recommendation",
        message="\n".join(message_lines),
        severity="🔴 HIGH" if any(lvl == "CRITICAL" for lvl, _ in flags) else "🟡 MEDIUM",
        dedup_key=f"optimizer_recommendation::{time.strftime('%Y-%m-%d')}::{now_ist().strftime('%H:%M:%S.%f')}",
    )


if __name__ == "__main__":
    main()
