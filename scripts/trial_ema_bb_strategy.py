"""
TEMPORARY TRIAL STRATEGY — EMA(50/200) fresh-cross.

Built at the user's explicit request as a short-term EXPERIMENT, kept
completely isolated from the live production pipeline
(execution/scanner.py, strategy/buy_strategy.py, strategy/sell_strategy.py,
paper_trading/paper_trading_engine.py, risk/*). This script imports
none of those and is never called by any production workflow — it can
be deleted or disabled at any time without touching production.

DEPLOYABILITY FIX (2026-09-02): this file previously imported
`wilders_smoothing` from `features/indicators/smoothing.py` for its ATR
calculation. That module does not exist anywhere in this repo's actual
GitHub history (verified via `git log --all`) — it, this whole file,
and both of its GitHub Actions workflows were never committed, only
ever present in a local working copy. Importing a genuinely missing
module would have made every run of this script crash immediately, the
same way market_intelligence_engine.py broke in a sibling repo this
session from an accidental overwrite — so Wilder's smoothing is now
INLINED below (`_wilders_smoothing()`) as a small, self-contained
math helper with zero import dependency on anything outside this file,
matching this script's own "imports none of the pipeline" isolation
claim literally rather than only for the pipeline modules.

SIGNAL (rewritten 2026-09-02 — the original EMA(26/70/240) three-way
trend-alignment version below never actually ran: this file, both of
its GitHub Actions workflows, and storage/trial_trades/ were never
committed to this repo — verified via `git log --all` finding zero
matches. There is no real trade data from the old version to have been
"unsuccessful" against; this is a genuinely fresh start, not a tuning
of a strategy that was tried and failed):

    BUY  : close crosses FRESH above ema_50 this candle (prev close was
           at/below ema_50, today's close is above it) AND today's
           close is ALSO above ema_200 (confirmation the longer-term
           trend is already bullish — this cross does not need to be
           fresh, only currently true).
    SELL : mirror, roles swapped per the user's explicit "reverse"
           wording — close crosses FRESH below ema_200 this candle
           (prev close was at/above ema_200, today's close is below
           it) AND today's close is ALSO below ema_50 (confirmation
           the shorter-term trend already agrees).
    NO_TRADE : anything else, OR the previous candle is unavailable
           (first row of the series — a "fresh" cross needs a
           yesterday to compare against).

DATA: interval="1d", period="1y" (per explicit instruction — changed
from the old period="1mo"). This also resolves the OLD version's
own documented caveat about ema_240 never being genuinely warmed up on
only ~21 candles: with a full year of daily history, both ema_50 and
ema_200 are properly warmed up.

RISK MANAGEMENT (fixed-percent, per explicit instruction — NOT any
ATR-based stop/target model production may use elsewhere, deliberately,
since this is a separate experiment; note there is no risk/stop_target.py
in this repo specifically — that path belongs to a different repo this
session also works on, corrected here rather than left as a
misattributed reference):
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
    - kelly_fraction: FIXED at FALLBACK_KELLY_FRACTION (0.5) here —
      simpler than production's real win-rate/reward-risk-derived Kelly
      formula in risk/position_sizing.py (CORRECTED 2026-09-02: an
      earlier version of this note claimed production also runs a flat
      fallback via a "KELLY_CALIBRATED" flag; checked directly against
      risk/position_sizing.py and that flag doesn't exist there —
      production computes kelly_fraction dynamically. This trial uses a
      flat 0.5 anyway, deliberately, since it has no win-rate/reward-risk
      history of its own yet to derive a real one from).
    - volatility_adjustment: from a REAL ATR(14) computed here (Wilder's
      smoothing — see compute_atr()'s docstring for the corrected note
      on how this compares to production's actual ATR formula).
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

TWO SEPARATE ENTRY POINTS (per explicit follow-up request), driven by
--mode:
    --mode scan (default) -> scan_new_signals(): runs ONCE DAILY, after
        market close (see .github/workflows/trial_ema_bb_strategy.yml,
        8:00 PM IST). Uses EOD data (interval="1d", period="1y") to
        classify every watchlist symbol and OPEN a new position where a
        signal fires and none is already open for that symbol. Does
        NOT check stop-loss/target1 on already-open positions — that
        is monitor_open_positions()'s job alone.
    --mode monitor -> monitor_open_positions(): runs INTRADAY, ~4x/day
        during market hours (see
        .github/workflows/trial_position_monitor.yml — 9:30, 11:30,
        13:30, 14:30 IST). Fetches a CURRENT price (interval="5m",
        period="1d" — MONITOR_INTERVAL/MONITOR_PERIOD, deliberately
        NOT the EOD series scan uses) for every EXISTING open position
        only, and applies the exact same rule either way: stop-loss
        hit -> close (FULL exit); neither hit -> hold, unchanged;
        target1 hit -> stop-loss shifts to target1 (locks in the 3%
        gain), position keeps running. NEVER opens a new position.
NOTE (rate limits, not yet solved, flagging honestly): with several
hundred open positions, monitor_open_positions() makes one fetch per
open position, 4x/day, on top of scan's own ~500 daily fetches —
data/market_data.py's own comments already document that Yahoo
Finance silently throttles/returns fewer rows under sustained request
volume. Worth watching for slowdowns/failures as the position count
grows; not addressed here beyond MarketDataProvider's existing
built-in retry-once-on-suspiciously-low-rows behavior.

Capital is tracked in the SAME state.json (see below): starting
capital defaults to STARTING_CAPITAL only the very first time this
runs (no state file yet) — every run after that reads/writes the real
persisted available_cash, it is never re-defaulted. Deleting
state.json (and trade_log.csv, to also clear trade history) makes the
NEXT run start completely fresh from STARTING_CAPITAL automatically —
no code change needed to "reset".

Every position also carries last_known_price/last_checked_at, updated
by BOTH scan (EOD, passively — no action taken) and monitor
(intraday, the live check) — so open_positions in state.json always
has a genuine, timestamped last-seen price for ad-hoc analysis (e.g.
computing real unrealized P&L from the committed state.json alone),
never a stale/fabricated value.

STATE / HISTORY: storage/trial_trades/state.json (open positions +
capital) and storage/trial_trades/trade_log.csv (closed trades) —
COMPLETELY SEPARATE from production's storage/trades/... paths, so
analytics/learning_engine.py, analytics/optimizer.py and the
backtester never see or mix this data (those modules hardcode
"storage/trades/..." paths; verified no generic directory scan exists
anywhere in that code).

TELEGRAM: reuses output/telegram_alert.py and the same
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets already configured for
the production workflows — no new bot/setup needed. scan_new_signals()
sends exactly ONE message (scan summary). monitor_open_positions()
sends exactly TWO kinds (a monitor summary, and one-or-few
holding-status messages) — never one message per signal/position.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from core.logger import get_logger
from core.trading_calendar import is_trading_day, skip_reason
from data.market_data import MarketDataProvider
from data.watchlist import WatchlistManager
from output.telegram_alert import TelegramAlert

logger = get_logger(__name__)

INTERVAL = "1d"
PERIOD = "1y"

# Used ONLY by monitor_open_positions() for a CURRENT intraday price of
# already-open positions — deliberately NOT the EOD series scan_new_signals()
# uses. Reads only "close" (never volume/CMF/MFI), which sidesteps the
# documented yfinance NSE bug where the FIRST hourly candle of the day gets
# volume=0 — that bug only corrupts volume-derived indicators, not raw close.
MONITOR_INTERVAL = "5m"
MONITOR_PERIOD = "1d"

EMA_FAST = 50
EMA_SLOW = 200

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
    """Adds ema_50 / ema_200 columns. Deliberately NOT reusing
    features/indicators/moving_average.py (which computes its own
    9/20/50/100/200 set inside production's pipeline) so this trial
    stays fully isolated and production's shared indicator module is
    never touched by it."""
    df = dataframe.copy()
    for period in (EMA_FAST, EMA_SLOW):
        df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def _wilders_smoothing(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (alpha = 1/period) — the industry-standard
    smoothing method for ATR/RSI/ADX, an exponentially-weighted moving
    average rather than a plain rolling mean. Inlined here (not shared
    with production) — see this file's module docstring's
    "DEPLOYABILITY FIX" note for why: the module this used to import it
    from does not actually exist in this repo. NaN for the first
    `period - 1` bars, same "needs a full window before it means
    anything" behavior as a `rolling(period, min_periods=period)` call."""
    smoothed = series.ewm(alpha=1.0 / period, adjust=False).mean()
    positions = pd.Series(range(len(series)), index=series.index)
    return smoothed.mask(positions < (period - 1))


def compute_atr(dataframe: pd.DataFrame) -> pd.Series:
    """ATR(14) via Wilder's smoothing (see _wilders_smoothing() above).
    NOTE (corrected 2026-09-02): this docstring used to claim this
    matches production's features/indicators/volatility.py formula —
    checked directly against that file and it does NOT: production's
    real ATR(14) there is a plain `rolling(14, min_periods=14).mean()`,
    not Wilder's smoothing. This trial deliberately keeps Wilder's
    smoothing anyway (the more standard ATR method, matching what most
    broker/charting platforms show) rather than silently matching
    production's simpler formula — flagged honestly rather than left
    as an inaccurate claim of parity that isn't real."""
    high = dataframe["high"]
    low = dataframe["low"]
    close = dataframe["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return _wilders_smoothing(true_range, ATR_PERIOD)


def compute_volume_average(dataframe: pd.DataFrame) -> pd.Series:
    """Average volume over VOLUME_AVG_PERIOD bars. Uses min_periods=1
    (a deliberately relaxed floor, kept from the old period="1mo"
    version even though period="1y" now gives plenty of history) so an
    early row in a short series is still an honest "average of
    whatever real history is actually available" rather than NaN,
    consistent with this trial's existing convention of not fabricating
    a value it doesn't have."""
    return dataframe["volume"].rolling(VOLUME_AVG_PERIOD, min_periods=1).mean()


def evaluate_signal(latest: pd.Series, previous: pd.Series | None) -> str:
    """Returns 'BUY', 'SELL', or 'NO_TRADE'.

    REWRITTEN 2026-09-02 (see module docstring for the full rationale
    and the user's exact wording this implements) — a FRESH-CROSS rule,
    not the old three-EMA static alignment:

        BUY  : close crosses fresh above ema_50 THIS candle (previous
               close was at/below ema_50, today's close is above it)
               AND today's close is also above ema_200 (confirms the
               longer-term trend is already bullish — this one is NOT
               required to be fresh, only currently true).
        SELL : mirror, with which EMA is the "fresh trigger" swapped —
               close crosses fresh below ema_200 THIS candle (previous
               close was at/above ema_200, today's close is below it)
               AND today's close is also below ema_50 (confirms the
               shorter-term trend already agrees).

    `previous` is None for the very first row of a series (no
    yesterday to compare against) — returns NO_TRADE rather than
    guessing a direction with no real "fresh" evidence either way.
    """
    if previous is None:
        return "NO_TRADE"

    close = latest["close"]
    ema_fast = latest[f"ema_{EMA_FAST}"]
    ema_slow = latest[f"ema_{EMA_SLOW}"]
    prev_close = previous["close"]
    prev_ema_fast = previous[f"ema_{EMA_FAST}"]
    prev_ema_slow = previous[f"ema_{EMA_SLOW}"]

    if (
        pd.isna(ema_fast) or pd.isna(ema_slow)
        or pd.isna(prev_ema_fast) or pd.isna(prev_ema_slow)
    ):
        return "NO_TRADE"

    fresh_break_above_fast = prev_close <= prev_ema_fast and close > ema_fast
    fresh_break_below_slow = prev_close >= prev_ema_slow and close < ema_slow

    if fresh_break_above_fast and close > ema_slow:
        return "BUY"

    if fresh_break_below_slow and close < ema_fast:
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


def fetch_current_price(symbol: str, provider: MarketDataProvider) -> float | None:
    """Best-effort CURRENT price for intraday monitoring (MONITOR_INTERVAL /
    MONITOR_PERIOD — 5m candles, today only). Returns None (NEVER a
    fabricated price) if the fetch fails, comes back empty, or the API
    errors — the caller must skip that symbol this cycle rather than guess
    a price, per the standing "never fabricate" rule."""
    try:
        dataframe = provider.fetch(symbol=symbol, interval=MONITOR_INTERVAL, period=MONITOR_PERIOD)
    except Exception as exc:
        logger.warning("Current-price fetch failed for %s: %s", symbol, exc)
        return None

    if dataframe is None or dataframe.empty:
        return None

    return float(dataframe.iloc[-1]["close"])


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


def _capped_symbol_list(symbols: list[str], cap: int = 10) -> str:
    """Shared by both message formatters — short (capped) ' (SYM1, SYM2,
    +N more)' suffix so message length stays bounded regardless of how
    many symbols matched."""
    if not symbols:
        return ""
    shown = ", ".join(symbols[:cap])
    extra = f", +{len(symbols) - cap} more" if len(symbols) > cap else ""
    return f" ({shown}{extra})"


def _overall_pnl_line(available_cash: float, net_worth: float, starting_capital: float) -> list[str]:
    """Shared Cash/Net-Worth/Overall-P&L block used by both message
    formatters."""
    overall_pnl_amount = round(net_worth - starting_capital, 2)
    overall_pnl_percent = (
        round(overall_pnl_amount / starting_capital * 100, 2) if starting_capital else 0.0
    )
    return [
        f"Available Cash: ₹{available_cash:,.2f}",
        f"Net Worth: ₹{net_worth:,.2f} (started at ₹{starting_capital:,.2f})",
        f"Overall P&L: ₹{overall_pnl_amount:,.2f} ({overall_pnl_percent:+.2f}%)",
    ]


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
    """ONE consolidated message per DAILY scan run (scan_new_signals) —
    replaces the old one-message-per-signal spam. Only counts + short
    (capped) symbol lists for the event types, so length stays bounded
    regardless of how many symbols were scanned. Does NOT report
    target1-shift/stop-hit events — scan_new_signals() never checks
    existing positions, that is monitor_open_positions()'s job (see
    _format_monitor_summary)."""

    lines = [
        "[TRIAL_SCAN_COMPLETED]",
        f"Trial scan completed — {scanned} symbol(s) scanned.",
        f"BUY: {buy_count} | SELL: {sell_count} | NO_TRADE: {no_trade_count}",
        "",
        f"New positions opened: {new_buy_count + new_sell_count} "
        f"({new_buy_count} BUY, {new_sell_count} SELL)",
        f"Target1 hit, stop-loss shifted: {len(target1_shift_symbols)}"
        f"{_capped_symbol_list(target1_shift_symbols)}",
        f"Stop-loss hit, closed: {len(stop_hit_symbols)}"
        f"{_capped_symbol_list(stop_hit_symbols)}",
        f"Signal found but skipped (insufficient capital/risk budget): "
        f"{len(skipped_capital_symbols)}{_capped_symbol_list(skipped_capital_symbols)}",
        f"Open positions now: {open_count} ({winning_count} winning, {losing_count} losing)",
        "",
        *_overall_pnl_line(available_cash, net_worth, starting_capital),
    ]
    return "\n".join(lines)


def _format_monitor_summary(
    checked_count: int,
    target1_shift_symbols: list[str],
    stop_hit_symbols: list[str],
    open_count: int,
    winning_count: int,
    losing_count: int,
    available_cash: float,
    net_worth: float,
    starting_capital: float,
) -> str:
    """ONE consolidated message per INTRADAY monitoring run
    (monitor_open_positions) — reports what changed for ALREADY-OPEN
    positions only (stop-loss hits / target1 shifts). Never opens new
    positions, so there is no BUY/SELL/NO_TRADE universe breakdown or
    "new positions opened" line here — those only apply to
    scan_new_signals()'s message (_format_scan_summary)."""

    lines = [
        "[TRIAL_POSITION_MONITOR]",
        f"Position monitor run completed — {checked_count} open position(s) checked.",
        "",
        f"Target1 hit, stop-loss shifted: {len(target1_shift_symbols)}"
        f"{_capped_symbol_list(target1_shift_symbols)}",
        f"Stop-loss hit, closed: {len(stop_hit_symbols)}"
        f"{_capped_symbol_list(stop_hit_symbols)}",
        f"Open positions now: {open_count} ({winning_count} winning, {losing_count} losing)",
        "",
        *_overall_pnl_line(available_cash, net_worth, starting_capital),
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


def scan_new_signals(
    symbols: list[str],
    state_path: Path = STATE_PATH,
    trade_log_path: Path = TRADE_LOG_PATH,
    market_provider: MarketDataProvider | None = None,
    notify=send_telegram,
) -> dict:
    """DAILY scan — runs ONCE, after market close (EOD data). For every
    symbol, classifies its current signal (for the scan-summary stats)
    and, if none is already open for that symbol, sizes + opens a fresh
    BUY/SELL position (skipping it if the capital/risk budget can't
    afford even 1 share).

    Does NOT check stop-loss/target1 on already-open positions — that
    is monitor_open_positions()'s job alone. A symbol that already has
    an open position is still fetched here (for BUY/SELL/NO_TRADE
    stats) but its position is left untouched except for a passive
    last_known_price/last_checked_at update (useful for ad-hoc P&L
    analysis between monitor runs — never used to trigger an exit).

    Sends exactly ONE Telegram message per run (the scan summary) — no
    holding-status messages, that is monitor_open_positions()'s job."""
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
        # "Fresh cross" needs yesterday's row too — None when this
        # symbol's fetch returned only a single candle (evaluate_signal()
        # correctly treats that as NO_TRADE rather than guessing).
        previous = dataframe.iloc[-2] if len(dataframe) >= 2 else None
        latest_close = float(latest["close"])
        latest_close_by_symbol[symbol] = latest_close

        signal = evaluate_signal(latest, previous)
        if signal == "BUY":
            buy_count += 1
        elif signal == "SELL":
            sell_count += 1
        else:
            no_trade_count += 1

        if symbol in open_positions:
            # Passive only — scan_new_signals() never acts on an
            # existing position (no stop-loss/target1 check here).
            open_positions[symbol]["last_known_price"] = latest_close
            open_positions[symbol]["last_checked_at"] = _now_iso()
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
        now_iso = _now_iso()

        open_positions[symbol] = {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": signal,
            "quantity": quantity,
            "entry_price": latest_close,
            "entry_time": now_iso,
            "invested_amount": invested_amount,
            "stop_loss": stop_loss,
            "target1": target1,
            "target1_hit": False,
            "highest_price": latest_close,
            "lowest_price": latest_close,
            "last_known_price": latest_close,
            "last_checked_at": now_iso,
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
    # count.
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
        target1_shift_symbols=[],
        stop_hit_symbols=[],
        skipped_capital_symbols=skipped_capital_symbols,
        open_count=len(open_positions),
        winning_count=winning_count,
        losing_count=losing_count,
        available_cash=round(available_cash, 2),
        net_worth=net_worth,
        starting_capital=starting_capital,
    )
    notify(scan_summary)

    summary = {
        "scanned": len(symbols),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "no_trade_count": no_trade_count,
        "new_signals": new_buy_count + new_sell_count,
        "new_buy_count": new_buy_count,
        "new_sell_count": new_sell_count,
        "skipped_insufficient_capital": len(skipped_capital_symbols),
        "open_positions": len(open_positions),
        "winning_positions": winning_count,
        "losing_positions": losing_count,
        "available_cash": round(available_cash, 2),
        "net_worth": net_worth,
    }
    logger.info("Trial scan complete: %s", summary)
    return summary


def monitor_open_positions(
    state_path: Path = STATE_PATH,
    trade_log_path: Path = TRADE_LOG_PATH,
    market_provider: MarketDataProvider | None = None,
    notify=send_telegram,
) -> dict:
    """INTRADAY position monitoring — runs ~4x/day during market hours
    (9:30, 11:30, 13:30, 14:30 IST). Checks ONLY already-open positions
    against a CURRENT price (MONITOR_INTERVAL/MONITOR_PERIOD): stop-loss
    hit -> close (full exit, logged to trade_log); neither hit -> hold,
    unchanged; target1 hit -> stop-loss shifts to target1 (locks in the
    3% gain), position keeps running. NEVER opens a new position — that
    is scan_new_signals()'s job alone.

    Sends exactly TWO kinds of Telegram message per run — one monitor
    summary, and one (or a few, chunked) holding-status message."""
    provider = market_provider or MarketDataProvider()
    state = load_state(state_path)
    open_positions = state["open_positions"]
    capital = state["capital"]
    available_cash = float(capital["available_cash"])
    starting_capital = float(capital["starting_capital"])

    target1_shift_symbols: list[str] = []
    stop_hit_symbols: list[str] = []
    latest_close_by_symbol: dict[str, float] = {}
    checked_count = 0

    for symbol in list(open_positions.keys()):
        current_price = fetch_current_price(symbol, provider)
        if current_price is None:
            logger.warning(
                "Current-price fetch failed/empty for %s — skipping this "
                "monitoring cycle, position left untouched.",
                symbol,
            )
            continue

        checked_count += 1
        latest_close_by_symbol[symbol] = current_price
        open_positions[symbol]["last_known_price"] = current_price
        open_positions[symbol]["last_checked_at"] = _now_iso()

        position, events = monitor_position(open_positions[symbol], current_price)

        closed = False
        for event_type, level in events:
            if event_type == "TARGET1_HIT_SL_SHIFTED":
                target1_shift_symbols.append(symbol)
            elif event_type == "STOP_LOSS_HIT":
                stop_hit_symbols.append(symbol)
                entry_price = position["entry_price"]
                quantity = position.get("quantity", 0)
                invested_amount = position.get("invested_amount", 0.0)
                pnl_percent = _pnl_percent(position["direction"], entry_price, current_price)
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
                        "exit_price": current_price,
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

    capital["available_cash"] = round(available_cash, 2)
    state["capital"] = capital
    save_state(state, state_path)

    net_worth = available_cash + sum(
        pos.get("quantity", 0) * latest_close_by_symbol.get(sym, pos["entry_price"])
        for sym, pos in open_positions.items()
    )
    net_worth = round(net_worth, 2)

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

    monitor_summary = _format_monitor_summary(
        checked_count=checked_count,
        target1_shift_symbols=target1_shift_symbols,
        stop_hit_symbols=stop_hit_symbols,
        open_count=len(open_positions),
        winning_count=winning_count,
        losing_count=losing_count,
        available_cash=round(available_cash, 2),
        net_worth=net_worth,
        starting_capital=starting_capital,
    )
    notify(monitor_summary)

    for holding_message in _format_holding_status_messages(open_positions, latest_close_by_symbol):
        notify(holding_message)

    summary = {
        "checked": checked_count,
        "target1_shifts": len(target1_shift_symbols),
        "stop_losses_hit": len(stop_hit_symbols),
        "open_positions": len(open_positions),
        "winning_positions": winning_count,
        "losing_positions": losing_count,
        "available_cash": round(available_cash, 2),
        "net_worth": net_worth,
    }
    logger.info("Trial position monitor complete: %s", summary)
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
    parser.add_argument(
        "--mode",
        choices=["scan", "monitor"],
        default="scan",
        help=(
            "'scan' (default): DAILY, after market close — EOD data, opens "
            "new positions only. 'monitor': INTRADAY, ~4x/day — current "
            "price, checks existing open positions only (stop-loss/"
            "target1), never opens new positions."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the NSE-trading-day check (testing only — e.g. to verify "
        "a fix on a market holiday). Normal scheduled runs never pass this.",
    )
    args = parser.parse_args()

    # BUG FIX (found 2026-08-24): this script had NO trading-day gate at
    # all — unlike morning_executor.py / generate_full_report.py, which
    # both call is_trading_day() before doing anything. Both GitHub
    # Actions crons for this script (trial_ema_bb_strategy.yml,
    # trial_position_monitor.yml) use "* * *" for day-of-week, so they
    # fire every single day including weekends/NSE holidays — and this
    # script would happily scan/monitor on those days too (yfinance
    # just returns stale/repeated data), wasting runs and risking
    # misleading signals or Telegram spam on non-trading days.
    today_date = date.today()
    if not args.force and not is_trading_day(today_date):
        reason = skip_reason(today_date) or "Non-trading day"
        logger.info("Not an NSE trading day — exiting before any scan/monitor begins.")
        print(f"Not an NSE trading day ({reason}). No {args.mode} performed.")
        send_telegram(
            f"⏸️ [TRIAL_EMA_BB_STRATEGY] Skipped ({args.mode})\n"
            f"Reason: {reason}\n"
            f"No scan/monitor was executed today."
        )
        return

    if args.mode == "monitor":
        summary = monitor_open_positions()
        print(
            f"Done. Checked: {summary['checked']}. "
            f"Target1 stop-shifts: {summary['target1_shifts']}, "
            f"Stop-losses hit: {summary['stop_losses_hit']}, "
            f"Open positions now: {summary['open_positions']} "
            f"({summary['winning_positions']} winning, {summary['losing_positions']} losing). "
            f"Available Cash: ₹{summary['available_cash']:,.2f}, "
            f"Net Worth: ₹{summary['net_worth']:,.2f}."
        )
        return

    symbols = _load_symbols(args.symbols, args.symbols_file)
    if not symbols:
        print("No symbols to scan — exiting.")
        return

    print(
        f"NOTE: interval={INTERVAL!r} period={PERIOD!r} — this now reuses "
        f"data/market_data.py's own period='1y' buffer fix (a genuine "
        f"~400 calendar-day lookback, not yfinance's raw period='1y' "
        f"string, which alone would land right at the warm-up threshold "
        f"— see that file's NOTE), so ema_{EMA_SLOW} here IS a genuinely "
        f"mature {EMA_SLOW}-day EMA, unlike the old period='1mo' version."
    )
    print(f"Scanning {len(symbols)} symbol(s)...")

    summary = scan_new_signals(symbols)

    print(
        f"Done. BUY: {summary['buy_count']} | SELL: {summary['sell_count']} | "
        f"NO_TRADE: {summary['no_trade_count']}. "
        f"New positions: {summary['new_signals']} "
        f"({summary['new_buy_count']} BUY, {summary['new_sell_count']} SELL). "
        f"Skipped (insufficient capital): {summary['skipped_insufficient_capital']}, "
        f"Open positions now: {summary['open_positions']}. "
        f"Available Cash: ₹{summary['available_cash']:,.2f}, "
        f"Net Worth: ₹{summary['net_worth']:,.2f}."
    )


if __name__ == "__main__":
    main()
