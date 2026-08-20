"""
TEMPORARY TRIAL STRATEGY — EMA(26/70/240) trend-alignment.

Built at the user's explicit request as a short-term EXPERIMENT, kept
completely isolated from the live production pipeline
(execution/scanner.py, strategy/buy_strategy.py, strategy/sell_strategy.py,
paper_trading/paper_trading_engine.py, risk/*). This script imports
none of those and is never called by any production workflow — it can
be deleted or disabled at any time without touching production. It
DOES import features/indicators/smoothing.py's wilders_smoothing — a
pure math helper, not part of the strategy/decision engine — so ATR is
computed with the exact same (real-data-audited) formula production
uses, instead of re-deriving a second, possibly-diverging copy.

SIGNAL (all three must agree — AND logic, per explicit instruction):
    BUY      : close > ema26  AND close > ema70  AND close > ema240
    SELL     : close < ema26  AND close < ema70  AND close < ema240
    NO_TRADE : anything else (mixed / conflicting EMAs)

DATA: interval="1d", period="1mo" (per explicit instruction).
CAVEAT (flagged loudly, not silently "fixed"): a 240-period EMA
normally needs ~240 trading days of history to be a properly warmed-up
value. period="1mo" returns roughly 21 daily candles — far short of
240 — so ema_240 here is the EMA *formula* applied to a short window,
not a genuinely mature 240-day EMA. This script prints a warning about
this every run; see main().

RISK MANAGEMENT (fixed-percent, per explicit instruction — NOT the
ATR-based STOP/TARGET model in risk/stop_target.py, deliberately,
since this is a separate experiment):
    initial stop-loss = entry -+ 1.5%   (BUY: below entry, SELL: above)
    target1            = entry -+ 3.0%   (BUY: above entry, SELL: below)
    Once price crosses target1, stop-loss is moved to target1 (locks
    in the 3% gain). No further fixed target after that — the position
    keeps running until the (now-shifted) stop-loss is eventually hit,
    per the user's explicit "let it run" choice.

POSITION SIZING (capital tracking, per explicit follow-up request):
adapted from risk/position_sizing.py's real ATR+Kelly formula, reusing
every piece that can be honestly computed from data this trial
actually has:
    - kelly_fraction: FIXED at FALLBACK_KELLY_FRACTION (0.5) — this is
      not a simplification unique to the trial; production ITSELF
      currently runs with KELLY_CALIBRATED=False and uses this exact
      same flat fallback (no calibration table exists yet anywhere in
      this codebase).
    - volatility_adjustment: from a REAL ATR(14) computed here (Wilder's
      smoothing, same formula as features/indicators/volatility.py).
    - liquidity_adjustment: from REAL average volume computed here.
    - confidence_adjustment / risk_adjustment: production derives these
      from decision.confidence / risk.total_risk, which come from the
      tier2/tier3 scoring + risk engines this trial deliberately does
      NOT have. Feeding fabricated numbers into those slots would be
      exactly the "sized off fabricated confidence" bug
      risk/position_sizing.py's own comments describe fixing — so both
      are left at neutral 1.0 here (documented as "not modeled", not a
      computed score) rather than invented.
    - ATR-based risk-budget quantity check reuses this trial's own real
      stop_distance (the fixed 1.5%), not production's ATR-based stop.
A trade whose sized quantity comes out to 0 (capital/risk budget can't
afford even 1 share) is NOT opened — same "quantity can legitimately
be 0" behavior as production, not silently forced to 1 share.

Capital is tracked in the SAME state.json (see below): starting
capital defaults to STARTING_CAPITAL only the very first time this
runs (no state file yet) — every run after that reads/writes the real
persisted available_cash, it is never re-defaulted.

STATE / HISTORY: storage/trial_trades/state.json (open positions +
capital) and storage/trial_trades/trade_log.csv (closed trades) —
COMPLETELY SEPARATE from production's storage/trades/... paths, so
analytics/learning_engine.py, analytics/optimizer.py and the
backtester never see or mix this data (those modules hardcode
"storage/trades/..." paths; verified no generic directory scan exists
anywhere in that code).

TELEGRAM: reuses output/telegram_alert.py and the same
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets already configured for
the production workflows — no new bot/setup needed. Exactly two kinds
of message are sent per run (a scan summary and one-or-few
holding-status messages) — never one message per signal/position.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.logger import get_logger
from data.market_data import MarketDataProvider
from data.watchlist import WatchlistManager
from features.indicators.smoothing import wilders_smoothing
from output.telegram_alert import TelegramAlert

logger = get_logger(__name__)

INTERVAL = "1d"
PERIOD = "1mo"

EMA_FAST = 26
EMA_MID = 70
EMA_SLOW = 240

STOP_LOSS_PERCENT = 0.015
TARGET1_PERCENT = 0.03

ATR_PERIOD = 14
VOLUME_AVG_PERIOD = 20

# Capital / position sizing — adapted from risk/position_sizing.py, see
# module docstring above for exactly which pieces are real vs. neutral.
STARTING_CAPITAL = 1_000_000.0
MAX_RISK_PER_TRADE = 0.02
MIN_CAPITAL_ALLOCATION = 0.02
MAX_CAPITAL_ALLOCATION = 0.20
MIN_POSITION_VALUE = 5_000.0
MAX_POSITION_VALUE = 500_000.0
FALLBACK_KELLY_FRACTION = 0.5

WATCHLIST_PATH = "storage/watchlist/nifty500.json"
STATE_PATH = Path("storage/trial_trades/state.json")
TRADE_LOG_PATH = Path("storage/trial_trades/trade_log.csv")

TRADE_LOG_FIELDS = [
    "trade_id",
    "symbol",
    "direction",
    "quantity",
    "entry_price",
    "entry_time",
    "invested_amount",
    "exit_price",
    "exit_time",
    "exit_reason",
    "target1_hit",
    "pnl_percent",
    "pnl_amount",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "open_positions": {},
        "capital": {
            "starting_capital": STARTING_CAPITAL,
            "available_cash": STARTING_CAPITAL,
        },
    }


def load_state(path: Path = STATE_PATH) -> dict:
    """Never fabricates data — a missing/unreadable state file simply
    means "first run ever, start from STARTING_CAPITAL", not a
    silently-invented mid-experiment default. Every run after the
    first reads back the real persisted available_cash."""
    if not path.exists():
        return _default_state()

    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    if "open_positions" not in data:
        data["open_positions"] = {}

    if "capital" not in data:
        data["capital"] = {
            "starting_capital": STARTING_CAPITAL,
            "available_cash": STARTING_CAPITAL,
        }

    return data


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=2)


def append_trade_log(row: dict, path: Path = TRADE_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()

    with path.open("a", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=TRADE_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def compute_emas(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Adds ema_26 / ema_70 / ema_240 columns. Deliberately NOT reusing
    features/indicators/moving_average.py (which only computes
    9/20/50/100/200) so production's shared indicator module stays
    untouched by this trial."""
    df = dataframe.copy()
    for period in (EMA_FAST, EMA_MID, EMA_SLOW):
        df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def compute_atr(dataframe: pd.DataFrame) -> pd.Series:
    """ATR(14), Wilder's smoothing — the exact same formula as
    production's features/indicators/volatility.py (a real-data-audited
    fix, see PHASE30_NOTES.md), reused via the shared smoothing helper
    rather than re-deriving a second copy that could drift."""
    high = dataframe["high"]
    low = dataframe["low"]
    close = dataframe["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return wilders_smoothing(true_range, ATR_PERIOD)


def compute_volume_average(dataframe: pd.DataFrame) -> pd.Series:
    """Average volume over VOLUME_AVG_PERIOD bars. Uses min_periods=1
    (NOT production's min_periods=20) deliberately — period="1mo"
    typically returns ~21 rows, barely enough for a full 20-bar window
    at the latest row and not enough earlier. This is an honest
    "average of whatever real history is actually available", clearly
    weaker than a true 20-day average early on — flagged here rather
    than silently matching production's stricter requirement (which
    would make liquidity data NaN this trial almost never has time to
    fill in a 21-candle window)."""
    return dataframe["volume"].rolling(VOLUME_AVG_PERIOD, min_periods=1).mean()


def evaluate_signal(latest: pd.Series) -> str:
    """Returns 'BUY', 'SELL', or 'NO_TRADE'. All three EMAs must agree
    with price direction (AND logic) — this is intentionally strict
    (fewer, higher-conviction signals), per explicit instruction."""
    close = latest["close"]
    ema_fast = latest[f"ema_{EMA_FAST}"]
    ema_mid = latest[f"ema_{EMA_MID}"]
    ema_slow = latest[f"ema_{EMA_SLOW}"]

    if pd.isna(ema_fast) or pd.isna(ema_mid) or pd.isna(ema_slow):
        return "NO_TRADE"

    if close > ema_fast and close > ema_mid and close > ema_slow:
        return "BUY"

    if close < ema_fast and close < ema_mid and close < ema_slow:
        return "SELL"

    return "NO_TRADE"


def compute_initial_stop_target(direction: str, entry_price: float) -> tuple[float, float]:
    """Fixed-percent stop/target, mirrored for BUY and SELL — see
    module docstring for the exact rule."""
    if direction == "BUY":
        stop_loss = round(entry_price * (1 - STOP_LOSS_PERCENT), 2)
        target1 = round(entry_price * (1 + TARGET1_PERCENT), 2)
    else:
        stop_loss = round(entry_price * (1 + STOP_LOSS_PERCENT), 2)
        target1 = round(entry_price * (1 - TARGET1_PERCENT), 2)
    return stop_loss, target1


def compute_position_size(
    entry_price: float,
    stop_distance: float,
    atr_percent: float,
    average_volume: float,
    total_capital: float,
    available_cash: float,
) -> dict:
    """Adapted from risk/position_sizing.py's real ATR+Kelly formula —
    see module docstring for exactly which pieces are reused as-is
    vs. deliberately left neutral. Returns quantity=0 (never forced to
    1) when the capital/risk budget can't afford even 1 share."""
    kelly_fraction = FALLBACK_KELLY_FRACTION

    base_allocation = MIN_CAPITAL_ALLOCATION + (
        MAX_CAPITAL_ALLOCATION - MIN_CAPITAL_ALLOCATION
    ) * kelly_fraction

    if atr_percent <= 1.0:
        volatility_adjustment = 1.00
    elif atr_percent <= 2.0:
        volatility_adjustment = 0.90
    elif atr_percent <= 3.0:
        volatility_adjustment = 0.75
    elif atr_percent <= 5.0:
        volatility_adjustment = 0.60
    else:
        volatility_adjustment = 0.40

    if average_volume >= 5_000_000:
        liquidity_adjustment = 1.00
    elif average_volume >= 2_000_000:
        liquidity_adjustment = 0.90
    elif average_volume >= 1_000_000:
        liquidity_adjustment = 0.80
    elif average_volume >= 500_000:
        liquidity_adjustment = 0.65
    else:
        liquidity_adjustment = 0.40

    # confidence_adjustment / risk_adjustment: NOT modeled in this
    # trial (no scoring/risk engine here) — neutral 1.0, not fabricated.
    adjustment_factor = volatility_adjustment * liquidity_adjustment

    allocation_percent = base_allocation * adjustment_factor
    allocation_percent = max(
        MIN_CAPITAL_ALLOCATION, min(allocation_percent, MAX_CAPITAL_ALLOCATION)
    )

    capital_to_use = min(available_cash * allocation_percent, available_cash)
    position_value = max(MIN_POSITION_VALUE, capital_to_use)
    position_value = min(position_value, MAX_POSITION_VALUE, available_cash)

    capital_quantity = math.floor(position_value / entry_price) if entry_price > 0 else 0

    risk_per_trade = total_capital * MAX_RISK_PER_TRADE
    atr_quantity = math.floor(risk_per_trade / stop_distance) if stop_distance > 0 else 0

    executable_quantity = max(0, min(atr_quantity, capital_quantity))

    return {
        "quantity": executable_quantity,
        "position_value": round(executable_quantity * entry_price, 2),
        "allocation_percent": round(allocation_percent, 4),
        "kelly_fraction": kelly_fraction,
        "volatility_adjustment": volatility_adjustment,
        "liquidity_adjustment": liquidity_adjustment,
        "atr_quantity": atr_quantity,
        "capital_quantity": capital_quantity,
    }


def monitor_position(position: dict, latest_close: float) -> tuple[dict, list[tuple[str, float]]]:
    """Checks one open position against the latest close. Returns the
    (possibly mutated) position and a list of (event_type, level)
    tuples — event_type is 'TARGET1_HIT_SL_SHIFTED' or
    'STOP_LOSS_HIT'. Mirrors BUY and SELL exactly (opposite
    comparison directions, identical logic shape). Also updates
    highest_price/lowest_price (direction-agnostic — just the raw
    extremes seen since entry, used for the holding-status message)."""
    events: list[tuple[str, float]] = []
    direction = position["direction"]
    target1 = position["target1"]
    target1_hit = position.get("target1_hit", False)

    entry_price = position["entry_price"]
    position["highest_price"] = max(position.get("highest_price", entry_price), latest_close)
    position["lowest_price"] = min(position.get("lowest_price", entry_price), latest_close)

    if direction == "BUY":
        if not target1_hit and latest_close >= target1:
            position["stop_loss"] = target1
            position["target1_hit"] = True
            target1_hit = True
            events.append(("TARGET1_HIT_SL_SHIFTED", target1))

        if latest_close <= position["stop_loss"]:
            events.append(("STOP_LOSS_HIT", position["stop_loss"]))

    else:
        if not target1_hit and latest_close <= target1:
            position["stop_loss"] = target1
            position["target1_hit"] = True
            target1_hit = True
            events.append(("TARGET1_HIT_SL_SHIFTED", target1))

        if latest_close >= position["stop_loss"]:
            events.append(("STOP_LOSS_HIT", position["stop_loss"]))

    return position, events


def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — skipping Telegram "
            "send. Message was: %s",
            message,
        )
        return

    try:
        TelegramAlert(token, chat_id).send(message, raw=True)
    except Exception as exc:  # pragma: no cover - network failure path
        logger.error("Telegram send failed (continuing scan): %s", exc)


