"""
TEMPORARY TRIAL STRATEGY — EMA(26/70/240) trend-alignment.

Built at the user's explicit request as a short-term EXPERIMENT, kept
completely isolated from the live production pipeline
(execution/scanner.py, strategy/buy_strategy.py, strategy/sell_strategy.py,
paper_trading/paper_trading_engine.py, risk/*). This script imports
none of those and is never called by any production workflow — it can
be deleted or disabled at any time without touching production.

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
ATR-based model in risk/stop_target.py, deliberately, since this is a
separate experiment):
    initial stop-loss = entry -+ 1.5%   (BUY: below entry, SELL: above)
    target1            = entry -+ 3.0%   (BUY: above entry, SELL: below)
    Once price crosses target1, stop-loss is moved to target1 (locks
    in the 3% gain). No further fixed target after that — the position
    keeps running until the (now-shifted) stop-loss is eventually hit,
    per the user's explicit "let it run" choice.

STATE / HISTORY: storage/trial_trades/state.json (open positions) and
storage/trial_trades/trade_log.csv (closed trades) — COMPLETELY
SEPARATE from production's storage/trades/... paths, so
analytics/learning_engine.py, analytics/optimizer.py and the
backtester never see or mix this data (those modules hardcode
"storage/trades/..." paths; verified no generic directory scan exists
anywhere in that code).

TELEGRAM: reuses output/telegram_alert.py and the same
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets already configured for
the production workflows — no new bot/setup needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.logger import get_logger
from data.market_data import MarketDataProvider
from data.watchlist import WatchlistManager
from output.telegram_alert import TelegramAlert

logger = get_logger(__name__)

INTERVAL = "1d"
PERIOD = "1mo"

EMA_FAST = 26
EMA_MID = 70
EMA_SLOW = 240

STOP_LOSS_PERCENT = 0.015
TARGET1_PERCENT = 0.03

WATCHLIST_PATH = "storage/watchlist/nifty500.json"
STATE_PATH = Path("storage/trial_trades/state.json")
TRADE_LOG_PATH = Path("storage/trial_trades/trade_log.csv")

TRADE_LOG_FIELDS = [
    "trade_id",
    "symbol",
    "direction",
    "entry_price",
    "entry_time",
    "exit_price",
    "exit_time",
    "exit_reason",
    "target1_hit",
    "pnl_percent",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path = STATE_PATH) -> dict:
    """Never fabricates data — a missing/unreadable state file simply
    means "no open positions yet", not a silently-invented default
    position."""
    if not path.exists():
        return {"open_positions": {}}

    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    if "open_positions" not in data:
        data["open_positions"] = {}

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


def monitor_position(position: dict, latest_close: float) -> tuple[dict, list[tuple[str, float]]]:
    """Checks one open position against the latest close. Returns the
    (possibly mutated) position and a list of (event_type, level)
    tuples — event_type is 'TARGET1_HIT_SL_SHIFTED' or
    'STOP_LOSS_HIT'. Mirrors BUY and SELL exactly (opposite
    comparison directions, identical logic shape)."""
    events: list[tuple[str, float]] = []
    direction = position["direction"]
    target1 = position["target1"]
    target1_hit = position.get("target1_hit", False)

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


def run(
    symbols: list[str],
    state_path: Path = STATE_PATH,
    trade_log_path: Path = TRADE_LOG_PATH,
    market_provider: MarketDataProvider | None = None,
    notify=send_telegram,
) -> dict:
    """Runs one full cycle: monitor open positions first, then scan
    remaining symbols for a fresh signal. Returns a small summary dict
    (useful for tests and for the CLI's own printed summary)."""
    provider = market_provider or MarketDataProvider()
    state = load_state(state_path)
    open_positions = state["open_positions"]

    new_signal_count = 0
    target_shift_count = 0
    stop_hit_count = 0

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

        if symbol in open_positions:
            position, events = monitor_position(open_positions[symbol], latest_close)

            closed = False
            for event_type, level in events:
                if event_type == "TARGET1_HIT_SL_SHIFTED":
                    target_shift_count += 1
                    notify(
                        f"[TRIAL] {symbol} {position['direction']} — Target1 "
                        f"(3%) hit @ {latest_close:.2f}. Stop-loss shifted to "
                        f"{level:.2f} (locked-in). Position still open, no "
                        f"fixed final target."
                    )
                elif event_type == "STOP_LOSS_HIT":
                    stop_hit_count += 1
                    entry_price = position["entry_price"]
                    pnl_percent = _pnl_percent(position["direction"], entry_price, latest_close)
                    notify(
                        f"[TRIAL] {symbol} {position['direction']} — "
                        f"Stop-loss hit @ {latest_close:.2f} (SL was "
                        f"{level:.2f}). Position CLOSED. P&L: "
                        f"{pnl_percent:.2f}%."
                    )
                    append_trade_log(
                        {
                            "trade_id": position["trade_id"],
                            "symbol": symbol,
                            "direction": position["direction"],
                            "entry_price": entry_price,
                            "entry_time": position["entry_time"],
                            "exit_price": latest_close,
                            "exit_time": _now_iso(),
                            "exit_reason": "STOP_LOSS_HIT",
                            "target1_hit": position["target1_hit"],
                            "pnl_percent": round(pnl_percent, 2),
                        },
                        path=trade_log_path,
                    )
                    del open_positions[symbol]
                    closed = True

            if not closed:
                open_positions[symbol] = position

            continue

        signal = evaluate_signal(latest)
        if signal == "NO_TRADE":
            continue

        stop_loss, target1 = compute_initial_stop_target(signal, latest_close)
        trade_id = f"trial_{symbol.replace('.', '_')}_{int(datetime.now(timezone.utc).timestamp())}"

        open_positions[symbol] = {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": signal,
            "entry_price": latest_close,
            "entry_time": _now_iso(),
            "stop_loss": stop_loss,
            "target1": target1,
            "target1_hit": False,
        }
        new_signal_count += 1
        notify(
            f"[TRIAL] NEW {signal} signal — {symbol} @ {latest_close:.2f}. "
            f"Stop-loss {stop_loss:.2f} (1.5%), Target1 {target1:.2f} (3%). "
            f"EMA{EMA_FAST}/{EMA_MID}/{EMA_SLOW} trend-aligned {signal}."
        )

    save_state(state, state_path)

    summary = {
        "new_signals": new_signal_count,
        "target1_shifts": target_shift_count,
        "stop_losses_hit": stop_hit_count,
        "open_positions": len(open_positions),
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
            "Telegram alerts. Fully isolated from the production pipeline."
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
        f"Done. New signals: {summary['new_signals']}, "
        f"Target1 stop-shifts: {summary['target1_shifts']}, "
        f"Stop-losses hit: {summary['stop_losses_hit']}, "
        f"Open positions now: {summary['open_positions']}."
    )


if __name__ == "__main__":
    main()
