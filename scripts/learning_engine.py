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

import csv
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf  # noqa: E402

from core.logger import get_logger  # noqa: E402
from core.notifications import notify  # noqa: E402
from core.trading_calendar import now_ist  # noqa: E402
from analytics.learning_engine import LearningEngine  # noqa: E402

logger = get_logger(__name__)

PICKS_HISTORY_PATH = "reports/learning_picks_history.jsonl"
METRICS_HISTORY_PATH = "reports/learning_metrics_history.jsonl"
FULL_REPORT_PATH = "reports/full_report.csv"

OUTPUT_PATH = "reports/learning_observation_latest.json"


def _pct(value) -> str:
    if value is None:
        return "N/A"
    value = value + 0.0  # normalizes -0.0 to 0.0, avoiding a "+-0.0%" display bug
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def _confidence_label(n: int) -> str:
    if n < 50:
        return "LOW"
    if n < 150:
        return "MEDIUM"
    return "HIGH"


def _profit_factor_label(pf) -> str:
    if pf is None:
        return "N/A"
    if pf > 1.5:
        return f"{pf} 🟢 (Good)"
    if pf >= 1.0:
        return f"{pf} 🟡 (Average)"
    return f"{pf} 🔴 (Loss-making)"


def _render_side(accuracy: dict, side: str) -> list[str]:
    n = accuracy.get("trades", 0)
    if n == 0:
        return [f"{side} Trades Closed", "0", "(no closed trades to report yet)"]

    wins = accuracy.get("wins", 0)
    losses = accuracy.get("losses", 0)
    data_issues = accuracy.get("data_quality_issues", 0)
    win_rate = accuracy.get("win_rate")

    lines = [
        f"{side} Trades Closed",
        f"{n}",
        "Wins",
        f"{wins}",
        "Losses",
        f"{losses}",
    ]
    if data_issues:
        lines.append("Data Quality Issues")
        lines.append(f"{data_issues} (PnL unavailable/NaN — excluded from win/loss, not from total)")
    lines.extend([
        "Win Rate",
        f"{win_rate}%" if win_rate is not None else "N/A",
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
    ])

    winner_hold = accuracy.get("avg_winner_holding_days")
    loser_hold = accuracy.get("avg_loser_holding_days")
    if winner_hold is not None or loser_hold is not None:
        lines.append(
            f"  (Winners held {winner_hold if winner_hold is not None else 'N/A'} days avg, "
            f"Losers held {loser_hold if loser_hold is not None else 'N/A'} days avg)"
        )

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("Observation")
    observations = []
    if winner_hold is not None and loser_hold is not None:
        if winner_hold > loser_hold * 1.2:
            observations.append(f"Winning trades ran longer on average ({winner_hold}d vs {loser_hold}d) than losing trades.")
        elif loser_hold > winner_hold * 1.2:
            observations.append(f"Losing trades are being held longer ({loser_hold}d vs {winner_hold}d) — consider tighter stop discipline.")
    largest_loser = accuracy.get("largest_loser_pct")
    if largest_loser is not None:
        if largest_loser >= -5:
            observations.append(f"Losses remain controlled below 5% (worst: {largest_loser}%).")
        else:
            observations.append(f"Largest loss ({largest_loser}%) exceeds 5% — worth reviewing stop-loss discipline.")
    if win_rate is not None:
        if win_rate < 40:
            observations.append(f"{side} win rate ({win_rate}%) is low and requires further investigation.")
        elif win_rate >= 55:
            observations.append(f"{side} win rate ({win_rate}%) is currently strong.")
    if not observations:
        observations.append(f"No strong {side}-side pattern detected yet — needs more closed trades.")
    for obs in observations:
        lines.append(f"• {obs}")

    lines.append("Dataset Confidence")
    lines.append(_confidence_label(n))
    if n < 50:
        lines.append(f"({n} closed trades only)")
    lines.append("Minimum recommended: 100 closed trades")
    lines.append("Recommendations are observational only.")

    profit_factor = accuracy.get("profit_factor")
    gross_profit = accuracy.get("gross_profit")
    gross_loss = accuracy.get("gross_loss")
    if profit_factor is not None or gross_profit is not None:
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("Profit Factor")
        lines.append("Gross Profit")
        lines.append(f"₹{gross_profit}")
        lines.append("Gross Loss")
        lines.append(f"₹{gross_loss}")
        lines.append("Net P&L")
        net = round((gross_profit or 0) - (gross_loss or 0), 2)
        sign = "+" if net >= 0 else ""
        lines.append(f"{sign}₹{net}")
        lines.append("Profit Factor")
        lines.append(_profit_factor_label(profit_factor))

    return lines