def _pnl_percent(direction: str, entry_price: float, exit_price: float) -> float:
    if direction == "BUY":
        return (exit_price - entry_price) / entry_price * 100
    return (entry_price - exit_price) / entry_price * 100


def _pnl_amount(invested_amount: float, pnl_percent: float) -> float:
    return round(invested_amount * pnl_percent / 100, 2)


def _format_scan_summary(
    scanned: int,
    buy_count: int,
    sell_count: int,
    no_trade_count: int,
    new_buy_count: int,
    new_sell_count: int,
    target1_shift_symbols: list[str],
    stop_hit_symbols: list[str],
    skipped_capital_symbols: list[str],
    open_count: int,
    winning_count: int,
    losing_count: int,
    available_cash: float,
    net_worth: float,
    starting_capital: float,
) -> str:
    """ONE consolidated message per run — replaces the old
    one-message-per-signal spam. Only counts + short (capped) symbol
    lists for the event types, so length stays bounded regardless of
    how many symbols were scanned."""

    def _capped_list(symbols: list[str], cap: int = 10) -> str:
        if not symbols:
            return ""
        shown = ", ".join(symbols[:cap])
        extra = f", +{len(symbols) - cap} more" if len(symbols) > cap else ""
        return f" ({shown}{extra})"

    overall_pnl_amount = round(net_worth - starting_capital, 2)
    overall_pnl_percent = (
        round(overall_pnl_amount / starting_capital * 100, 2) if starting_capital else 0.0
    )

    lines = [
        "[TRIAL_SCAN_COMPLETED]",
        f"Trial scan completed — {scanned} symbol(s) scanned.",
        f"BUY: {buy_count} | SELL: {sell_count} | NO_TRADE: {no_trade_count}",
        "",
        f"New positions opened: {new_buy_count + new_sell_count} "
        f"({new_buy_count} BUY, {new_sell_count} SELL)",
        f"Target1 hit, stop-loss shifted: {len(target1_shift_symbols)}"
        f"{_capped_list(target1_shift_symbols)}",
        f"Stop-loss hit, closed: {len(stop_hit_symbols)}"
        f"{_capped_list(stop_hit_symbols)}",
        f"Signal found but skipped (insufficient capital/risk budget): "
        f"{len(skipped_capital_symbols)}{_capped_list(skipped_capital_symbols)}",
        f"Open positions now: {open_count} ({winning_count} winning, {losing_count} losing)",
        "",
        f"Available Cash: ₹{available_cash:,.2f}",
        f"Net Worth: ₹{net_worth:,.2f} (started at ₹{starting_capital:,.2f})",
        f"Overall P&L: ₹{overall_pnl_amount:,.2f} ({overall_pnl_percent:+.2f}%)",
    ]
    return "\n".join(lines)


