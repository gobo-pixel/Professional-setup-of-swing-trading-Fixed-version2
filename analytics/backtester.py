"""
Backtesting Engine

Institutional Simulation Framework

Responsibilities:
-----------------
• Replay historical market data
• Simulate scanner → broker → portfolio loop
• Validate strategy performance
• Generate equity curve + metrics

This is the "truth validation layer" of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.logger import get_logger

from execution.scanner import MarketScanner
from portfolio.portfolio import PortfolioEngine, PortfolioState
from execution.tracker import PositionTracker, PositionState
from execution.broker import BrokerEngine

logger = get_logger(__name__)


# ==========================================================
# BACKTEST STATE
# ==========================================================


@dataclass(slots=True)
class BacktestState:

    start_date: str

    end_date: str

    current_step: int = 0

    equity_curve: list[float] = field(default_factory=list)

    trades: list[Any] = field(default_factory=list)

    diagnostics: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# BACKTEST ENGINE
# ==========================================================


class Backtester:

    def __init__(self):

        self.scanner = MarketScanner()

        self.tracker = PositionTracker()

        self.broker = BrokerEngine()

        self.state: BacktestState | None = None

        logger.info("Backtester initialized.")

    # ==========================================================
    # RUN BACKTEST
    # ==========================================================

    def run(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float,
        start_date: str,
        end_date: str,
    ) -> BacktestState:

        self.state = BacktestState(
            start_date=start_date,
            end_date=end_date,
        )

        # ==========================================================
        # PORTFOLIO INITIALIZATION
        # ==========================================================

        portfolio = PortfolioState(
            total_capital=initial_capital,
            available_capital=initial_capital,
        )

        portfolio_engine = PortfolioEngine(portfolio)

        # ==========================================================
        # SYMBOL SETUP
        # ==========================================================

        symbols = list(data.keys())

        # ==========================================================
        # MAIN BACKTEST LOOP
        # ==========================================================

        for step in range(len(next(iter(data.values())))):

            self.state.current_step = step

            # ==========================================================
            # BUILD MARKET STATE
            # ==========================================================

            market_state = {
                "market_open": True,
                "volatility_regime": "BACKTEST",
                "risk_on": True,
                "step": step,
            }

            # ==========================================================
            # DATAFRAME SLICE (TIME PROGRESSION)
            # ==========================================================

            dataframe_map = {}

            for symbol in symbols:

                df = data[symbol].iloc[: step + 1]

                dataframe_map[symbol] = df
            # ==========================================================
            # SCANNER EXECUTION (BACKTEST STEP)
            # ==========================================================

            scan_results = self.scanner.scan_symbols(
                symbols=symbols,
                portfolio=portfolio_engine.state.__dict__,
                broker_status={},
                market_state=market_state,
            )

            # ==========================================================
            # FILTER VALID SIGNALS
            # ==========================================================

            candidates = [
                r
                for r in scan_results
                if r.action in ("BUY", "SELL") and r.portfolio_allowed
            ]

            # ==========================================================
            # SORT BY RANKING
            # ==========================================================

            candidates.sort(
                key=lambda x: (
                    x.ranking,
                    x.confidence,
                    x.score,
                ),
                reverse=True,
            )

            # ==========================================================
            # EXECUTE TRADES (SIMULATED BROKER FLOW)
            # ==========================================================

            executed_trades = []

            for candidate in candidates[:10]:

                dataframe = data[candidate.symbol].iloc[: step + 1]

                market_price = float(dataframe.iloc[-1]["close"])

                order = {
                    "symbol": candidate.symbol,
                    "action": candidate.action,
                    "quantity": candidate.position_size,
                }

                result = self.broker.place_order(
                    order=type(
                        "Order",
                        (),
                        order,
                    ),
                    market_price=market_price,
                    market_state=market_state,
                )

                executed_trades.append(result)

                self.state.trades.append(result)
            # ==========================================================
            # TRACKER INITIALIZATION (BACKTEST MODE)
            # ==========================================================

            tracker_results = []

            for trade in executed_trades:

                if trade.status == "REJECTED":

                    continue

                if trade.filled_quantity <= 0:

                    continue

                position = PositionState(
                    symbol=trade.symbol,
                    entry_price=trade.avg_price,
                    quantity=trade.filled_quantity,
                    direction=trade.diagnostics.get(
                        "action",
                        "BUY",
                    ),
                    entry_time=str(step),
                )

                tracker_result = self.tracker.update_position(
                    position=position,
                    dataframe=data[trade.symbol].iloc[: step + 1],
                    portfolio=portfolio_engine.state.__dict__,
                    market_state=market_state,
                )

                tracker_results.append(tracker_result)

            # ==========================================================
            # PORTFOLIO SYNC (BACKTEST)
            # ==========================================================

            for tr in tracker_results:

                symbol = tr.symbol

                if symbol not in portfolio_engine.state.open_positions:

                    portfolio_engine.add_position(
                        symbol=symbol,
                        quantity=tr.diagnostics.get(
                            "quantity",
                            1,
                        ),
                        entry_price=tr.pnl_absolute / max(tr.pnl_percent, 1e-9),
                        direction="BUY",
                    )

                portfolio_engine.update_position(
                    symbol=symbol,
                    current_price=data[symbol].iloc[step]["close"],
                )

            # ==========================================================
            # EQUITY CURVE UPDATE
            # ==========================================================

            portfolio_engine.mark_to_market()

            portfolio_engine.update_risk_score()

            equity = (
                portfolio_engine.state.total_capital + portfolio_engine.state.total_pnl
            )

            self.state.equity_curve.append(equity)

            # ==========================================================
            # STEP ADVANCE
            # ==========================================================

            self.state.diagnostics["step"] = step

            self.state.diagnostics["equity"] = equity

            self.state.diagnostics["open_positions"] = len(
                portfolio_engine.state.open_positions
            )
            # ==========================================================
            # TRADE LOGGING (DETAILED)
            # ==========================================================

            for trade in executed_trades:

                self.state.trades.append(
                    {
                        "symbol": trade.symbol,
                        "status": trade.status,
                        "filled_qty": trade.filled_quantity,
                        "avg_price": trade.avg_price,
                        "slippage": trade.slippage,
                        "brokerage": trade.brokerage,
                        "step": step,
                    }
                )

            # ==========================================================
            # CLOSED POSITION TRACKING
            # ==========================================================

            closed_positions = portfolio_engine.export_closed_positions()

            # ==========================================================
            # DRAWDOWN TRACKING
            # ==========================================================

            equity_curve = self.state.equity_curve

            peak = max(equity_curve) if equity_curve else 0.0

            current = equity_curve[-1] if equity_curve else 0.0

            drawdown = 0.0

            if peak > 0:

                drawdown = (peak - current) / peak

            self.state.diagnostics["drawdown"] = drawdown

            self.state.diagnostics["peak_equity"] = peak

            self.state.diagnostics["current_equity"] = current

        # ==========================================================
        # PERFORMANCE AGGREGATION
        # ==========================================================

        total_trades = len(self.state.trades)

        filled_trades = sum(1 for t in self.state.trades if t["status"] == "FILLED")

        rejected_trades = sum(1 for t in self.state.trades if t["status"] == "REJECTED")

        avg_slippage = sum(t["slippage"] for t in self.state.trades) / max(
            total_trades, 1
        )

        avg_brokerage = sum(t["brokerage"] for t in self.state.trades) / max(
            total_trades, 1
        )

        # ==========================================================
        # STORE METRICS
        # ==========================================================

        self.state.diagnostics["performance"] = {
            "total_trades": total_trades,
            "filled_trades": filled_trades,
            "rejected_trades": rejected_trades,
            "fill_rate": filled_trades / max(total_trades, 1),
            "avg_slippage": avg_slippage,
            "avg_brokerage": avg_brokerage,
        }
        # ==========================================================
        # RETURNS CALCULATION
        # ==========================================================

        equity_curve = self.state.equity_curve

        returns = []

        for i in range(1, len(equity_curve)):

            prev_value = equity_curve[i - 1]

            curr_value = equity_curve[i]

            if prev_value == 0:

                returns.append(0.0)

                continue

            returns.append((curr_value - prev_value) / prev_value)

        self.state.diagnostics["returns"] = returns

        # ==========================================================
        # CUMULATIVE RETURN
        # ==========================================================

        if equity_curve:

            cumulative_return = (equity_curve[-1] - equity_curve[0]) / max(
                equity_curve[0], 1e-9
            )

        else:

            cumulative_return = 0.0

        self.state.diagnostics["cumulative_return"] = cumulative_return

        # ==========================================================
        # CAGR ESTIMATION
        # ==========================================================

        steps = max(self.state.current_step, 1)

        years = steps / (252 * 6.5)  # intraday approximation

        if years > 0:

            cagr = (1 + cumulative_return) ** (1 / years) - 1

        else:

            cagr = 0.0

        self.state.diagnostics["cagr"] = cagr

        # ==========================================================
        # WIN RATE CALCULATION
        # ==========================================================

        pnl_values = [
            t["avg_price"] * t["filled_qty"]
            for t in self.state.trades
            if t["status"] == "FILLED"
        ]

        wins = sum(1 for v in pnl_values if v > 0)

        losses = sum(1 for v in pnl_values if v <= 0)

        win_rate = wins / max(len(pnl_values), 1)

        self.state.diagnostics["win_rate"] = win_rate

        # ==========================================================
        # PROFIT FACTOR
        # ==========================================================

        gross_profit = sum(v for v in pnl_values if v > 0)

        gross_loss = abs(sum(v for v in pnl_values if v < 0))

        profit_factor = gross_profit / max(gross_loss, 1e-9)

        self.state.diagnostics["profit_factor"] = profit_factor
        # ==========================================================
        # SHARPE RATIO
        # ==========================================================

        import math

        mean_return = sum(returns) / max(len(returns), 1)

        variance = sum((r - mean_return) ** 2 for r in returns) / max(len(returns), 1)

        std_dev = math.sqrt(variance)

        sharpe_ratio = (mean_return / max(std_dev, 1e-9)) * math.sqrt(252)

        self.state.diagnostics["sharpe_ratio"] = sharpe_ratio

        # ==========================================================
        # SORTINO RATIO
        # ==========================================================

        downside_returns = [r for r in returns if r < 0]

        downside_variance = sum(r**2 for r in downside_returns) / max(
            len(downside_returns), 1
        )

        downside_std = math.sqrt(downside_variance)

        sortino_ratio = (mean_return / max(downside_std, 1e-9)) * math.sqrt(252)

        self.state.diagnostics["sortino_ratio"] = sortino_ratio

        # ==========================================================
        # MAX DRAWDOWN
        # ==========================================================

        peak = float("-inf")

        max_dd = 0.0

        for value in equity_curve:

            if value > peak:

                peak = value

            dd = (peak - value) / max(peak, 1e-9)

            max_dd = max(max_dd, dd)

        self.state.diagnostics["max_drawdown"] = max_dd

        # ==========================================================
        # VOLATILITY SCORE
        # ==========================================================

        volatility = std_dev * math.sqrt(252)

        self.state.diagnostics["volatility"] = volatility

        # ==========================================================
        # RISK-ADJUSTED SCORE
        # ==========================================================

        risk_adjusted_score = (
            (sharpe_ratio * 0.4) + (sortino_ratio * 0.3) + ((1 - max_dd) * 0.3)
        )

        self.state.diagnostics["risk_adjusted_score"] = risk_adjusted_score
        # ==========================================================
        # STRATEGY PERFORMANCE SUMMARY
        # ==========================================================

        performance = self.state.diagnostics.get("performance", {})

        summary = {
            "cumulative_return": self.state.diagnostics.get("cumulative_return", 0.0),
            "cagr": self.state.diagnostics.get("cagr", 0.0),
            "win_rate": self.state.diagnostics.get("win_rate", 0.0),
            "profit_factor": self.state.diagnostics.get("profit_factor", 0.0),
            "sharpe_ratio": self.state.diagnostics.get("sharpe_ratio", 0.0),
            "sortino_ratio": self.state.diagnostics.get("sortino_ratio", 0.0),
            "max_drawdown": self.state.diagnostics.get("max_drawdown", 0.0),
            "risk_adjusted_score": self.state.diagnostics.get(
                "risk_adjusted_score", 0.0
            ),
            "total_trades": performance.get("total_trades", 0),
            "fill_rate": performance.get("fill_rate", 0.0),
            "avg_slippage": performance.get("avg_slippage", 0.0),
        }

        self.state.diagnostics["strategy_summary"] = summary

        # ==========================================================
        # STRATEGY VERDICT
        # ==========================================================

        score = summary["risk_adjusted_score"]

        if score >= 1.5:

            verdict = "EXCELLENT"

        elif score >= 1.0:

            verdict = "GOOD"

        elif score >= 0.5:

            verdict = "MODERATE"

        else:

            verdict = "POOR"

        self.state.diagnostics["verdict"] = verdict

        # ==========================================================
        # EQUITY CURVE NORMALIZATION
        # ==========================================================

        if equity_curve:

            base = equity_curve[0]

            normalized_curve = [(v / max(base, 1e-9)) for v in equity_curve]

        else:

            normalized_curve = []

        self.state.diagnostics["normalized_equity_curve"] = normalized_curve

        # ==========================================================
        # FINAL BACKTEST STATUS
        # ==========================================================

        self.state.diagnostics["status"] = "COMPLETED"

        self.state.diagnostics["final_step"] = self.state.current_step
        # ==========================================================
        # TRADE BREAKDOWN ANALYSIS
        # ==========================================================

        trade_breakdown = {
            "total": len(self.state.trades),
            "filled": sum(1 for t in self.state.trades if t["status"] == "FILLED"),
            "rejected": sum(1 for t in self.state.trades if t["status"] == "REJECTED"),
            "partial": sum(
                1 for t in self.state.trades if t["status"] == "PARTIALLY_FILLED"
            ),
        }

        self.state.diagnostics["trade_breakdown"] = trade_breakdown

        # ==========================================================
        # SYMBOL LEVEL PERFORMANCE
        # ==========================================================

        symbol_stats = {}

        for t in self.state.trades:

            symbol = t["symbol"]

            if symbol not in symbol_stats:

                symbol_stats[symbol] = {
                    "trades": 0,
                    "filled": 0,
                    "slippage": 0.0,
                    "brokerage": 0.0,
                }

            symbol_stats[symbol]["trades"] += 1

            symbol_stats[symbol]["slippage"] += t["slippage"]

            symbol_stats[symbol]["brokerage"] += t["brokerage"]

            if t["status"] == "FILLED":

                symbol_stats[symbol]["filled"] += 1

        self.state.diagnostics["symbol_stats"] = symbol_stats

        # ==========================================================
        # BEST / WORST PERFORMERS
        # ==========================================================

        performance_by_symbol = []

        for sym, stats in symbol_stats.items():

            fill_rate = stats["filled"] / max(stats["trades"], 1)

            avg_slip = stats["slippage"] / max(stats["trades"], 1)

            score = fill_rate * 0.5 - avg_slip * 0.5

            performance_by_symbol.append(
                {
                    "symbol": sym,
                    "score": score,
                    "fill_rate": fill_rate,
                    "avg_slippage": avg_slip,
                }
            )

        performance_by_symbol.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        self.state.diagnostics["top_symbols"] = performance_by_symbol[:5]

        self.state.diagnostics["worst_symbols"] = performance_by_symbol[-5:]

        # ==========================================================
        # SYSTEM CONSISTENCY CHECK
        # ==========================================================

        consistency_issues = []

        if trade_breakdown["filled"] + trade_breakdown["rejected"] == 0:

            consistency_issues.append("NO_EXECUTION_DATA")

        if len(equity_curve) != self.state.current_step:

            consistency_issues.append("EQUITY_CURVE_MISMATCH")

        if max_dd > 1.0:

            consistency_issues.append("EXTREME_DRAWDOWN")

        self.state.diagnostics["consistency_issues"] = consistency_issues

    # ==========================================================
    # FORMATTED BACKTEST REPORT
    # ==========================================================

    def report(self) -> str:

        d = self.state.diagnostics

        summary = d.get("strategy_summary", {})

        lines = []

        lines.append("=" * 120)
        lines.append("BACKTEST REPORT")
        lines.append("=" * 120)
        lines.append("")

        lines.append("STRATEGY METRICS")
        lines.append("-" * 60)

        lines.append(f"CAGR                 : {summary.get('cagr', 0.0):.4f}")
        lines.append(
            f"Cumulative Return    : {summary.get('cumulative_return', 0.0):.4f}"
        )
        lines.append(f"Win Rate             : {summary.get('win_rate', 0.0):.4f}")
        lines.append(f"Profit Factor        : {summary.get('profit_factor', 0.0):.4f}")
        lines.append(f"Sharpe Ratio         : {summary.get('sharpe_ratio', 0.0):.4f}")
        lines.append(f"Sortino Ratio        : {summary.get('sortino_ratio', 0.0):.4f}")
        lines.append(f"Max Drawdown         : {summary.get('max_drawdown', 0.0):.4f}")
        lines.append(
            f"Risk Adjusted Score  : {summary.get('risk_adjusted_score', 0.0):.4f}"
        )

        lines.append("")
        lines.append("TRADING ACTIVITY")
        lines.append("-" * 60)

        breakdown = d.get("trade_breakdown", {})

        lines.append(f"Total Trades         : {breakdown.get('total', 0)}")
        lines.append(f"Filled Trades        : {breakdown.get('filled', 0)}")
        lines.append(f"Rejected Trades      : {breakdown.get('rejected', 0)}")
        lines.append(f"Partial Trades       : {breakdown.get('partial', 0)}")

        perf = d.get("performance", {})

        lines.append("")
        lines.append("EXECUTION QUALITY")
        lines.append("-" * 60)

        lines.append(f"Fill Rate            : {perf.get('fill_rate', 0.0):.4f}")
        lines.append(f"Avg Slippage         : {perf.get('avg_slippage', 0.0):.6f}")
        lines.append(f"Avg Brokerage        : {perf.get('avg_brokerage', 0.0):.4f}")

        lines.append("")
        lines.append("SYSTEM VERDICT")
        lines.append("-" * 60)

        lines.append(f"Verdict              : {d.get('verdict', 'N/A')}")
        lines.append(f"Status               : {d.get('status', 'UNKNOWN')}")

        if d.get("consistency_issues"):

            lines.append("")
            lines.append("WARNINGS")
            lines.append("-" * 60)

            for issue in d["consistency_issues"]:

                lines.append(f"- {issue}")

        lines.append("")
        lines.append("=" * 120)
        lines.append("END BACKTEST REPORT")
        lines.append("=" * 120)

        return "\n".join(lines)

    # ==========================================================
    # GET STATE
    # ==========================================================

    def get_state(self) -> BacktestState:

        return self.state

    # ==========================================================
    # SINGLE BACKTEST RUNNER (WRAPPER)
    # ==========================================================

    def run_once(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float,
        start_date: str,
        end_date: str,
    ) -> BacktestState:

        return self.run(
            data=data,
            initial_capital=initial_capital,
            start_date=start_date,
            end_date=end_date,
        )

    # ==========================================================
    # PARAMETERIZED BACKTEST RUNNER
    # ==========================================================

    def run_with_params(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float,
        params: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> BacktestState:

        self.scanner.params = params.get("scanner", {})

        self.tracker.params = params.get("tracker", {})

        return self.run(
            data=data,
            initial_capital=initial_capital,
            start_date=start_date,
            end_date=end_date,
        )

    # ==========================================================
    # BATCH BACKTEST RUNNER
    # ==========================================================

    def run_batch(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float,
        param_grid: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:

        results = []

        for i, params in enumerate(param_grid):

            self.state = None

            logger.info(
                "Running backtest %d/%d",
                i + 1,
                len(param_grid),
            )

            state = self.run_with_params(
                data=data,
                initial_capital=initial_capital,
                params=params,
                start_date=start_date,
                end_date=end_date,
            )

            results.append(
                {
                    "params": params,
                    "cagr": state.diagnostics.get("cagr", 0.0),
                    "sharpe": state.diagnostics.get("sharpe_ratio", 0.0),
                    "max_drawdown": state.diagnostics.get("max_drawdown", 0.0),
                    "win_rate": state.diagnostics.get("win_rate", 0.0),
                    "profit_factor": state.diagnostics.get("profit_factor", 0.0),
                }
            )

        return results

    # ==========================================================
    # CLI ENTRYPOINT STYLE RUN
    # ==========================================================

    def run_cli(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float = 100000.0,
        start_date: str = "",
        end_date: str = "",
    ) -> None:

        state = self.run(
            data=data,
            initial_capital=initial_capital,
            start_date=start_date,
            end_date=end_date,
        )

        print(self.report())

    # ==========================================================
    # QUICK SUMMARY ACCESSOR
    # ==========================================================

    def summary_dict(self) -> dict[str, Any]:

        d = self.state.diagnostics

        return {
            "cagr": d.get("cagr", 0.0),
            "sharpe": d.get("sharpe_ratio", 0.0),
            "sortino": d.get("sortino_ratio", 0.0),
            "max_drawdown": d.get("max_drawdown", 0.0),
            "win_rate": d.get("win_rate", 0.0),
            "profit_factor": d.get("profit_factor", 0.0),
            "risk_score": d.get("risk_adjusted_score", 0.0),
            "trades": len(self.state.trades),
        }

    # ==========================================================
    # RESET BACKTEST ENGINE
    # ==========================================================

    def reset(self) -> None:

        self.state = None

        logger.info("Backtester reset completed.")

    # ==========================================================
    # VALIDATION CHECK
    # ==========================================================

    def validate_results(self) -> dict[str, Any]:

        issues = []

        if not self.state:

            return {
                "valid": False,
                "issues": ["NO_STATE_FOUND"],
            }

        if len(self.state.trades) == 0:

            issues.append("NO_TRADES_EXECUTED")

        if len(self.state.equity_curve) == 0:

            issues.append("EMPTY_EQUITY_CURVE")

        if self.state.diagnostics.get("max_drawdown", 0) > 1:

            issues.append("EXTREME_DRAWDOWN")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }


# ==========================================================
# END OF FILE
# ==========================================================