def _load_today_report_rows() -> list[dict]:
    path = Path(FULL_REPORT_PATH)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        all_rows = list(csv.DictReader(f))
    dates = {r.get("Date") for r in all_rows if r.get("Date")}
    if not dates:
        return all_rows
    latest_date = max(dates)
    return [r for r in all_rows if r.get("Date") == latest_date]


def _load_picks_history() -> list[dict]:
    path = Path(PICKS_HISTORY_PATH)
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _append_picks_history(entry: dict) -> None:
    Path(PICKS_HISTORY_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(PICKS_HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _yesterday_followup_section(picks_history: list[dict]) -> list[str]:
    today_str = time.strftime("%Y-%m-%d")
    prior_entries = [p for p in picks_history if p.get("date") != today_str]
    if not prior_entries:
        return []
    yesterday_date = max(e["date"] for e in prior_entries)
    yesterday_picks_raw = [e for e in prior_entries if e["date"] == yesterday_date]
    if not yesterday_picks_raw:
        return []

    # De-duplicate: the workflow can run multiple times on the same
    # calendar day (manual tests, retries), each appending a new entry
    # with the same date — keep only the LAST (most recent) entry per
    # (symbol, direction) pair, not every duplicate.
    dedup: dict[tuple, dict] = {}
    for pick in yesterday_picks_raw:
        key = (pick.get("symbol"), pick.get("direction"))
        dedup[key] = pick
    yesterday_picks = list(dedup.values())

    lines = ["📅 Yesterday's Top Picks", ""]
    any_bad = False
    for pick in yesterday_picks:
        symbol = pick.get("symbol")
        entry_price = pick.get("entry_price")
        direction = pick.get("direction")
        if not symbol or not entry_price:
            continue
        try:
            df = yf.download(symbol, period="5d", progress=False, auto_adjust=False)
            if df.empty:
                continue
            current_price = float(df["Close"].iloc[-1])
        except Exception as exc:
            logger.warning("Could not fetch follow-up price for %s: %s", symbol, exc)
            continue

        if math.isnan(current_price):
            logger.warning("Follow-up price for %s came back NaN — skipping.", symbol)
            continue

        pct_change = round((current_price - entry_price) / entry_price * 100, 1)
        # For BUY, a price increase is good; for SELL, a price decrease is good.
        is_good = pct_change > 0 if direction == "BUY" else pct_change < 0
        display_pct = pct_change if direction == "BUY" else -pct_change
        icon = "✅" if is_good else "❌"
        if not is_good:
            any_bad = True
        sign = "+" if display_pct >= 0 else ""
        lines.append(direction)
        lines.append(symbol)
        lines.append(f"{icon} {sign}{display_pct}%")
        lines.append("")

    if len(lines) <= 2:
        return []
    lines.append("Status")
    lines.append("Needs Investigation" if any_bad else "Playing Out Well")
    return lines


def _best_candidate_section(report_rows: list[dict], direction: str) -> list[str]:
    score_col = "BuyOverallScore" if direction == "BUY" else "SellOverallScore"
    tier1_col = "BuyTier1Passed" if direction == "BUY" else "SellTier1Passed"
    tech_col = "BuyTier2Score" if direction == "BUY" else "SellTier2Score"
    candidates = [r for r in report_rows if r.get("Signal") == direction and r.get(score_col)]
    if not candidates:
        return []

    def _score(r):
        try:
            return float(r[score_col])
        except (TypeError, ValueError):
            return -1.0

    best = max(candidates, key=_score)
    emoji = "🏆" if direction == "BUY" else "🎯"
    lines = [f"{emoji} Today's Best {direction}", "", f"Stock        : {best.get('Stock', 'N/A')}"]
    lines.append(f"Score        : {round(_score(best), 1)}")
    if best.get("Confidence"):
        lines.append(f"Confidence   : {best['Confidence']}%")
    if best.get("probability"):
        try:
            lines.append(f"Probability  : {round(float(best['probability']), 1)}%")
        except (TypeError, ValueError):
            pass
    lines.append("")
    lines.append("Why?")
    # Show actual scores, not generic checkmarks — genuinely informative
    # rather than a template. For SELL, "Positive News" is confusing
    # (reads as a bullish signal) — use direction-appropriate wording.
    trend_ok = best.get(tier1_col) == "True"
    news_val = None
    fundamental_val = None
    tech_val = None
    try:
        news_val = float(best.get("NewsScore") or 0)
    except (TypeError, ValueError):
        pass
    try:
        fundamental_val = float(best.get("FundamentalScore") or 0)
    except (TypeError, ValueError):
        pass
    try:
        tech_val = float(best.get(tech_col) or 0)
    except (TypeError, ValueError):
        pass

    if tech_val is not None:
        lines.append(f"Technical Score  : {tech_val}")
    if direction == "BUY":
        if news_val is not None:
            lines.append(f"News Score       : {news_val}")
        if fundamental_val is not None:
            lines.append(f"Fundamental Score: {fundamental_val}")
        if trend_ok:
            lines.append("(Trend gate passed)")
    else:
        # For SELL, frame news/fundamentals as bearish-relevant instead
        # of "positive" (which reads backwards for a sell signal).
        if news_val is not None:
            if news_val == 0:
                lines.append("News              : No news data available for this stock today.")
            elif news_val < 50:
                lines.append(f"News (bearish-supportive): {news_val}")
            else:
                lines.append(f"News Score (not bearish — worth checking): {news_val}")
        if trend_ok:
            lines.append("(Bearish trend gate passed)")

    contributors = []
    if tech_val is not None and tech_val >= 60:
        contributors.append("Technical")
    if direction == "BUY" and fundamental_val is not None and fundamental_val >= 60:
        contributors.append("Fundamentals")
    if direction == "BUY" and news_val is not None and news_val >= 60:
        contributors.append("News")
    if contributors:
        lines.append(f"Reason: {' + '.join(contributors)} were the strongest contributors.")

    return lines


def _load_metrics_history() -> list[dict]:
    path = Path(METRICS_HISTORY_PATH)
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _append_metrics_history(entry: dict) -> None:
    Path(METRICS_HISTORY_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _trend_vs_yesterday_section(observation: dict, metrics_history: list[dict]) -> list[str]:
    today_str = time.strftime("%Y-%m-%d")
    prior_entries = [m for m in metrics_history if m.get("date") != today_str]
    if not prior_entries:
        return []
    yesterday = prior_entries[-1]

    lines = ["📊 Trend vs Yesterday"]
    for direction, label in (("buy_accuracy", "BUY"), ("sell_accuracy", "SELL")):
        today_acc = observation.get(direction, {})
        today_n = today_acc.get("trades", 0)
        yesterday_n = yesterday.get(f"{label.lower()}_trades", 0)
        if today_n == 0 and yesterday_n == 0:
            continue
        if yesterday_n:
            pct_change = round((today_n - yesterday_n) / yesterday_n * 100, 1)
            arrow = "↑" if pct_change > 0 else ("↓" if pct_change < 0 else "→")
            lines.append(f"{label} Trades Closed: {yesterday_n} → {today_n}  {arrow} {pct_change:+.1f}%")
        else:
            lines.append(f"{label} Trades Closed: {yesterday_n} → {today_n}")
    return lines if len(lines) > 1 else []


def _best_worst_trade_section(observation: dict) -> list[str]:
    bw = observation.get("best_worst_trade", {})
    if not bw:
        return []
    lines = []
    best, worst = bw.get("best", {}), bw.get("worst", {})
    if best:
        sign = "+" if best["pct"] >= 0 else ""
        lines.append("🏅 Best Closed Trade")
        lines.append(f"{best['symbol']} ({best['direction']})")
        lines.append(f"{sign}{best['pct']}%")
        lines.append("")
    if worst:
        sign = "+" if worst["pct"] >= 0 else ""
        lines.append("💥 Worst Closed Trade")
        lines.append(f"{worst['symbol']} ({worst['direction']})")
        lines.append(f"{sign}{worst['pct']}%")
    return lines


def _exit_reason_section(observation: dict) -> list[str]:
    breakdown = observation.get("exit_reason_breakdown", {})
    if not breakdown:
        return []
    lines = ["Most Common Exit"]
    for reason, count in breakdown.items():
        lines.append(reason)
        lines.append(f"{count}")
    return lines


def _strategy_alert_section(observation: dict, metrics_history: list[dict]) -> list[str]:
    today_str = time.strftime("%Y-%m-%d")
    prior_entries = [m for m in metrics_history if m.get("date") != today_str]
    previous = prior_entries[-1] if prior_entries else None

    lines = []
    for direction, label in (("buy_accuracy", "BUY"), ("sell_accuracy", "SELL")):
        acc = observation.get(direction, {})
        n = acc.get("trades", 0)
        wr = acc.get("win_rate")
        if n < 10 or wr is None:
            continue
        MIN_WIN_RATE = 40
        prev_wr = previous.get(f"{label.lower()}_win_rate") if previous else None
        prev_line = f"Previous       : {prev_wr}%" if prev_wr is not None else "Previous       : N/A (no prior data)"
        if wr < MIN_WIN_RATE:
            if lines:
                lines.append("")
            lines.append(f"🚨 ALERT — {label} Win Rate")
            lines.append(prev_line)
            lines.append(f"Today          : {wr}%")
            lines.append(f"Threshold      : {MIN_WIN_RATE}%")
            lines.append("Status         : 🔴")
            lines.append("Action")
            lines.append("Investigate strategy before optimization.")
        elif wr >= 55:
            if lines:
                lines.append("")
            lines.append(f"🟢 ALERT — {label} Win Rate")
            lines.append(prev_line)
            lines.append(f"Today          : {wr}%")
            lines.append("Status         : 🟢 Healthy")
    return lines


def _ai_conclusion(observation: dict) -> list[str]:
    """3-4 plain sentences synthesizing the whole observation — the
    reader's takeaway without needing to parse every section above."""
    lines = ["🧠 AI Conclusion"]
    sentences = []

    buy_acc = observation.get("buy_accuracy", {})
    sell_acc = observation.get("sell_accuracy", {})

    # Overall verdict
    sides_summary = []
    for label, acc in (("BUY", buy_acc), ("SELL", sell_acc)):
        n = acc.get("trades", 0)
        wr = acc.get("win_rate")
        if n > 0 and wr is not None:
            sides_summary.append((label, n, wr))
    if sides_summary:
        parts = [f"{label} win rate is {wr}% over {n} trades" for label, n, wr in sides_summary]
        sentences.append("Overall, " + " and ".join(parts) + ".")

    # Biggest weak dimension across sector/regime/news/technical
    weak_points = []
    for sector, stats in observation.get("sector_performance", {}).items():
        if stats.get("trades", 0) >= 5 and stats.get("win_rate", 100) == 0:
            weak_points.append(f"{sector} sector (0% over {stats['trades']} trades)")
    for regime, stats in observation.get("regime_performance", {}).items():
        if stats.get("trades", 0) >= 5 and stats.get("win_rate", 100) == 0:
            weak_points.append(f"{regime} regime (0% over {stats['trades']} trades)")
    if weak_points:
        sentences.append(f"The weakest spot right now is {weak_points[0]}.")

    # Directional recommendation
    total_n = buy_acc.get("trades", 0) + sell_acc.get("trades", 0)
    lowest_confidence = total_n < 50
    if lowest_confidence:
        sentences.append("Dataset is still small, so this should inform monitoring, not strategy changes yet.")
        sentences.append("No strategy changes recommended yet.")
    else:
        any_critical = any(
            acc.get("trades", 0) >= 10 and (acc.get("win_rate") or 100) < 20
            for acc in (buy_acc, sell_acc)
        )
        if any_critical:
            sentences.append("The dataset is now large enough that this weak performance deserves a closer strategy review.")
        else:
            sentences.append("Nothing here crosses the threshold for a strategy change — keep monitoring.")

    if not sentences:
        sentences.append("Not enough data yet to draw a clear conclusion.")

    for s in sentences:
        lines.append(s)
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

    # ---------------- Best Trade Candidate + Yesterday Follow-up setup ----------------
    # Load history BEFORE appending today's entries, so comparisons are
    # against genuinely prior days, not today itself.
    today_report_rows = _load_today_report_rows()
    picks_history = _load_picks_history()
    metrics_history = _load_metrics_history()

    today_str = time.strftime("%Y-%m-%d")
    for direction in ("BUY", "SELL"):
        score_col = "BuyOverallScore" if direction == "BUY" else "SellOverallScore"
        candidates = [r for r in today_report_rows if r.get("Signal") == direction and r.get(score_col)]
        if not candidates:
            continue
        try:
            best = max(candidates, key=lambda r: float(r[score_col]))
            entry_price = float(best.get("EntryPrice") or 0)
            if entry_price > 0:
                _append_picks_history({
                    "date": today_str, "symbol": best.get("Stock"), "direction": direction,
                    "entry_price": entry_price,
                })
        except (TypeError, ValueError):
            continue

    buy_acc, sell_acc = observation.get("buy_accuracy", {}), observation.get("sell_accuracy", {})
    _append_metrics_history({
        "date": today_str, "buy_trades": buy_acc.get("trades", 0), "sell_trades": sell_acc.get("trades", 0),
        "buy_win_rate": buy_acc.get("win_rate"), "sell_win_rate": sell_acc.get("win_rate"),
    })

    message_lines = ["🧠 LEARNING SUMMARY", "━━━━━━━━━━━━━━━━━━"]

    for direction in ("BUY", "SELL"):
        section = _best_candidate_section(today_report_rows, direction)
        if section:
            message_lines.extend(section)
            message_lines.append("━━━━━━━━━━━━━━━━━━")

    followup_section = _yesterday_followup_section(picks_history)
    if followup_section:
        message_lines.extend(followup_section)
        message_lines.append("━━━━━━━━━━━━━━━━━━")

    if observation["closed_trades_observed"] == 0:
        notify(
            event_type="learning_summary",
            message="\n".join(message_lines),
            dedup_key=f"learning_summary::{today_str}::{now_ist().strftime('%H:%M:%S.%f')}",
        )
        return

    message_lines.extend(_render_side(observation["buy_accuracy"], "BUY"))
    if sell_acc.get("trades", 0) > 0:
        message_lines.append("")
        message_lines.extend(_render_side(sell_acc, "SELL"))
    message_lines.append("━━━━━━━━━━━━━━━━━━")

    trend_section = _trend_vs_yesterday_section(observation, metrics_history)
    if trend_section:
        message_lines.extend(trend_section)
        message_lines.append("━━━━━━━━━━━━━━━━━━")

    alert_section = _strategy_alert_section(observation, metrics_history)
    if alert_section:
        message_lines.extend(alert_section)
        message_lines.append("━━━━━━━━━━━━━━━━━━")

    bw_section = _best_worst_trade_section(observation)
    if bw_section:
        message_lines.extend(bw_section)
        message_lines.append("━━━━━━━━━━━━━━━━━━")

    exit_section = _exit_reason_section(observation)
    if exit_section:
        message_lines.extend(exit_section)
        message_lines.append("━━━━━━━━━━━━━━━━━━")

    message_lines.extend(_ai_conclusion(observation))

    notify(
        event_type="learning_summary",
        message="\n".join(message_lines),
        dedup_key=f"learning_summary::{today_str}::{now_ist().strftime('%H:%M:%S.%f')}",
    )


if __name__ == "__main__":
    main()