def _format_holding_entry(index: int, symbol: str, position: dict, latest_close: float) -> str:
    direction = position["direction"]
    entry_price = position["entry_price"]
    entry_date = position["entry_time"][:10]
    quantity = position.get("quantity", 0)
    invested_amount = position.get("invested_amount", 0.0)

    try:
        entry_dt = datetime.fromisoformat(position["entry_time"])
        holding_days = (datetime.now(timezone.utc) - entry_dt).days
    except ValueError:  # pragma: no cover - defensive, malformed state
        holding_days = None

    pnl_percent = _pnl_percent(direction, entry_price, latest_close)
    pnl_amount = _pnl_amount(invested_amount, pnl_percent)
    current_value = round(invested_amount + pnl_amount, 2)

    highest_price = position.get("highest_price", entry_price)
    lowest_price = position.get("lowest_price", entry_price)
    highest_pct = _pnl_percent(direction, entry_price, highest_price)
    lowest_pct = _pnl_percent(direction, entry_price, lowest_price)

    if position.get("target1_hit"):
        target_line = f"Target1 (3%): HIT — stop-loss trailing at {position['stop_loss']:.2f}"
    else:
        if direction == "BUY":
            remaining_pct = (position["target1"] - latest_close) / entry_price * 100
        else:
            remaining_pct = (latest_close - position["target1"]) / entry_price * 100
        target_line = f"Target1 (3%): {remaining_pct:.2f}% remaining"

    stop_distance_pct = (
        abs(latest_close - position["stop_loss"]) / latest_close * 100 if latest_close else 0.0
    )
    holding_line = f"{holding_days} day(s)" if holding_days is not None else "unknown"

    return (
        f"{index}. {symbol} ({direction}) — HOLD\n"
        f"   Entry: {entry_price:.2f} ({entry_date}) | Current: {latest_close:.2f} | "
        f"Qty: {quantity}\n"
        f"   Invested: ₹{invested_amount:,.2f} | Current Value: ₹{current_value:,.2f}\n"
        f"   Holding: {holding_line}\n"
        f"   PnL: {pnl_percent:+.2f}% (₹{pnl_amount:+,.2f})\n"
        f"   Highest: {highest_pct:+.2f}% | Lowest: {lowest_pct:+.2f}% (since entry)\n"
        f"   {target_line}\n"
        f"   Stop-loss distance: {stop_distance_pct:.2f}%"
    )


