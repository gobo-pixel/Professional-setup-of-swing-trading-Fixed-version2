"""
Tests for scripts/trial_ema_bb_strategy.py — the TEMPORARY trial
strategy (EMA26/70/240 trend-alignment, fixed-percent risk
management). Covers the pure logic functions directly and the run()
orchestration with a mocked market-data provider / Telegram sender, so
no real network calls happen in tests.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.trial_ema_bb_strategy import (
    EMA_FAST,
    EMA_MID,
    EMA_SLOW,
    STOP_LOSS_PERCENT,
    TARGET1_PERCENT,
    _load_symbols,
    _pnl_percent,
    append_trade_log,
    compute_emas,
    compute_initial_stop_target,
    evaluate_signal,
    load_state,
    monitor_position,
    run,
    save_state,
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


# ---------------------------------------------------------------------
# compute_emas
# ---------------------------------------------------------------------


def test_compute_emas_adds_expected_columns():
    df = _synthetic_ohlcv([100.0 + i for i in range(30)])
    result = compute_emas(df)

    assert f"ema_{EMA_FAST}" in result.columns
    assert f"ema_{EMA_MID}" in result.columns
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


def test_evaluate_signal_buy_when_all_three_agree():
    latest = pd.Series({"close": 110.0, "ema_26": 100.0, "ema_70": 95.0, "ema_240": 90.0})
    assert evaluate_signal(latest) == "BUY"


def test_evaluate_signal_sell_when_all_three_agree():
    latest = pd.Series({"close": 80.0, "ema_26": 90.0, "ema_70": 95.0, "ema_240": 100.0})
    assert evaluate_signal(latest) == "SELL"


def test_evaluate_signal_no_trade_when_mixed():
    latest = pd.Series({"close": 95.0, "ema_26": 100.0, "ema_70": 90.0, "ema_240": 92.0})
    assert evaluate_signal(latest) == "NO_TRADE"


def test_evaluate_signal_no_trade_when_ema_is_nan():
    latest = pd.Series({"close": 110.0, "ema_26": 100.0, "ema_70": 95.0, "ema_240": float("nan")})
    assert evaluate_signal(latest) == "NO_TRADE"


def test_evaluate_signal_no_trade_at_exact_equality():
    # close exactly equal to an EMA is neither strictly above nor
    # below it — must not count as agreement either way.
    latest = pd.Series({"close": 100.0, "ema_26": 100.0, "ema_70": 90.0, "ema_240": 80.0})
    assert evaluate_signal(latest) == "NO_TRADE"


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
# monitor_position
# ---------------------------------------------------------------------


def _open_position(direction: str, entry_price: float = 1000.0) -> dict:
    stop_loss, target1 = compute_initial_stop_target(direction, entry_price)
    return {
        "trade_id": "trial_TEST_1",
        "symbol": "TEST.NS",
        "direction": direction,
        "entry_price": entry_price,
        "entry_time": "2026-08-19T00:00:00+00:00",
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


def test_load_state_missing_file_returns_empty_open_positions(tmp_path):
    state = load_state(tmp_path / "does_not_exist.json")
    assert state == {"open_positions": {}}


def test_save_and_load_state_roundtrip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state = {"open_positions": {"TEST.NS": _open_position("BUY")}}

    save_state(state, path)
    reloaded = load_state(path)

    assert reloaded == state


def test_load_state_tolerates_missing_open_positions_key(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    state = load_state(path)
    assert state["open_positions"] == {}


# ---------------------------------------------------------------------
# trade log
# ---------------------------------------------------------------------


def _trade_row(symbol: str = "TEST.NS") -> dict:
    return {
        "trade_id": "trial_TEST_1",
        "symbol": symbol,
        "direction": "BUY",
        "entry_price": 1000.0,
        "entry_time": "2026-08-19T00:00:00+00:00",
        "exit_price": 985.0,
        "exit_time": "2026-08-20T00:00:00+00:00",
        "exit_reason": "STOP_LOSS_HIT",
        "target1_hit": False,
        "pnl_percent": -1.5,
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
# run() — full-cycle orchestration with a mocked provider/notifier
# ---------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, frames: dict):
        self._frames = frames

    def fetch(self, symbol, interval, period):
        return self._frames[symbol]


def test_run_opens_new_position_on_buy_signal(tmp_path):
    uptrend = _synthetic_ohlcv([100.0 + i * 2 for i in range(30)])
    provider = _FakeProvider({"UP.NS": uptrend})
    messages = []

    summary = run(
        symbols=["UP.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 1
    assert summary["open_positions"] == 1
    assert any("NEW BUY signal" in m for m in messages)

    state = load_state(tmp_path / "state.json")
    assert "UP.NS" in state["open_positions"]
    assert state["open_positions"]["UP.NS"]["direction"] == "BUY"


def test_run_opens_new_position_on_sell_signal(tmp_path):
    downtrend = _synthetic_ohlcv([200.0 - i * 2 for i in range(30)])
    provider = _FakeProvider({"DOWN.NS": downtrend})
    messages = []

    summary = run(
        symbols=["DOWN.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 1
    state = load_state(tmp_path / "state.json")
    assert state["open_positions"]["DOWN.NS"]["direction"] == "SELL"


def test_run_no_signal_when_flat(tmp_path):
    flat = _synthetic_ohlcv([100.0] * 30)
    provider = _FakeProvider({"FLAT.NS": flat})
    messages = []

    summary = run(
        symbols=["FLAT.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["new_signals"] == 0
    assert messages == []


def test_run_skips_fresh_signal_check_when_position_already_open(tmp_path):
    # price still uptrending (would qualify for a fresh BUY signal) but
    # a position is already open for this symbol — must not open a
    # second position for the same symbol.
    uptrend = _synthetic_ohlcv([100.0 + i * 2 for i in range(30)])
    provider = _FakeProvider({"UP.NS": uptrend})

    state_path = tmp_path / "state.json"
    existing_position = _open_position("BUY", entry_price=50.0)
    save_state({"open_positions": {"UP.NS": existing_position}}, state_path)

    messages = []
    run(
        symbols=["UP.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert not any("NEW BUY signal" in m for m in messages)


def test_run_shifts_stop_loss_on_target1_and_notifies(tmp_path):
    flat = _synthetic_ohlcv([1030.0] * 5)  # close sits at/above target1
    provider = _FakeProvider({"OPEN.NS": flat})

    state_path = tmp_path / "state.json"
    position = _open_position("BUY", entry_price=1000.0)
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    messages = []
    summary = run(
        symbols=["OPEN.NS"],
        state_path=state_path,
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["target1_shifts"] == 1
    assert any("Target1 (3%) hit" in m for m in messages)


def test_run_closes_position_on_stop_loss_and_writes_trade_log(tmp_path):
    position = _open_position("BUY", entry_price=1000.0)
    crash = _synthetic_ohlcv([position["stop_loss"] - 5.0] * 5)
    provider = _FakeProvider({"OPEN.NS": crash})

    state_path = tmp_path / "state.json"
    trade_log_path = tmp_path / "trade_log.csv"
    save_state({"open_positions": {"OPEN.NS": position}}, state_path)

    messages = []
    summary = run(
        symbols=["OPEN.NS"],
        state_path=state_path,
        trade_log_path=trade_log_path,
        market_provider=provider,
        notify=messages.append,
    )

    assert summary["stop_losses_hit"] == 1
    assert summary["open_positions"] == 0
    assert any("Position CLOSED" in m for m in messages)

    final_state = load_state(state_path)
    assert "OPEN.NS" not in final_state["open_positions"]

    log_lines = trade_log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2  # header + one closed trade


def test_run_handles_fetch_failure_gracefully(tmp_path):
    class ExplodingProvider:
        def fetch(self, symbol, interval, period):
            raise RuntimeError("yfinance down")

    summary = run(
        symbols=["BAD.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=ExplodingProvider(),
        notify=lambda m: None,
    )
    assert summary["new_signals"] == 0
    assert summary["open_positions"] == 0


def test_run_handles_empty_dataframe_gracefully(tmp_path):
    provider = _FakeProvider({"EMPTY.NS": pd.DataFrame()})
    summary = run(
        symbols=["EMPTY.NS"],
        state_path=tmp_path / "state.json",
        trade_log_path=tmp_path / "trade_log.csv",
        market_provider=provider,
        notify=lambda m: None,
    )
    assert summary["new_signals"] == 0
