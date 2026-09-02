"""
Tests for scripts/trial_ema_bb_strategy.py — the TEMPORARY trial
strategy (EMA(50/200) fresh-cross, fixed-percent risk management).
Covers the pure logic functions directly and the two orchestration
entry points — scan_new_signals() (daily, EOD, opens new positions
only) and monitor_open_positions() (intraday, current price, checks
existing positions only) — with a mocked market-data provider /
Telegram sender, so no real network calls happen in tests.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.trial_ema_bb_strategy import (
    EMA_FAST,
    EMA_SLOW,
    STARTING_CAPITAL,
    STOP_LOSS_PERCENT,
    TARGET1_PERCENT,
    _default_state,
    _format_holding_entry,
    _format_holding_status_messages,
    _format_monitor_summary,
    _format_scan_summary,
    _load_symbols,
    _pnl_amount,
    _pnl_percent,
    append_trade_log,
    compute_atr,
    compute_emas,
    compute_initial_stop_target,
    compute_position_size,
    compute_volume_average,
    evaluate_signal,
    fetch_current_price,
    load_state,
    monitor_open_positions,
    monitor_position,
    save_state,
    scan_new_signals,
    send_telegram,
)


def _synthetic_ohlcv(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        }
    )


def _fresh_buy_series() -> list[float]:
    """A real (not hand-waved) fresh BUY setup: a long enough uptrend to
    get price genuinely above ema_200, a pullback that dips price below
    ema_50 for several days (so "previous close <= previous ema_50" is
    true), then one sharp breakout day that pushes close back above
    ema_50 while still comfortably above ema_200. Verified by actually
    running compute_emas()/evaluate_signal() over this exact series —
    not asserted from theory alone."""
    phase1 = [100.0 + i * 1.5 for i in range(80)]  # steady uptrend
    phase2 = [phase1[-1] - i * 3 for i in range(1, 11)]  # pullback below ema_50
    phase3 = [phase2[-1] + 10]  # fresh breakout day
    return phase1 + phase2 + phase3


def _fresh_sell_series() -> list[float]:
    """Mirror of _fresh_buy_series(): a downtrend that drags price below
    ema_200, a bounce long/strong enough to lift price back above
    ema_200 (so "previous close >= previous ema_200" is true), then one
    sharp drop day that pushes close back below ema_200 AND below
    ema_50 (the SELL-side confirmation). Also verified by actually
    running the real functions over this exact series."""
    phase1 = [300.0 - i * 1.0 for i in range(60)]  # steady downtrend
    phase2 = [phase1[-1] + i * 3 for i in range(1, 16)]  # bounce above ema_200
    phase3 = [phase2[-1] - 25]  # fresh drop day
    return phase1 + phase2 + phase3


# ---------------------------------------------------------------------
# compute_emas
# ---------------------------------------------------------------------


def test_compute_emas_adds_expected_columns():
    df = _synthetic_ohlcv([100.0 + i for i in range(30)])
    result = compute_emas(df)

    assert f"ema_{EMA_FAST}" in result.columns
    assert f"ema_{EMA_SLOW}" in result.columns
    # original dataframe must not be mutated in place
    assert f"ema_{EMA_FAST}" not in df.columns


def test_compute_emas_no_nan_even_with_short_history():
    # pandas .ewm(adjust=False) never produces NaN once the series has
    # at least 1 value — even with far fewer than `span` rows. This
    # test locks in that (documented, flagged-in-docstring) behavior.
    df = _synthetic_ohlcv([100.0, 101.0, 102.0])
    result = compute_emas(df)
    assert not result[f"ema_{EMA_SLOW}"].isna().any()


# ---------------------------------------------------------------------
# evaluate_signal
# ---------------------------------------------------------------------


def test_evaluate_signal_buy_on_fresh_cross_above_fast_with_slow_confirmation():
    # yesterday at/below ema_50 (fresh trigger), today above ema_50 AND
    # above ema_200 (confirmation the longer-term trend already agrees).
    previous = pd.Series({"close": 99.0, "ema_50": 100.0, "ema_200": 90.0})
    latest = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": 90.0})
    assert evaluate_signal(latest, previous) == "BUY"


def test_evaluate_signal_sell_on_fresh_cross_below_slow_with_fast_confirmation():
    # mirror, roles swapped: yesterday at/above ema_200 (fresh trigger),
    # today below ema_200 AND below ema_50 (confirmation).
    previous = pd.Series({"close": 101.0, "ema_50": 95.0, "ema_200": 100.0})
    latest = pd.Series({"close": 94.0, "ema_50": 95.0, "ema_200": 100.0})
    assert evaluate_signal(latest, previous) == "SELL"


def test_evaluate_signal_no_trade_when_no_previous_candle():
    # first row of a series — no yesterday to compare against, so
    # "fresh" cannot be evaluated either way.
    latest = pd.Series({"close": 110.0, "ema_50": 100.0, "ema_200": 90.0})
    assert evaluate_signal(latest, None) == "NO_TRADE"


def test_evaluate_signal_no_trade_when_above_fast_but_not_confirmed_by_slow():
    # fresh cross above ema_50, but NOT above ema_200 — confirmation
    # fails, must not fire BUY on the trigger alone.
    previous = pd.Series({"close": 99.0, "ema_50": 100.0, "ema_200": 110.0})
    latest = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": 110.0})
    assert evaluate_signal(latest, previous) == "NO_TRADE"


def test_evaluate_signal_no_trade_when_already_above_fast_yesterday():
    # already above ema_50 yesterday too (and above ema_200) — real,
    # but NOT a fresh cross, so must not fire BUY every day it stays up.
    previous = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": 90.0})
    latest = pd.Series({"close": 102.0, "ema_50": 100.0, "ema_200": 90.0})
    assert evaluate_signal(latest, previous) == "NO_TRADE"


def test_evaluate_signal_no_trade_when_ema_is_nan():
    previous = pd.Series({"close": 99.0, "ema_50": 100.0, "ema_200": 90.0})
    latest = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": float("nan")})
    assert evaluate_signal(latest, previous) == "NO_TRADE"


def test_evaluate_signal_no_trade_when_previous_ema_is_nan():
    previous = pd.Series({"close": 99.0, "ema_50": float("nan"), "ema_200": 90.0})
    latest = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": 90.0})
    assert evaluate_signal(latest, previous) == "NO_TRADE"


def test_evaluate_signal_buy_boundary_previous_close_exactly_at_fast_ema():
    # previous close exactly equal to ema_50 counts as "at/below" (<=)
    # — the boundary is inclusive on the not-yet-crossed side.
    previous = pd.Series({"close": 100.0, "ema_50": 100.0, "ema_200": 90.0})
    latest = pd.Series({"close": 101.0, "ema_50": 100.0, "ema_200": 90.0})
    assert evaluate_signal(latest, previous) == "BUY"


# ---------------------------------------------------------------------
# compute_initial_stop_target
# ---------------------------------------------------------------------


def test_compute_initial_stop_target_buy():
    stop_loss, target1 = compute_initial_stop_target("BUY", 1000.0)
    assert stop_loss == round(1000.0 * (1 - STOP_LOSS_PERCENT), 2)
    assert target1 == round(1000.0 * (1 + TARGET1_PERCENT), 2)
    assert stop_loss < 1000.0 < target1


def test_compute_initial_stop_target_sell():
    stop_loss, target1 = compute_initial_stop_target("SELL", 1000.0)
    assert stop_loss == round(1000.0 * (1 + STOP_LOSS_PERCENT), 2)
    assert target1 == round(1000.0 * (1 - TARGET1_PERCENT), 2)
    assert target1 < 1000.0 < stop_loss


# ---------------------------------------------------------------------
# compute_atr / compute_volume_average
# ---------------------------------------------------------------------


def test_compute_atr_nan_before_period_minus_one_bars():
    df = _synthetic_ohlcv([100.0 + i for i in range(10)])  # only 10 bars, ATR_PERIOD=14
    atr = compute_atr(df)
    assert atr.isna().all()  # never enough history for a real ATR(14) yet


def test_compute_atr_has_real_value_once_enough_history():
    df = _synthetic_ohlcv([100.0 + i for i in range(30)])
    atr = compute_atr(df)
    assert not pd.isna(atr.iloc[-1])
    assert atr.iloc[-1] > 0  # real true-range based volatility, not zero/fabricated


def test_compute_volume_average_uses_partial_window():
    df = pd.DataFrame(
        {
            "open": [1, 1, 1, 1, 1],
            "high": [1, 1, 1, 1, 1],
            "low": [1, 1, 1, 1, 1],
            "close": [1, 1, 1, 1, 1],
            "volume": [100, 200, 300, 400, 500],
        }
    )
    avg = compute_volume_average(df)
    # only 5 rows available (< VOLUME_AVG_PERIOD=20) — min_periods=1 means
    # the latest value is the mean of everything available so far, not NaN.
    assert avg.iloc[-1] == pytest.approx(300.0)


# ---------------------------------------------------------------------
# compute_position_size
# ---------------------------------------------------------------------


def test_compute_position_size_basic_case():
    sizing = compute_position_size(
        entry_price=100.0,
        stop_distance=1.5,
        atr_percent=0.5,  # <=1.0 -> volatility_adjustment=1.00
        average_volume=6_000_000,  # >=5M -> liquidity_adjustment=1.00
        total_capital=100_000.0,
        available_cash=100_000.0,
    )
    # base_allocation = 0.02 + 0.18*0.5 = 0.11; adjustment_factor = 1.0
    assert sizing["allocation_percent"] == pytest.approx(0.11)
    assert sizing["kelly_fraction"] == pytest.approx(0.5)
    assert sizing["volatility_adjustment"] == pytest.approx(1.00)
    assert sizing["liquidity_adjustment"] == pytest.approx(1.00)
    # capital_quantity = floor(11000/100) = 110; atr_quantity = floor(2000/1.5) = 1333
    assert sizing["capital_quantity"] == 110
    assert sizing["atr_quantity"] == 1333
    assert sizing["quantity"] == 110  # capital-bound, not ATR-bound
    assert sizing["position_value"] == pytest.approx(11_000.0)


def test_compute_position_size_atr_bound_when_stop_distance_wide():
    sizing = compute_position_size(
        entry_price=10.0,
        stop_distance=10.0,  # wide stop relative to a small risk budget
        atr_percent=0.5,
        average_volume=6_000_000,
        total_capital=1_000.0,  # risk_per_trade = 20
        available_cash=100_000.0,
    )
    assert sizing["atr_quantity"] == 2  # floor(20/10)
    assert sizing["quantity"] == 2  # ATR-bound, not capital-bound


def test_compute_position_size_zero_when_capital_too_small():
    sizing = compute_position_size(
        entry_price=100_000.0,  # a very expensive stock
        stop_distance=1_500.0,
        atr_percent=0.5,
        average_volume=6_000_000,
        total_capital=100.0,
        available_cash=100.0,  # nowhere near 1 share's worth
    )
    assert sizing["quantity"] == 0  # legitimately 0, never forced to 1
    assert sizing["position_value"] == 0.0


def test_compute_position_size_low_liquidity_low_volatility_bucket_math():
    sizing = compute_position_size(
        entry_price=100.0,
        stop_distance=1.5,
        atr_percent=6.0,  # >5.0 -> volatility_adjustment=0.40
        average_volume=100_000,  # <500k -> liquidity_adjustment=0.40
        total_capital=100_000.0,
        available_cash=100_000.0,
    )
    assert sizing["volatility_adjustment"] == pytest.approx(0.40)
    assert sizing["liquidity_adjustment"] == pytest.approx(0.40)
    # allocation clamped to MIN_CAPITAL_ALLOCATION floor (0.02) since
    # 0.11 * 0.16 = 0.0176 < 0.02
    assert sizing["allocation_percent"] == pytest.approx(0.02)


# ---------------------------------------------------------------------
# _pnl_amount
# ---------------------------------------------------------------------


def test_pnl_amount_matches_percent_of_invested():
    assert _pnl_amount(10_000.0, 5.0) == pytest.approx(500.0)
    assert _pnl_amount(10_000.0, -3.0) == pytest.approx(-300.0)
    assert _pnl_amount(0.0, 10.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------
# fetch_current_price
# ---------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, frames: dict):
        self._frames = frames

    def fetch(self, symbol, interval, period):
        return self._frames[symbol]


def test_fetch_current_price_returns_latest_close():
    provider = _FakeProvider({"TEST.NS": _synthetic_ohlcv([100.0, 101.0, 102.5])})
    price = fetch_current_price("TEST.NS", provider)
    assert price == pytest.approx(102.5)


def test_fetch_current_price_returns_none_on_fetch_exception():
    class ExplodingProvider:
        def fetch(self, symbol, interval, period):
            raise RuntimeError("yfinance down")

    assert fetch_current_price("BAD.NS", ExplodingProvider()) is None


def test_fetch_current_price_returns_none_on_empty_dataframe():
    provider = _FakeProvider({"EMPTY.NS": pd.DataFrame()})
    assert fetch_current_price("EMPTY.NS", provider) is None


def test_fetch_current_price_returns_none_when_dataframe_is_none():
    class NoneProvider:
        def fetch(self, symbol, interval, period):
            return None

    assert fetch_current_price("NONE.NS", NoneProvider()) is None


# ---------------------------------------------------------------------
# monitor_position
# ---------------------------------------------------------------------


def _open_position(direction: str, entry_price: float = 1000.0, quantity: int = 10) -> dict:
    stop_loss, target1 = compute_initial_stop_target(direction, entry_price)
    return {
        "trade_id": "trial_TEST_1",
        "symbol": "TEST.NS",
        "direction": direction,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_time": "2026-08-19T00:00:00+00:00",
        "invested_amount": round(quantity * entry_price, 2),
        "stop_loss": stop_loss,
        "target1": target1,
        "target1_hit": False,
    }


def test_monitor_position_buy_target1_hit_shifts_stop_loss():
    position = _open_position("BUY")
    updated, events = monitor_position(position, 1030.0)  # +3%, at target1

    assert updated["target1_hit"] is True
    assert updated["stop_loss"] == updated["target1"]
    assert ("TARGET1_HIT_SL_SHIFTED", pytest.approx(1030.0, rel=1e-3)) in events


def test_monitor_position_buy_stop_loss_hit():
    position = _open_position("BUY")
    updated, events = monitor_position(position, position["stop_loss"] - 1.0)

    assert any(event_type == "STOP_LOSS_HIT" for event_type, _ in events)
    assert updated["target1_hit"] is False


def test_monitor_position_sell_target1_hit_shifts_stop_loss():
    position = _open_position("SELL")
    updated, events = monitor_position(position, 970.0)  # -3%, at target1

    assert updated["target1_hit"] is True
    assert updated["stop_loss"] == updated["target1"]
    assert ("TARGET1_HIT_SL_SHIFTED", pytest.approx(970.0, rel=1e-3)) in events


def test_monitor_position_sell_stop_loss_hit():
    position = _open_position("SELL")
    updated, events = monitor_position(position, position["stop_loss"] + 1.0)

    assert any(event_type == "STOP_LOSS_HIT" for event_type, _ in events)


def test_monitor_position_target1_not_retriggered_once_hit():
    position = _open_position("BUY")
    position["target1_hit"] = True
    position["stop_loss"] = position["target1"]  # already shifted

    _, events = monitor_position(position, position["target1"] + 5.0)

    assert not any(event_type == "TARGET1_HIT_SL_SHIFTED" for event_type, _ in events)


def test_monitor_position_no_event_between_stop_and_target():
    position = _open_position("BUY")
    midpoint = (position["stop_loss"] + position["target1"]) / 2
    _, events = monitor_position(position, midpoint)
    assert events == []


def test_monitor_position_target1_and_stop_hit_same_bar_buy():
    # a wide intraday-equivalent move (using close only, per this
    # trial's design) can cross target1 AND then reverse below the
    # newly-shifted stop within the same evaluated close — both events
    # should be reported, not silently dropped.
    position = _open_position("BUY")
    # close sits AT target1 exactly, which also is the new stop_loss —
    # <= stop_loss check fires too since target1 becomes the new floor.
    updated, events = monitor_position(position, position["target1"])
    event_types = {event_type for event_type, _ in events}
    assert "TARGET1_HIT_SL_SHIFTED" in event_types
    assert "STOP_LOSS_HIT" in event_types
    assert updated["stop_loss"] == position["target1"]


def test_monitor_position_tracks_highest_and_lowest_price():
    position = _open_position("BUY")
    position, _ = monitor_position(position, 1010.0)
    position, _ = monitor_position(position, 990.0)
    position, _ = monitor_position(position, 1005.0)

    assert position["highest_price"] == 1010.0
    assert position["lowest_price"] == 990.0


def test_monitor_position_highest_lowest_default_to_entry_when_absent():
    position = _open_position("BUY")
    assert "highest_price" not in position  # helper doesn't set these
    updated, _ = monitor_position(position, position["entry_price"])
    assert updated["highest_price"] == position["entry_price"]
    assert updated["lowest_price"] == position["entry_price"]


# ---------------------------------------------------------------------
# _pnl_percent
# ---------------------------------------------------------------------


def test_pnl_percent_buy_profit():
    assert _pnl_percent("BUY", 100.0, 110.0) == pytest.approx(10.0)


def test_pnl_percent_sell_profit():
    assert _pnl_percent("SELL", 100.0, 90.0) == pytest.approx(10.0)


def test_pnl_percent_buy_loss():
    assert _pnl_percent("BUY", 100.0, 95.0) == pytest.approx(-5.0)


# ---------------------------------------------------------------------
# state persistence
# ---------------------------------------------------------------------


def test_load_state_missing_file_returns_default_state_with_starting_capital(tmp_path):
    state = load_state(tmp_path / "does_not_exist.json")
    assert state == _default_state()
    assert state["open_positions"] == {}
    assert state["capital"]["starting_capital"] == STARTING_CAPITAL
    assert state["capital"]["available_cash"] == STARTING_CAPITAL


def test_save_and_load_state_roundtrip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state = {
        "open_positions": {"TEST.NS": _open_position("BUY")},
        "capital": {"starting_capital": 50_000.0, "available_cash": 42_000.0},
    }

    save_state(state, path)
    reloaded = load_state(path)

    assert reloaded == state


def test_load_state_tolerates_missing_open_positions_key(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    state = load_state(path)
    assert state["open_positions"] == {}


def test_load_state_tolerates_missing_capital_key(tmp_path):
    # An old state.json written before capital tracking existed —
    # must NOT crash, and must backfill STARTING_CAPITAL rather than
    # 0 (which would look like the account is already broke).
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"open_positions": {}}), encoding="utf-8")

    state = load_state(path)
    assert state["capital"]["available_cash"] == STARTING_CAPITAL
    assert state["capital"]["starting_capital"] == STARTING_CAPITAL


def test_load_state_preserves_real_available_cash_on_subsequent_runs(tmp_path):
    # This is the important case: once a state file exists with a
    # REAL (non-default) available_cash, loading it must never
    # silently reset back to STARTING_CAPITAL.
    path = tmp_path / "state.json"
    save_state(
        {"open_positions": {}, "capital": {"starting_capital": STARTING_CAPITAL, "available_cash": 37_500.25}},
        path,
    )
    state = load_state(path)
    assert state["capital"]["available_cash"] == 37_500.25


# ---------------------------------------------------------------------
# trade log
# ---------------------------------------------------------------------


def _trade_row(symbol: str = "TEST.NS") -> dict:
    return {
        "trade_id": "trial_TEST_1",
        "symbol": symbol,
        "direction": "BUY",
        "quantity": 10,
        "entry_price": 1000.0,
        "entry_time": "2026-08-19T00:00:00+00:00",
        "invested_amount": 10000.0,
        "exit_price": 985.0,
        "exit_time": "2026-08-20T00:00:00+00:00",
        "exit_reason": "STOP_LOSS_HIT",
        "target1_hit": False,
        "pnl_percent": -1.5,
        "pnl_amount": -150.0,
    }


def test_append_trade_log_writes_header_once(tmp_path):
    path = tmp_path / "trade_log.csv"
    append_trade_log(_trade_row(), path)
    append_trade_log(_trade_row(), path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("trade_id,")
    assert len(lines) == 3  # header + 2 rows
    assert sum(1 for line in lines if line.startswith("trade_id,")) == 1


def test_append_trade_log_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / "trade_log.csv"
    append_trade_log(_trade_row(), path)
    assert path.exists()


# ---------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------


def test_send_telegram_skips_when_creds_missing(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    # Should not raise even with no creds configured.
    send_telegram("test message")


def test_send_telegram_calls_alert_when_creds_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "fake-chat")

    sent = {}

    class FakeTelegramAlert:
        def __init__(self, bot_token, chat_id):
            sent["bot_token"] = bot_token
            sent["chat_id"] = chat_id

        def send(self, message, raw=False):
            sent["message"] = message
            sent["raw"] = raw

    monkeypatch.setattr(
        "scripts.trial_ema_bb_strategy.TelegramAlert",
        FakeTelegramAlert,
    )

    send_telegram("hello trial")

    assert sent["bot_token"] == "fake-token"
    assert sent["chat_id"] == "fake-chat"
    assert sent["message"] == "hello trial"
    assert sent["raw"] is True


def test_send_telegram_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "fake-chat")

    class ExplodingTelegramAlert:
        def __init__(self, bot_token, chat_id):
            pass

        def send(self, message, raw=False):
            raise RuntimeError("network down")

    monkeypatch.setattr(
        "scripts.trial_ema_bb_strategy.TelegramAlert",
        ExplodingTelegramAlert,
    )

    # Must not propagate — a Telegram outage should never crash the scan.
    send_telegram("should not raise")


# ---------------------------------------------------------------------
# _load_symbols
# ---------------------------------------------------------------------


def test_load_symbols_explicit_list_overrides_watchlist():
    symbols = _load_symbols("hdfcbank.ns, tcs.ns", "storage/watchlist/nifty500.json")
    assert symbols == ["HDFCBANK.NS", "TCS.NS"]


def test_load_symbols_falls_back_to_watchlist_file(monkeypatch):
    monkeypatch.setattr(
        "scripts.trial_ema_bb_strategy.WatchlistManager.load",
        lambda self: ["FAKESYM.NS"],
    )
    symbols = _load_symbols("", "storage/watchlist/nifty500.json")
    assert symbols == ["FAKESYM.NS"]


# ---------------------------------------------------------------------
# scan_new_signals() — daily scan orchestration, mocked provider/notifier
# ---------------------------------------------------------------------


def test_scan_sends_exactly_one_scan_summary_message(tmp_path):
    flat = _synthetic_ohlcv([100.0] * 30)
    provider = _FakeProvider({"FLAT.NS": flat})
    messages = []

    scan_new_signals(
        symbols=["FLAT.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    # No open positions -> only the scan-summary message, never one
    # message per symbol/signal, and NEVER a holding-status message
    # (that is monitor_open_positions()'s job).
    assert len(messages) == 1
    assert messages[0].startswith("[TRIAL_SCAN_COMPLETED]")


def test_scan_opens_new_position_on_buy_signal(tmp_path):
    uptrend = _synthetic_ohlcv(_fresh_buy_series())
    provider = _FakeProvider({"UP.NS": uptrend})
    messages = []

    summary = scan_new_signals(
        symbols=["UP.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 1
    assert summary["new_buy_count"] == 1
    assert summary["open_positions"] == 1
    assert "New positions opened: 1 (1 BUY, 0 SELL)" in messages[0]

    state = load_state(tmp_path / "state.json")
    assert "UP.NS" in state["open_positions"]
    position = state["open_positions"]["UP.NS"]
    assert position["direction"] == "BUY"
    assert position["quantity"] > 0
    assert position["invested_amount"] == round(position["quantity"] * position["entry_price"], 2)
    # new fields for ad-hoc analysis between monitor runs
    assert position["last_known_price"] == position["entry_price"]
    assert position["last_checked_at"]

    # capital was actually debited by the invested amount
    assert state["capital"]["available_cash"] == round(
        STARTING_CAPITAL - position["invested_amount"], 2
    )
    assert summary["available_cash"] == state["capital"]["available_cash"]


def test_scan_opens_new_position_on_sell_signal(tmp_path):
    downtrend = _synthetic_ohlcv(_fresh_sell_series())
    provider = _FakeProvider({"DOWN.NS": downtrend})
    messages = []

    summary = scan_new_signals(
        symbols=["DOWN.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 1
    assert summary["new_sell_count"] == 1
    state = load_state(tmp_path / "state.json")
    position = state["open_positions"]["DOWN.NS"]
    assert position["direction"] == "SELL"
    assert position["quantity"] > 0


def test_scan_skips_new_position_when_capital_exhausted(tmp_path):
    uptrend = _synthetic_ohlcv(_fresh_buy_series())
    provider = _FakeProvider({"UP.NS": uptrend})

    state_path = tmp_path / "state.json"
    save_state(
        {
            "open_positions": {},
            "capital": {"starting_capital": STARTING_CAPITAL, "available_cash": 0.0},
        },
        state_path,
    )

    messages = []
    summary = scan_new_signals(
        symbols=["UP.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 0
    assert summary["skipped_insufficient_capital"] == 1
    assert "Signal found but skipped (insufficient capital/risk budget): 1 (UP.NS)" in messages[0]


def test_scan_reports_buy_sell_no_trade_counts_across_all_scanned_symbols(tmp_path):
    uptrend = _synthetic_ohlcv(_fresh_buy_series())
    downtrend = _synthetic_ohlcv(_fresh_sell_series())
    flat = _synthetic_ohlcv([100.0] * 30)
    provider = _FakeProvider({"UP.NS": uptrend, "DOWN.NS": downtrend, "FLAT.NS": flat})

    summary = scan_new_signals(
        symbols=["UP.NS", "DOWN.NS", "FLAT.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["buy_count"] == 1
    assert summary["sell_count"] == 1
    assert summary["no_trade_count"] == 1


def test_scan_no_signal_when_flat(tmp_path):
    flat = _synthetic_ohlcv([100.0] * 30)
    provider = _FakeProvider({"FLAT.NS": flat})

    summary = scan_new_signals(
        symbols=["FLAT.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["new_signals"] == 0


def test_scan_skips_fresh_signal_check_when_position_already_open(tmp_path):
    # a genuine fresh BUY signal is present (see _fresh_buy_series()) but
    # a position is already open for this symbol — must not open a
    # second position for the same symbol.
    uptrend = _synthetic_ohlcv(_fresh_buy_series())
    provider = _FakeProvider({"UP.NS": uptrend})

    state_path = tmp_path / "state.json"
    existing_position = _open_position("BUY", entry_price=50.0)
    save_state({"open_positions": {"UP.NS": existing_position}}, state_path)

    summary = scan_new_signals(
        symbols=["UP.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["new_signals"] == 0
    assert summary["open_positions"] == 1  # still just the one pre-existing position


def test_scan_never_checks_stop_loss_or_target1_on_existing_position(tmp_path):
    # Even though this price would trip the stop-loss if scan checked
    # it, scan_new_signals() must NOT act on existing positions at
    # all — that is monitor_open_positions()'s job alone.
    position = _open_position("BUY", entry_price=1000.0, quantity=10)
    crash_price = position["stop_loss"] - 5.0
    crash = _synthetic_ohlcv([crash_price] * 5)
    provider = _FakeProvider({"OPEN.NS": crash})

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    summary = scan_new_signals(
        symbols=["OPEN.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["open_positions"] == 1  # left open, untouched
    final_state = load_state(state_path)
    assert "OPEN.NS" in final_state["open_positions"]
    assert final_state["open_positions"]["OPEN.NS"]["stop_loss"] == position["stop_loss"]


def test_scan_passively_updates_last_known_price_on_existing_position(tmp_path):
    position = _open_position("BUY", entry_price=1000.0, quantity=10)
    flat = _synthetic_ohlcv([1010.0] * 5)
    provider = _FakeProvider({"OPEN.NS": flat})

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    scan_new_signals(
        symbols=["OPEN.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    final_state = load_state(state_path)
    assert final_state["open_positions"]["OPEN.NS"]["last_known_price"] == 1010.0
    assert final_state["open_positions"]["OPEN.NS"]["last_checked_at"]


def test_scan_handles_fetch_failure_gracefully(tmp_path):
    class ExplodingProvider:
        def fetch(self, symbol, interval, period):
            raise RuntimeError("yfinance down")

    summary = scan_new_signals(
        symbols=["BAD.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=ExplodingProvider(),
        notify=lambda m: None,
    )
    assert summary["new_signals"] == 0
    assert summary["open_positions"] == 0


def test_scan_handles_empty_dataframe_gracefully(tmp_path):
    provider = _FakeProvider({"EMPTY.NS": pd.DataFrame()})
    summary = scan_new_signals(
        symbols=["EMPTY.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )
    assert summary["new_signals"] == 0


def test_scan_reports_winning_and_losing_open_position_counts(tmp_path):
    # WIN.NS is well above its entry (winning); LOSS.NS is below its
    # entry but not yet at stop_loss (losing, still open).
    win_position = _open_position("BUY", entry_price=100.0, quantity=1)
    loss_position = _open_position("BUY", entry_price=100.0, quantity=1)

    provider = _FakeProvider(
        {
            "WIN.NS": _synthetic_ohlcv([105.0] * 5),
            # stop_loss for a 100.0 entry is 98.5 — 99.0 is losing but
            # not yet stopped out, so the position stays open.
            "LOSS.NS": _synthetic_ohlcv([99.0] * 5),
        }
    )

    state_path = tmp_path / "state.json"
    save_state(
        {
            "open_positions": {"WIN.NS": win_position, "LOSS.NS": loss_position},
            "capital": {"starting_capital": STARTING_CAPITAL, "available_cash": STARTING_CAPITAL},
        },
        state_path,
    )

    summary = scan_new_signals(
        symbols=["WIN.NS", "LOSS.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["winning_positions"] == 1
    assert summary["losing_positions"] == 1


# ---------------------------------------------------------------------
# monitor_open_positions() — intraday monitor orchestration, mocked
# provider/notifier
# ---------------------------------------------------------------------


def test_monitor_never_opens_a_new_position(tmp_path):
    # Even with zero open positions and an empty state, monitoring must
    # do nothing — opening positions is scan_new_signals()'s job alone.
    provider = _FakeProvider({})
    summary = monitor_open_positions(
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )
    assert summary["checked"] == 0
    assert summary["open_positions"] == 0


def test_monitor_shifts_stop_loss_on_target1_and_reports_it(tmp_path):
    # 1035 > target1 (1030) but does not also touch the newly-shifted
    # stop_loss (1030) — isolates the shift event from a same-bar close.
    provider = _FakeProvider({"OPEN.NS": _synthetic_ohlcv([1035.0] * 5)})

    state_path = tmp_path / "state.json"
    position = _open_position("BUY", entry_price=1000.0)
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    messages = []
    summary = monitor_open_positions(
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["target1_shifts"] == 1
    assert messages[0].startswith("[TRIAL_POSITION_MONITOR]")
    assert "Target1 hit, stop-loss shifted: 1 (OPEN.NS)" in messages[0]
    # and the holding-status message reflects the shift too
    holding_message = next(m for m in messages if m.startswith("[TRIAL_HOLDING_STATUS]"))
    assert "Target1 (3%): HIT" in holding_message

    final_state = load_state(state_path)
    assert final_state["open_positions"]["OPEN.NS"]["target1_hit"] is True


def test_monitor_closes_position_on_stop_loss_and_writes_trade_log(tmp_path):
    position = _open_position("BUY", entry_price=1000.0, quantity=10)
    crash_price = position["stop_loss"] - 5.0
    provider = _FakeProvider({"OPEN.NS": _synthetic_ohlcv([crash_price] * 5)})

    state_path = tmp_path / "state.json"
    trade_log_path = tmp_path / "trade_log.csv"
    starting_cash = 50_000.0
    save_state(
        {
            "open_positions": {"OPEN.NS": position},
            "capital": {
                "starting_capital": STARTING_CAPITAL,
                "available_cash": starting_cash,
            },
        },
        state_path,
    )

    messages = []
    summary = monitor_open_positions(
        state_path=state_path,
        trade_log_path=trade_log_path,
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["stop_losses_hit"] == 1
    assert summary["open_positions"] == 0
    assert "Stop-loss hit, closed: 1 (OPEN.NS)" in messages[0]
    # position is closed -> no holding-status message at all
    assert not any(m.startswith("[TRIAL_HOLDING_STATUS]") for m in messages)

    final_state = load_state(state_path)
    assert "OPEN.NS" not in final_state["open_positions"]

    # capital released back: committed invested_amount + realized (negative) P&L
    expected_pnl_percent = _pnl_percent("BUY", 1000.0, crash_price)
    expected_pnl_amount = _pnl_amount(position["invested_amount"], expected_pnl_percent)
    expected_cash = round(starting_cash + position["invested_amount"] + expected_pnl_amount, 2)
    assert final_state["capital"]["available_cash"] == expected_cash
    assert expected_pnl_amount < 0  # this scenario is a loss

    log_lines = trade_log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2  # header + one closed trade
    assert "quantity" in log_lines[0]
    assert "pnl_amount" in log_lines[0]


def test_monitor_holds_position_when_neither_stop_nor_target_hit(tmp_path):
    position = _open_position("BUY", entry_price=1000.0)
    midpoint = (position["stop_loss"] + position["target1"]) / 2
    provider = _FakeProvider({"OPEN.NS": _synthetic_ohlcv([midpoint] * 5)})

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    summary = monitor_open_positions(
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    assert summary["target1_shifts"] == 0
    assert summary["stop_losses_hit"] == 0
    assert summary["open_positions"] == 1
    final_state = load_state(state_path)
    assert final_state["open_positions"]["OPEN.NS"]["stop_loss"] == position["stop_loss"]


def test_monitor_sends_holding_status_for_open_position(tmp_path):
    position = _open_position("BUY", entry_price=1000.0)
    provider = _FakeProvider({"OPEN.NS": _synthetic_ohlcv([1010.0] * 5)})

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    messages = []
    monitor_open_positions(
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert len(messages) == 2  # monitor summary + one holding-status message
    assert messages[1].startswith("[TRIAL_HOLDING_STATUS]")
    assert "OPEN.NS (BUY) — HOLD" in messages[1]


def test_monitor_updates_last_known_price_on_checked_position(tmp_path):
    position = _open_position("BUY", entry_price=1000.0)
    provider = _FakeProvider({"OPEN.NS": _synthetic_ohlcv([1010.0] * 5)})

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    monitor_open_positions(
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )

    final_state = load_state(state_path)
    assert final_state["open_positions"]["OPEN.NS"]["last_known_price"] == 1010.0
    assert final_state["open_positions"]["OPEN.NS"]["last_checked_at"]


def test_monitor_leaves_position_untouched_when_price_fetch_fails(tmp_path):
    position = _open_position("BUY", entry_price=1000.0)

    class ExplodingProvider:
        def fetch(self, symbol, interval, period):
            raise RuntimeError("yfinance down")

    state_path = tmp_path / "state.json"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    summary = monitor_open_positions(
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=ExplodingProvider(),
        notify=lambda m: None,
    )

    assert summary["checked"] == 0
    assert summary["open_positions"] == 1
    final_state = load_state(state_path)
    assert final_state["open_positions"]["OPEN.NS"]["stop_loss"] == position["stop_loss"]


# ---------------------------------------------------------------------
# _format_scan_summary
# ---------------------------------------------------------------------


def test_format_scan_summary_basic_counts():
    message = _format_scan_summary(
        scanned=500,
        buy_count=101,
        sell_count=1,
        no_trade_count=398,
        new_buy_count=5,
        new_sell_count=0,
        target1_shift_symbols=[],
        stop_hit_symbols=[],
        skipped_capital_symbols=[],
        open_count=14,
        winning_count=9,
        losing_count=5,
        available_cash=45_000.0,
        net_worth=105_000.0,
        starting_capital=100_000.0,  # literal, decoupled from STARTING_CAPITAL constant
    )
    assert message.startswith("[TRIAL_SCAN_COMPLETED]")
    assert "500 symbol(s) scanned" in message
    assert "BUY: 101 | SELL: 1 | NO_TRADE: 398" in message
    assert "New positions opened: 5 (5 BUY, 0 SELL)" in message
    assert "Open positions now: 14 (9 winning, 5 losing)" in message
    assert "Available Cash: ₹45,000.00" in message
    assert "Net Worth: ₹1,05,000.00" not in message  # no Indian-style grouping
    assert "Net Worth: ₹105,000.00" in message
    assert "Overall P&L: ₹5,000.00 (+5.00%)" in message


def test_format_scan_summary_caps_long_symbol_lists():
    symbols = [f"SYM{i}.NS" for i in range(15)]
    message = _format_scan_summary(
        scanned=15,
        buy_count=0,
        sell_count=0,
        no_trade_count=0,
        new_buy_count=0,
        new_sell_count=0,
        target1_shift_symbols=symbols,
        stop_hit_symbols=[],
        skipped_capital_symbols=[],
        open_count=15,
        winning_count=0,
        losing_count=0,
        available_cash=0.0,
        net_worth=STARTING_CAPITAL,
        starting_capital=STARTING_CAPITAL,
    )
    assert "+5 more" in message
    assert "SYM14.NS" not in message  # beyond the cap of 10


def test_format_scan_summary_negative_pnl():
    message = _format_scan_summary(
        scanned=10,
        buy_count=0,
        sell_count=0,
        no_trade_count=10,
        new_buy_count=0,
        new_sell_count=0,
        target1_shift_symbols=[],
        stop_hit_symbols=[],
        skipped_capital_symbols=[],
        open_count=0,
        winning_count=0,
        losing_count=0,
        available_cash=90_000.0,
        net_worth=90_000.0,
        starting_capital=100_000.0,  # literal, decoupled from STARTING_CAPITAL constant
    )
    assert "Overall P&L: ₹-10,000.00 (-10.00%)" in message


# ---------------------------------------------------------------------
# _format_monitor_summary
# ---------------------------------------------------------------------


def test_format_monitor_summary_basic_counts():
    message = _format_monitor_summary(
        checked_count=87,
        target1_shift_symbols=["A.NS", "B.NS"],
        stop_hit_symbols=["C.NS"],
        open_count=86,
        winning_count=50,
        losing_count=36,
        available_cash=45_000.0,
        net_worth=105_000.0,
        starting_capital=100_000.0,
    )
    assert message.startswith("[TRIAL_POSITION_MONITOR]")
    assert "87 open position(s) checked" in message
    assert "Target1 hit, stop-loss shifted: 2 (A.NS, B.NS)" in message
    assert "Stop-loss hit, closed: 1 (C.NS)" in message
    assert "Open positions now: 86 (50 winning, 36 losing)" in message
    assert "Available Cash: ₹45,000.00" in message
    assert "Net Worth: ₹105,000.00" in message
    assert "Overall P&L: ₹5,000.00 (+5.00%)" in message
    # scan-only fields must never appear in the monitor message
    assert "BUY:" not in message
    assert "New positions opened" not in message


def test_format_monitor_summary_caps_long_symbol_lists():
    symbols = [f"SYM{i}.NS" for i in range(15)]
    message = _format_monitor_summary(
        checked_count=15,
        target1_shift_symbols=symbols,
        stop_hit_symbols=[],
        open_count=15,
        winning_count=0,
        losing_count=0,
        available_cash=0.0,
        net_worth=STARTING_CAPITAL,
        starting_capital=STARTING_CAPITAL,
    )
    assert "+5 more" in message
    assert "SYM14.NS" not in message  # beyond the cap of 10


# ---------------------------------------------------------------------
# _format_holding_entry / _format_holding_status_messages
# ---------------------------------------------------------------------


def test_format_holding_entry_buy_progress_remaining():
    position = _open_position("BUY", entry_price=1000.0, quantity=10)
    entry = _format_holding_entry(1, "TEST.NS", position, 1010.0)
    assert "TEST.NS (BUY) — HOLD" in entry
    assert "Qty: 10" in entry
    assert "Invested: ₹10,000.00" in entry
    assert "Current Value: ₹10,100.00" in entry
    assert "PnL: +1.00% (₹+100.00)" in entry
    assert "Target1 (3%): 2.00% remaining" in entry


def test_format_holding_entry_target1_hit_shows_trailing_stop():
    position = _open_position("BUY", entry_price=1000.0, quantity=10)
    position["target1_hit"] = True
    position["stop_loss"] = position["target1"]
    entry = _format_holding_entry(1, "TEST.NS", position, 1035.0)
    assert "Target1 (3%): HIT" in entry
    assert f"{position['stop_loss']:.2f}" in entry


def test_format_holding_entry_sell_loss_shows_negative_pnl_amount():
    position = _open_position("SELL", entry_price=1000.0, quantity=5)
    entry = _format_holding_entry(1, "TEST.NS", position, 1020.0)  # price rose = SELL loses
    # (1000-1020)/1000*100 = -2.00%; invested=5000 -> pnl_amount=-100.00
    assert "PnL: -2.00% (₹-100.00)" in entry


def test_format_holding_entry_missing_quantity_defaults_to_zero():
    # backward-compat: a position saved before capital tracking existed
    position = _open_position("BUY", entry_price=1000.0)
    del position["quantity"]
    del position["invested_amount"]
    entry = _format_holding_entry(1, "TEST.NS", position, 1010.0)
    assert "Qty: 0" in entry
    assert "Invested: ₹0.00" in entry


def test_format_holding_status_messages_empty_when_no_open_positions():
    assert _format_holding_status_messages({}, {}) == []


def test_format_holding_status_messages_skips_positions_not_scanned_this_run():
    position = _open_position("BUY")
    messages = _format_holding_status_messages(
        {"TEST.NS": position}, latest_close_by_symbol={}
    )
    assert messages == []


def test_format_holding_status_messages_single_chunk():
    position = _open_position("BUY", entry_price=1000.0)
    messages = _format_holding_status_messages(
        {"TEST.NS": position},
        latest_close_by_symbol={"TEST.NS": 1010.0},
    )
    assert len(messages) == 1
    assert messages[0].startswith("[TRIAL_HOLDING_STATUS] Open Positions (1)")
    assert "part" not in messages[0]


def test_format_holding_status_messages_paginates_when_many_positions():
    open_positions = {}
    latest_close_by_symbol = {}
    for i in range(25):
        symbol = f"SYM{i}.NS"
        open_positions[symbol] = _open_position("BUY", entry_price=1000.0)
        latest_close_by_symbol[symbol] = 1010.0

    messages = _format_holding_status_messages(
        open_positions, latest_close_by_symbol, chunk_size=10
    )
    assert len(messages) == 3  # 10 + 10 + 5
    assert "part 1/3" in messages[0]
    assert "part 3/3" in messages[2]