def _format_holding_status_messages(
    open_positions: dict,
    latest_close_by_symbol: dict,
    chunk_size: int = 10,
) -> list[str]:
    """One message listing ALL open positions, chunked at
    `chunk_size` entries per message so a large position count still
    stays under Telegram's per-message length limit — never one
    message per position."""
    relevant = [(sym, pos) for sym, pos in open_positions.items() if sym in latest_close_by_symbol]
    if not relevant:
        return []

    entries = [
        _format_holding_entry(idx, sym, pos, latest_close_by_symbol[sym])
        for idx, (sym, pos) in enumerate(relevant, start=1)
    ]

    chunks = [entries[i : i + chunk_size] for i in range(0, len(entries), chunk_size)]
    total_chunks = len(chunks)

    messages = []
    for chunk_idx, chunk in enumerate(chunks, start=1):
        header = f"[TRIAL_HOLDING_STATUS] Open Positions ({len(relevant)})"
        if total_chunks > 1:
            header += f" — part {chunk_idx}/{total_chunks}"
        messages.append(f"{header}\n\n" + "\n\n".join(chunk))

    return messages


def run(
    symbols: list[str],
    state_path: Path = STATE_PATH,
    trade_log_path: Path = TRADE_LOG_PATH,
    market_provider: MarketDataProvider | None = None,
    notify=send_telegram,
) -> dict:
    """Runs one full cycle: for every symbol, classify its current
    signal (for the scan-summary stats), monitor it if a position is
    already open, or size + act on a fresh signal if not (skipping it
    if the capital/risk budget can't afford even 1 share). Sends
    exactly TWO kinds of Telegram message per run — one scan summary,
    and one (or a few, chunked) holding-status message — never one
    message per individual signal/position."""
    provider = market_provider or MarketDataProvider()
    state = load_state(state_path)
    open_positions = state["open_positions"]
    capital = state["capital"]
    available_cash = float(capital["available_cash"])
    starting_capital = float(capital["starting_capital"])

    # Cost-basis net worth, used ONLY as the risk-budget reference
    # (2% of this) for sizing a fresh trade this run. Algebraically
    # unchanged by opening a new position at cost (cash decreases by
    # exactly what the position's cost-basis increases by), so it is
    # computed once up front rather than recomputed every iteration.
    total_capital_cost_basis = available_cash + sum(
        pos["entry_price"] * pos.get("quantity", 0) for pos in open_positions.values()
    )

    buy_count = 0
    sell_count = 0
    no_trade_count = 0
    new_buy_count = 0
    new_sell_count = 0
    target1_shift_symbols: list[str] = []
    stop_hit_symbols: list[str] = []
    skipped_capital_symbols: list[str] = []
    latest_close_by_symbol: dict[str, float] = {}

    for symbol in symbols:
        try:
            dataframe = provider.fetch(symbol=symbol, interval=INTERVAL, period=PERIOD)
        except Exception as exc:
            logger.warning("Fetch failed for %s: %s", symbol, exc)
            continue

        if dataframe is None or dataframe.empty:
            continue

        dataframe = compute_emas(dataframe)
        latest = dataframe.iloc[-1]
        latest_close = float(latest["close"])
        latest_close_by_symbol[symbol] = latest_close

        signal = evaluate_signal(latest)
        if signal == "BUY":
            buy_count += 1
        elif signal == "SELL":
            sell_count += 1
        else:
            no_trade_count += 1

        if symbol in open_positions:
            position, events = monitor_position(open_positions[symbol], latest_close)

            closed = False
            for event_type, level in events:
                if event_type == "TARGET1_HIT_SL_SHIFTED":
                    target1_shift_symbols.append(symbol)
                elif event_type == "STOP_LOSS_HIT":
                    stop_hit_symbols.append(symbol)
                    entry_price = position["entry_price"]
                    quantity = position.get("quantity", 0)
                    invested_amount = position.get("invested_amount", 0.0)
                    pnl_percent = _pnl_percent(position["direction"], entry_price, latest_close)
                    pnl_amount = _pnl_amount(invested_amount, pnl_percent)
                    available_cash += invested_amount + pnl_amount
                    append_trade_log(
                        {
                            "trade_id": position["trade_id"],
                            "symbol": symbol,
                            "direction": position["direction"],
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "entry_time": position["entry_time"],
                            "invested_amount": invested_amount,
                            "exit_price": latest_close,
                            "exit_time": _now_iso(),
                            "exit_reason": "STOP_LOSS_HIT",
                            "target1_hit": position["target1_hit"],
                            "pnl_percent": round(pnl_percent, 2),
                            "pnl_amount": pnl_amount,
                        },
                        path=trade_log_path,
                    )
                    del open_positions[symbol]
                    closed = True

            if not closed:
                open_positions[symbol] = position

            continue

        if signal == "NO_TRADE":
            continue

        stop_loss, target1 = compute_initial_stop_target(signal, latest_close)
        stop_distance = abs(latest_close - stop_loss)

        atr_series = compute_atr(dataframe)
        latest_atr = atr_series.iloc[-1]
        if pd.isna(latest_atr):
            logger.warning(
                "ATR not available yet for %s (insufficient history) — "
                "skipping position sizing this run.",
                symbol,
            )
            skipped_capital_symbols.append(symbol)
            continue

        atr_percent = (latest_atr / latest_close * 100) if latest_close else 0.0
        average_volume = float(compute_volume_average(dataframe).iloc[-1])

        sizing = compute_position_size(
            entry_price=latest_close,
            stop_distance=stop_distance,
            atr_percent=atr_percent,
            average_volume=average_volume,
            total_capital=total_capital_cost_basis,
            available_cash=available_cash,
        )

        if sizing["quantity"] <= 0:
            skipped_capital_symbols.append(symbol)
            continue

        quantity = sizing["quantity"]
        invested_amount = round(quantity * latest_close, 2)
        available_cash -= invested_amount

        trade_id = f"trial_{symbol.replace('.', '_')}_{int(datetime.now(timezone.utc).timestamp())}"

        open_positions[symbol] = {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": signal,
            "quantity": quantity,
            "entry_price": latest_close,
            "entry_time": _now_iso(),
            "invested_amount": invested_amount,
            "stop_loss": stop_loss,
            "target1": target1,
            "target1_hit": False,
            "highest_price": latest_close,
            "lowest_price": latest_close,
            "sizing": {
                "allocation_percent": sizing["allocation_percent"],
                "kelly_fraction": sizing["kelly_fraction"],
                "volatility_adjustment": sizing["volatility_adjustment"],
                "liquidity_adjustment": sizing["liquidity_adjustment"],
            },
        }
        if signal == "BUY":
            new_buy_count += 1
        else:
            new_sell_count += 1

    capital["available_cash"] = round(available_cash, 2)
    state["capital"] = capital
    save_state(state, state_path)

    net_worth = available_cash + sum(
        pos.get("quantity", 0) * latest_close_by_symbol.get(sym, pos["entry_price"])
        for sym, pos in open_positions.items()
    )
    net_worth = round(net_worth, 2)

    # Winning/losing split among open positions that were actually
    # scanned this run (mark-to-market at today's latest close) — a
    # position not in this run's symbol list contributes to neither
    # count, same "only report what was actually checked" rule as
    # the holding-status message below.
    winning_count = 0
    losing_count = 0
    for sym, pos in open_positions.items():
        if sym not in latest_close_by_symbol:
            continue
        unrealized_pct = _pnl_percent(pos["direction"], pos["entry_price"], latest_close_by_symbol[sym])
        if unrealized_pct > 0:
            winning_count += 1
        elif unrealized_pct < 0:
            losing_count += 1

    scan_summary = _format_scan_summary(
        scanned=len(symbols),
        buy_count=buy_count,
        sell_count=sell_count,
        no_trade_count=no_trade_count,
        new_buy_count=new_buy_count,
        new_sell_count=new_sell_count,
        target1_shift_symbols=target1_shift_symbols,
        stop_hit_symbols=stop_hit_symbols,
        skipped_capital_symbols=skipped_capital_symbols,
        open_count=len(open_positions),
        winning_count=winning_count,
        losing_count=losing_count,
        available_cash=round(available_cash, 2),
        net_worth=net_worth,
        starting_capital=starting_capital,
    )
    notify(scan_summary)

    for holding_message in _format_holding_status_messages(open_positions, latest_close_by_symbol):
        notify(holding_message)

    summary = {
        "scanned": len(symbols),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "no_trade_count": no_trade_count,
        "new_signals": new_buy_count + new_sell_count,
        "new_buy_count": new_buy_count,
        "new_sell_count": new_sell_count,
        "target1_shifts": len(target1_shift_symbols),
        "stop_losses_hit": len(stop_hit_symbols),
        "skipped_insufficient_capital": len(skipped_capital_symbols),
        "open_positions": len(open_positions),
        "winning_positions": winning_count,
        "losing_positions": losing_count,
        "available_cash": round(available_cash, 2),
        "net_worth": net_worth,
    }
    logger.info("Trial run complete: %s", summary)
    return summary


