"""
PAPER TRADING ENGINE

Runs the existing production scanner exactly as it does today. Whenever
it produces a valid BUY/SELL signal that passes all production
validations, a VIRTUAL position is opened (no real broker, no real
orders — pure simulation). Every open position is then re-evaluated on
every subsequent cycle using the same scanner intelligence plus a
separate ExitEngine, which decides HOLD or EXIT.

This module does not change, wrap, or reinterpret any BUY/SELL decision
logic — it only reacts to scanner.py's output.

Workflow per cycle (see module docstring in the spec):
    Entry -> Daily Monitoring -> Exit Engine -> Trade Closed -> Trade Diary
"""

from __future__ import annotations

import math
import time
from datetime import date
from typing import Any

from core.logger import get_logger
from core.notifications import notify, severity_from_magnitude
from core.trading_calendar import is_trading_day
from execution.scanner import MarketScanner
from paper_trading.virtual_portfolio import VirtualPortfolio
from risk.exit_engine import ExitEngine
from storage.trades.trade_diary import TradeDiary
from storage.trades.trade_store import TradeStore

logger = get_logger(__name__)


class PaperTradingEngine:

    def __init__(
        self,
        scanner: MarketScanner | None = None,
        portfolio: VirtualPortfolio | None = None,
        diary: TradeDiary | None = None,
        trade_store: TradeStore | None = None,
        exit_engine: ExitEngine | None = None,
    ):
        self.scanner = scanner or MarketScanner()
        self.portfolio = portfolio or VirtualPortfolio()
        self.diary = diary or TradeDiary()
        self.trade_store = trade_store or TradeStore()
        self.exit_engine = exit_engine or ExitEngine()

    # ==========================================================
    # MAIN DAILY CYCLE
    # ==========================================================

    def run_cycle(self, symbols: list[str]) -> dict[str, Any]:
        today_date = date.today()
        if not is_trading_day(today_date):
            logger.info("Not an NSE trading day (%s) — skipping cycle entirely. "
                        "No new entries, no monitoring (no fresh market data exists anyway).",
                        today_date.isoformat())
            return {
                "date": today_date.isoformat(),
                "status": "SKIPPED_NON_TRADING_DAY",
                "opened_today": [], "closed_today": [], "monitored": [],
                "portfolio_snapshot": self.portfolio.snapshot(),
            }

        today = today_date.isoformat()
        broker_status = {
            "status": "ONLINE", "mode": "PAPER",
            "connected": True, "order_allowed": True, "available_margin": 1e12,
        }
        market_state = {
            "max_trade_candidates": 20, "max_watchlist": 50,
            "market_open": True, "holiday": False,
        }

        open_symbols = set(self.portfolio.engine.state.open_positions.keys())
        opened_today: list[dict[str, Any]] = []
        closed_today: list[dict[str, Any]] = []
        monitored: list[dict[str, Any]] = []

        # --------------------------------------------------
        # 1. MONITOR EXISTING OPEN POSITIONS FIRST
        #    (uses the SAME production scanner intelligence via
        #    evaluate_position() — a MONITORING-ONLY method that never
        #    runs entry-only checks like duplicate_position/max_positions,
        #    since this position already legitimately exists.)
        # --------------------------------------------------
        for symbol in list(open_symbols):
            portfolio_dict = self.portfolio.engine.snapshot()
            pos = self.portfolio.engine.state.open_positions[symbol]
            result = self.scanner.evaluate_position(
                symbol=symbol,
                position={
                    "symbol": symbol,
                    "direction": pos.direction,
                    "current_price": pos.current_price,
                    "max_drawdown_percent": pos.max_drawdown_percent,
                },
                portfolio=portfolio_dict,
                broker_status=broker_status, market_state=market_state,
            )
            if result.action == "ERROR":
                logger.warning("Monitoring scan failed for %s: %s", symbol, result.diagnostics.get("error"))
                continue

            self.portfolio.register_sector(symbol, result.diagnostics.get("sector"))

            current_price = result.diagnostics.get("latest_close", pos.current_price)

            # ROOT-CAUSE GUARD (see CHANGELOG.md): an occasional bad/
            # incomplete market-data fetch can produce a NaN close price
            # even when the scan otherwise "succeeds" (action != ERROR).
            # Using a NaN price here would silently corrupt this
            # position's P&L today AND, if it reaches close_position(),
            # PERMANENTLY corrupt the whole portfolio's cumulative
            # total_pnl (NaN is contagious through +=) for every future
            # day. Skip this symbol for this cycle instead — same
            # fail-safe pattern as the existing action=="ERROR" skip
            # above — and retry next cycle when fresh data is available.
            if current_price is None or (
                isinstance(current_price, float) and math.isnan(current_price)
            ):
                logger.warning(
                    "Latest close price is NaN/invalid for %s; skipping this "
                    "monitoring cycle (will retry next run).", symbol,
                )
                continue

            self.portfolio.engine.update_position(symbol=symbol, current_price=current_price)
            pos = self.portfolio.engine.state.open_positions[symbol]  # refreshed

            trade_id = self._find_open_trade_id(symbol)
            diary_record = self.diary.get_diary(trade_id) if trade_id else None
            holding_days = len(diary_record["daily_log"]) if diary_record else 0

            dataframe = result.diagnostics.get("_dataframe")
            fundamentals = result.diagnostics.get("_fundamentals") or {}
            news_score = result.diagnostics.get("_news_score")

            if dataframe is None:
                logger.warning("No dataframe available to evaluate exit for %s; holding by default.", symbol)
                continue

            position_input = {
                "symbol": symbol,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "current_price": current_price,
                "stop_loss": result.diagnostics.get("stop_loss"),
                "max_drawdown_percent": pos.max_drawdown_percent,
            }
            exit_eval = self.exit_engine.evaluate(
                dataframe=dataframe, fundamentals=fundamentals, news_score=news_score,
                position=position_input, risk_safe=result.diagnostics.get("risk_safe", True),
                holding_days=holding_days,
            )

            if trade_id is None:
                logger.warning("No open diary entry found for %s; skipping diary update.", symbol)
                continue
            self.diary.add_daily_log(
                trade_id=trade_id, date=today, current_price=current_price,
                current_pnl=pos.unrealized_pnl,
                current_buy_confidence=result.diagnostics.get("buy_decision_confidence", 0.0),
                current_sell_confidence=result.diagnostics.get("sell_decision_confidence", 0.0),
                exit_score=exit_eval.exit_score, recommendation=exit_eval.action,
                notes=exit_eval.reasons,
            )
            monitored.append({"symbol": symbol, "action": exit_eval.action, "exit_score": exit_eval.exit_score})

            # "Existing Position Updated" — only notify on a MEANINGFUL
            # change vs the last logged values (prevents spamming every
            # trivial fluctuation), and dedup by (symbol, today's date)
            # so this fires at most once per position per day.
            prev_log = diary_record["daily_log"][-1] if diary_record and diary_record["daily_log"] else None
            new_buy_conf = result.diagnostics.get("buy_decision_confidence", 0.0)
            new_sell_conf = result.diagnostics.get("sell_decision_confidence", 0.0)
            CHANGE_THRESHOLD = 10.0
            meaningfully_changed = prev_log is None or (
                abs(new_buy_conf - prev_log.get("current_buy_confidence", 0.0)) >= CHANGE_THRESHOLD
                or abs(new_sell_conf - prev_log.get("current_sell_confidence", 0.0)) >= CHANGE_THRESHOLD
                or abs(exit_eval.exit_score - prev_log.get("current_exit_score", 0.0)) >= CHANGE_THRESHOLD
                or exit_eval.action != prev_log.get("recommendation")
            )
            if meaningfully_changed:
                position_status = "EXIT" if exit_eval.action == "EXIT" else (
                    "REVIEW" if exit_eval.exit_score >= exit_eval.threshold * 0.7 else "HOLD"
                )
                notify(
                    event_type="position_updated",
                    message=self._format_position_update(
                        symbol, pos, holding_days, new_buy_conf, new_sell_conf,
                        exit_eval, position_status,
                    ),
                    severity=severity_from_magnitude(exit_eval.exit_score / 100.0),
                    dedup_key=f"position_updated::{symbol}::{today}",
                )

            if exit_eval.action == "EXIT":
                closed = self.portfolio.engine.close_position(symbol=symbol, exit_price=current_price)
                if closed is not None:
                    self.trade_store.save_trade({
                        "symbol": closed.symbol, "direction": closed.direction, "action": "CLOSE",
                        "quantity": closed.quantity, "entry_price": closed.entry_price,
                        "exit_price": current_price, "status": "CLOSED",
                        "realized_pnl": closed.realized_pnl,
                        "realized_pnl_percent": (
                            (current_price - closed.entry_price) / max(closed.entry_price, 1e-9) * 100
                        ),
                        "max_profit_percent": closed.max_profit_percent,
                        "max_drawdown_percent": closed.max_drawdown_percent,
                        "regime": result.diagnostics.get("market_regime", ""),
                        "confidence": result.confidence,
                        "reasons": "; ".join(exit_eval.reasons),
                    })
                    self.diary.close_trade(
                        trade_id=trade_id, exit_date=today, exit_price=current_price,
                        exit_reason=exit_eval.hard_risk_reason or "; ".join(exit_eval.reasons[-1:]),
                        final_pnl=closed.realized_pnl,
                        max_profit_percent=closed.max_profit_percent,
                        max_drawdown_percent=closed.max_drawdown_percent,
                    )
                    closed_today.append({"symbol": symbol, "pnl": closed.realized_pnl})
                    open_symbols.discard(symbol)

                    pnl_pct = (current_price - closed.entry_price) / max(closed.entry_price, 1e-9) * 100
                    notify(
                        event_type="trade_closed",
                        message=self._format_trade_closed(
                            symbol, closed, current_price, pnl_pct, holding_days, exit_eval,
                        ),
                        severity=severity_from_magnitude(min(abs(pnl_pct) / 10.0, 1.0)),
                        dedup_key=f"trade_closed::{symbol}::{today}",
                    )

        self.portfolio.engine.mark_to_market()

        # --------------------------------------------------
        # 2. SCAN FOR NEW ENTRIES (skip symbols already open)
        # --------------------------------------------------
        candidate_symbols = [s for s in symbols if s not in open_symbols]
        if candidate_symbols:
            portfolio_dict = self.portfolio.engine.snapshot()
            candidates = self.scanner.scan_symbols(
                symbols=candidate_symbols, portfolio=portfolio_dict,
                broker_status=broker_status, market_state=market_state,
            )
            for candidate in candidates:
                if not candidate.portfolio_allowed or candidate.position_size <= 0:
                    continue

                price = candidate.diagnostics.get("latest_close")
                # NOTE: "if not price" alone would NOT catch NaN — NaN is
                # truthy in Python (bool(float('nan')) is True) — so this
                # explicit isnan check is required to actually guard
                # against a bad/incomplete data fetch (see the matching
                # guard + explanation in the monitoring loop above).
                if not price or (isinstance(price, float) and math.isnan(price)):
                    continue

                self.portfolio.engine.add_position(
                    symbol=candidate.symbol, quantity=candidate.position_size,
                    entry_price=price, direction=candidate.action,
                )
                self.portfolio.register_sector(candidate.symbol, candidate.diagnostics.get("sector"))

                trade_id = self._new_trade_id(candidate.symbol)
                reasons_list = [
                    r for r in candidate.diagnostics.get("decision_reasons", "").split(" | ") if r
                ]

                self.diary.open_trade(
                    trade_id=trade_id, symbol=candidate.symbol, direction=candidate.action,
                    entry_price=price, entry_date=today,
                    buy_probability=candidate.probability, buy_confidence=candidate.confidence,
                    entry_reasons=reasons_list,
                )
                self.trade_store.save_trade({
                    "symbol": candidate.symbol, "direction": candidate.action, "action": "OPEN",
                    "quantity": candidate.position_size, "entry_price": price, "exit_price": "",
                    "status": "OPEN", "realized_pnl": "", "realized_pnl_percent": "",
                    "regime": candidate.diagnostics.get("market_regime", ""),
                    "confidence": candidate.confidence, "reasons": "",
                })
                opened_today.append({"symbol": candidate.symbol, "action": candidate.action, "price": price})

                notify(
                    event_type="trade_opened",
                    message=self._format_buy_report(candidate, price, reasons_list),
                    severity=severity_from_magnitude(candidate.confidence / 100.0),
                    dedup_key=f"trade_opened::{candidate.symbol}::{today}",
                )

        self.portfolio.save()

        summary = {
            "date": today,
            "opened_today": opened_today,
            "closed_today": closed_today,
            "monitored": monitored,
            "portfolio_snapshot": self.portfolio.snapshot(),
        }
        logger.info(
            "Paper trading cycle complete: %d opened, %d closed, %d monitored.",
            len(opened_today), len(closed_today), len(monitored),
        )
        return summary

    def _find_open_trade_id(self, symbol: str) -> str | None:
        prefix = f"paper_{symbol.replace('.', '_')}_"
        for tid in self.diary.list_open_trade_ids():
            if tid.startswith(prefix):
                return tid
        return None

    @staticmethod
    def _new_trade_id(symbol: str) -> str:
        # Unique per position lifetime (symbol + open timestamp) — if the
        # same symbol trades again later after a prior position closed,
        # this avoids overwriting the earlier CLOSED diary record.
        return f"paper_{symbol.replace('.', '_')}_{int(time.time() * 1000)}"

    # ==========================================================
    # TELEGRAM REPORT FORMATTING (presentation only — every value
    # used below was already computed elsewhere; nothing new here.
    # Market Intelligence stays fully decoupled — see
    # market_intelligence/market_intelligence_engine.py, which runs on
    # its own separate schedule and sends its own summary.)
    # ==========================================================

    @staticmethod
    def _format_buy_report(candidate: Any, price: float, reasons_list: list[str]) -> str:
        top_reasons = "\n".join(f"• {r}" for r in reasons_list[:5]) or "• N/A"
        return (
            f"🟢 New Virtual Trade Opened\n"
            f"Symbol: {candidate.symbol}\n"
            f"Signal: {candidate.action}\n"
            f"Entry Price: {price}\n"
            f"Quantity: {candidate.position_size}\n"
            f"Probability: {candidate.probability:.1f}%\n"
            f"Confidence: {candidate.confidence:.1f}%\n\n"
            f"Top Reasons\n{top_reasons}"
        )

    @staticmethod
    def _format_position_update(
        symbol: str, pos: Any, holding_days: int, buy_conf: float, sell_conf: float,
        exit_eval: Any, position_status: str,
    ) -> str:
        return (
            f"🔄 Position Update: {symbol} ({pos.direction})\n"
            f"Holding Days: {holding_days}\n"
            f"Current Return: {pos.unrealized_pnl_percent:.2f}%\n"
            f"BUY Confidence: {buy_conf:.1f}%\n"
            f"SELL Confidence: {sell_conf:.1f}%\n"
            f"Exit Score: {exit_eval.exit_score:.1f}/100\n"
            f"Recommendation: {position_status}"
        )

    @staticmethod
    def _format_trade_closed(
        symbol: str, closed: Any, exit_price: float, pnl_pct: float,
        holding_days: int, exit_eval: Any,
    ) -> str:
        reason = exit_eval.hard_risk_reason or (exit_eval.reasons[-1] if exit_eval.reasons else "N/A")
        top_reasons = "\n".join(f"• {r}" for r in exit_eval.reasons[:5]) or "• N/A"
        return (
            f"🔴 Virtual Trade Closed: {symbol} ({closed.direction})\n"
            f"Entry: {closed.entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Return: {pnl_pct:.2f}%\n"
            f"Holding Days: {holding_days}\n"
            f"Exit Reason: {reason}\n\n"
            f"Top Reasons\n{top_reasons}"
        )
