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


def _format_scan_summary(
    scanned: int,
    buy_count: int,
    sell_count: int,
    no_trade_count: int,
    new_buy_count: int,
    new_sell_count: int,
    target1_shift_symbols: list[str],
    stop_hit_symbols: list[str],
    open_count: int,
) -> str:
    """ONE consolidated message per run — replaces the old
    one-message-per-signal spam. Only counts + short (capped) symbol
    lists for the two event types, so length stays bounded regardless
    of how many symbols were scanned."""

    def _capped_list(symbols: list[str], cap: int = 10) -> str:
        if not symbols:
            return ""
        shown = ", ".join(symbols[:cap])
        extra = f", +{len(symbols) - cap} more" if len(symbols) > cap else ""
        return f" ({shown}{extra})"

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
        f"Open positions now: {open_count}",
    ]
    return "\n".join(lines)


def _format_holding_entry(index: int, symbol: str, position: dict, latest_close: float) -> str:
    direction = position["direction"]
    entry_price = position["entry_price"]
    entry_date = position["entry_time"][:10]

    try:
        entry_dt = datetime.fromisoformat(position["entry_time"])
        holding_days = (datetime.now(timezone.utc) - entry_dt).days
    except ValueError:  # pragma: no cover - defensive, malformed state
        holding_days = None

    pnl_percent = _pnl_percent(direction, entry_price, latest_close)

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
        f"   Entry: {entry_price:.2f} ({entry_date}) | Current: {latest_close:.2f}\n"
        f"   Holding: {holding_line}\n"
        f"   PnL: {pnl_percent:+.2f}%\n"
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
    already open, or act on a fresh signal if not. Sends exactly TWO
    kinds of Telegram message per run — one scan summary, and one (or
    a few, chunked) holding-status message — never one message per
    individual signal/position."""
    provider = market_provider or MarketDataProvider()
    state = load_state(state_path)
    open_positions = state["open_positions"]

    buy_count = 0
    sell_count = 0
    no_trade_count = 0
    new_buy_count = 0
    new_sell_count = 0
    target1_shift_symbols: list[str] = []
    stop_hit_symbols: list[str] = []
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
                    pnl_percent = _pnl_percent(position["direction"], entry_price, latest_close)
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
            "highest_price": latest_close,
            "lowest_price": latest_close,
        }
        if signal == "BUY":
            new_buy_count += 1
        else:
            new_sell_count += 1

    save_state(state, state_path)

    scan_summary = _format_scan_summary(
        scanned=len(symbols),
        buy_count=buy_count,
        sell_count=sell_count,
        no_trade_count=no_trade_count,
        new_buy_count=new_buy_count,
        new_sell_count=new_sell_count,
        target1_shift_symbols=target1_shift_symbols,
        stop_hit_symbols=stop_hit_symbols,
        open_count=len(open_positions),
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
        f"Done. BUY: {summary['buy_count']} | SELL: {summary['sell_count']} | "
        f"NO_TRADE: {summary['no_trade_count']}. "
        f"New positions: {summary['new_signals']} "
        f"({summary['new_buy_count']} BUY, {summary['new_sell_count']} SELL). "
        f"Target1 stop-shifts: {summary['target1_shifts']}, "
        f"Stop-losses hit: {summary['stop_losses_hit']}, "
        f"Open positions now: {summary['open_positions']}."
    )


if __name__ == "__main__":
    main()