def _load_symbols(symbols_arg: str, symbols_file: str) -> list[str]:
    if symbols_arg:
        return [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]
    return WatchlistManager(symbols_file).load()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "TEMPORARY TRIAL: EMA(26/70/240) trend-alignment strategy, fixed"
            "-percent risk management (1.5% stop / 3% target-then-trail), "
            "real capital tracking, Telegram alerts. Fully isolated from "
            "the production pipeline."
        )
    )
    parser.add_argument(
        "--symbols",
        default="",
        help=(
            "Optional comma-separated symbol list to test with instead of "
            "the full Nifty500 watchlist, e.g. 'HDFCBANK.NS,TCS.NS'."
        ),
    )
    parser.add_argument(
        "--symbols-file",
        default=WATCHLIST_PATH,
        help=f"Watchlist JSON path (default: {WATCHLIST_PATH}).",
    )
    args = parser.parse_args()

    symbols = _load_symbols(args.symbols, args.symbols_file)
    if not symbols:
        print("No symbols to scan — exiting.")
        return

    print(
        f"NOTE: interval={INTERVAL!r} period={PERIOD!r} — ema_{EMA_SLOW} "
        f"needs ~{EMA_SLOW} trading days of history to be a genuinely "
        f"warmed-up {EMA_SLOW}-day EMA; period={PERIOD!r} returns far fewer "
        f"candles than that, so ema_{EMA_SLOW} here is NOT a mature "
        f"long-term EMA value (this is exactly what was requested — "
        f"flagging it loudly rather than silently changing the period)."
    )
    print(f"Scanning {len(symbols)} symbol(s)...")

    summary = run(symbols)

    print(
        f"Done. BUY: {summary['buy_count']} | SELL: {summary['sell_count']} | "
        f"NO_TRADE: {summary['no_trade_count']}. "
        f"New positions: {summary['new_signals']} "
        f"({summary['new_buy_count']} BUY, {summary['new_sell_count']} SELL). "
        f"Target1 stop-shifts: {summary['target1_shifts']}, "
        f"Stop-losses hit: {summary['stop_losses_hit']}, "
        f"Skipped (insufficient capital): {summary['skipped_insufficient_capital']}, "
        f"Open positions now: {summary['open_positions']}. "
        f"Available Cash: ₹{summary['available_cash']:,.2f}, "
        f"Net Worth: ₹{summary['net_worth']:,.2f}."
    )


if __name__ == "__main__":
    main()
