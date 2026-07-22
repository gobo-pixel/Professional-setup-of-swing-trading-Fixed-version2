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
from core.trading_calendar import is_trading_day, now_ist
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
                        exit_eval, position_status, result.diagnostics,
                        trade_id, diary_record.get("created_at") if diary_record else None,
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

                    closed_at = time.time()
                    pnl_pct = (current_price - closed.entry_price) / max(closed.entry_price, 1e-9) * 100
                    notify(
                        event_type="trade_closed",
                        message=self._format_trade_closed(
                            symbol, closed, current_price, pnl_pct, holding_days, exit_eval,
                            trade_id, diary_record.get("created_at") if diary_record else None, closed_at,
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
                    message=self._format_buy_report(candidate, price, reasons_list, trade_id),
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
    def _fmt_ts(epoch: float | None) -> str:
        if not epoch:
            return "N/A"
        from datetime import datetime, timezone
        from core.trading_calendar import IST_OFFSET
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc) + IST_OFFSET
        return dt.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _extract_reason_line(reasons_list: list[str], prefix: str) -> str | None:
        """Find an already-existing reason line by its prefix (e.g.
        "BUY Strength", "SELL engine validation") — these are produced
        by decision_engine.py's own reasons list, not recomputed here."""
        for r in reasons_list:
            if r.strip().lower().startswith(prefix.lower()):
                return r.strip()
        return None

    def _format_buy_report(
        self, candidate: Any, price: float, reasons_list: list[str], trade_id: str,
    ) -> str:
        d = candidate.diagnostics
        action = candidate.action
        other_side = "SELL" if action == "BUY" else "BUY"

        strength_prefixes = ("buy strength", "sell strength", "decision quality",
                             "buy engine validation", "sell engine validation")
        filtered_reasons = [
            r for r in reasons_list
            if not r.strip().lower().startswith(strength_prefixes)
        ]
        top_reasons = "\n".join(f"• {r}" for r in filtered_reasons[:5]) or "• N/A"

        buy_strength = self._extract_reason_line(reasons_list, "BUY Strength")
        sell_strength = self._extract_reason_line(reasons_list, "SELL Strength")
        decision_quality = self._extract_reason_line(reasons_list, "Decision Quality")
        other_side_rejection = self._extract_reason_line(
            reasons_list, f"{other_side} engine validation"
        )

        stop_loss = d.get("stop_loss", 0.0) or 0.0
        target1 = d.get("target1", 0.0) or 0.0
        target2 = d.get("target2", 0.0) or 0.0
        expected_hold_days = d.get("expected_hold_days", 0) or 0

        stop_pct = round(abs(price - stop_loss) / price * 100, 2) if stop_loss and price else 0.0
        stop_dist = abs(price - stop_loss)

        def target_block(label: str, target_price: float) -> list[str]:
            if not target_price or not price:
                return [f"{label}: N/A"]
            pct = round((target_price - price) / price * 100, 2)
            rr = round(abs(target_price - price) / stop_dist, 2) if stop_dist else 0.0
            sign = "+" if pct >= 0 else ""
            return [f"{label}: {sign}{pct:.1f}%  (Risk:Reward 1:{rr:.2f})"]

        # Decision Margin — overall score vs the qualifying threshold that
        # actually decided this trade (already computed by the strategy).
        score_key, threshold_key = (
            ("buy_overall_score", "buy_qualify_threshold") if action == "BUY"
            else ("sell_overall_score", "sell_qualify_threshold")
        )
        score = d.get(score_key)
        threshold = d.get(threshold_key)
        margin_lines = []
        if score is not None and threshold is not None:
            margin = round(score - threshold, 2)
            margin_lines = [
                "",
                "Decision Margin",
                f"{action} Score: {score:.1f}",
                f"Threshold: {threshold:.1f}",
                f"Margin: {'+' if margin >= 0 else ''}{margin:.1f}",
            ]

        opened_ts = self._fmt_ts(time.time())

        lines = [
            "🟢 New Virtual Trade Opened",
            f"Trade ID: {trade_id}",
            f"Symbol: {candidate.symbol}",
            f"Signal: {action}",
            f"Entry Price: {price}",
            f"Quantity: {candidate.position_size}",
            f"Probability: {candidate.probability:.1f}%",
            f"Confidence: {candidate.confidence:.1f}%",
            "",
            f"📅 Expected Holding: ~{expected_hold_days} days",
            "🎯 " + target_block("Target 1 (Partial)", target1)[0],
            "🎯 " + target_block("Target 2 (Final)", target2)[0],
            f"🛑 Expected Stop Loss: -{stop_pct:.1f}%",
        ]
        lines += margin_lines
        if buy_strength or sell_strength or decision_quality:
            lines.append("")
            if buy_strength:
                lines.append(buy_strength)
            if sell_strength:
                lines.append(sell_strength)
            if decision_quality:
                lines.append(decision_quality)
        lines.append("")
        lines.append("Top Reasons")
        lines.append(top_reasons)
        if other_side_rejection:
            lines.append("")
            lines.append(f"Why {other_side} was rejected:")
            lines.append(f"• {other_side_rejection}")
        lines += [
            "",
            "Lifecycle",
            f"Opened: {opened_ts}",
            "Holding: 0 Days",
            "Status: ACTIVE",
        ]

        return "\n".join(lines)

    def _format_position_update(
        self, symbol: str, pos: Any, holding_days: int, buy_conf: float, sell_conf: float,
        exit_eval: Any, position_status: str, result_diagnostics: dict,
        trade_id: str, created_at: float | None,
    ) -> str:
        current_price = pos.current_price
        stop_loss = result_diagnostics.get("stop_loss", 0.0) or 0.0
        target1 = result_diagnostics.get("target1", 0.0) or 0.0
        target2 = result_diagnostics.get("target2", 0.0) or 0.0
        dist_to_target1 = (
            round((target1 - current_price) / current_price * 100, 2)
            if target1 and current_price else None
        )
        dist_to_target2 = (
            round((target2 - current_price) / current_price * 100, 2)
            if target2 and current_price else None
        )
        dist_to_stop = (
            round((current_price - stop_loss) / current_price * 100, 2)
            if stop_loss and current_price else None
        )
        current_pnl_rupees = pos.unrealized_pnl

        lines = [
            f"🔄 Position Update: {symbol} ({pos.direction})",
            f"Trade ID: {trade_id}",
            f"Holding Days: {holding_days}",
            f"Current Price: {current_price}",
            f"Entry Price: {pos.entry_price}",
            f"Current PnL: {pos.unrealized_pnl_percent:.2f}% (₹{current_pnl_rupees:.2f})",
            f"Highest PnL achieved: {pos.max_profit_percent:.2f}%",
            f"Lowest PnL achieved: -{pos.max_drawdown_percent:.2f}%",
        ]
        if dist_to_target1 is not None:
            lines.append(f"Remaining Distance to Target 1: {dist_to_target1:.2f}%")
        if dist_to_target2 is not None:
            lines.append(f"Remaining Distance to Target 2: {dist_to_target2:.2f}%")
        if dist_to_stop is not None:
            lines.append(f"Remaining Distance to Stop Loss: {dist_to_stop:.2f}%")
        lines += [
            f"BUY Confidence: {buy_conf:.1f}%",
            f"SELL Confidence: {sell_conf:.1f}%",
            f"Exit Score: {exit_eval.exit_score:.1f}/100",
            f"Recommendation: {position_status}",
            "",
            "Lifecycle",
            f"Opened: {self._fmt_ts(created_at)}",
            f"Holding: {holding_days} Days",
            "Status: ACTIVE",
        ]
        return "\n".join(lines)

    @staticmethod
    def _classify_exit_trigger(exit_eval: Any) -> str:
        """Classifies the ALREADY-COMPUTED exit reason into a short
        label. Purely a text categorization of exit_eval's existing
        output (hard_risk_reason / reasons) — does not change when or
        why ExitEngine decides to exit, only how it's labeled here."""
        reason_text = (exit_eval.hard_risk_reason or "").lower()
        if "stop-loss" in reason_text:
            return "Stop Loss Hit"
        if "risk engine" in reason_text or "unsafe" in reason_text:
            return "Risk Management Exit"
        if "maximum holding" in reason_text:
            return "Time-Based Exit"
        # Weighted-score exit (no hard-risk override) — look at which
        # sub-score(s) were the biggest drivers, from exit_eval's own
        # already-computed breakdown.
        subscores = {
            "Momentum Weakened": exit_eval.technical_exit,
            "Fundamentals Weakened": exit_eval.fundamental_exit,
            "Negative News": exit_eval.news_exit,
            "Risk Management Exit": exit_eval.risk_exit,
        }
        top = max(subscores, key=subscores.get)
        return "Trend Reversal" if top == "Momentum Weakened" and exit_eval.technical_exit >= 80 else top

    def _format_trade_closed(
        self, symbol: str, closed: Any, exit_price: float, pnl_pct: float,
        holding_days: int, exit_eval: Any, trade_id: str,
        created_at: float | None, closed_at: float | None,
    ) -> str:
        trigger = self._classify_exit_trigger(exit_eval)
        explanation = exit_eval.hard_risk_reason or (
            exit_eval.reasons[-1] if exit_eval.reasons else "N/A"
        )
        top_reasons = "\n".join(f"• {r}" for r in exit_eval.reasons[:5]) or "• N/A"
        pnl_rupees = closed.realized_pnl
        return (
            f"🔴 Virtual Trade Closed: {symbol} ({closed.direction})\n"
            f"Trade ID: {trade_id}\n"
            f"Holding Days: {holding_days}\n"
            f"Entry: {closed.entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Total Return: {pnl_pct:.2f}%\n"
            f"Total P&L: ₹{pnl_rupees:.2f}\n"
            f"Exit Reason: {trigger}\n"
            f"Why: {explanation}\n\n"
            f"Top Reasons\n{top_reasons}\n\n"
            f"Lifecycle\n"
            f"Opened: {self._fmt_ts(created_at)}\n"
            f"Closed: {self._fmt_ts(closed_at)}\n"
            f"Holding: {holding_days} Days"
        )
