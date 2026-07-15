"""
Analytics Engine

Post-backtest intelligence layer:
• Converts raw backtest output into structured insights
• Computes comparative metrics
• Identifies behavioral patterns
• Prepares optimizer-ready signals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# ANALYTICS STATE
# ==========================================================


@dataclass(slots=True)
class AnalyticsState:

    strategy_name: str

    metrics: dict[str, Any] = field(default_factory=dict)

    risk_metrics: dict[str, Any] = field(default_factory=dict)

    trade_insights: dict[str, Any] = field(default_factory=dict)

    equity_analysis: dict[str, Any] = field(default_factory=dict)

    diagnostics: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# ANALYTICS ENGINE
# ==========================================================


class AnalyticsEngine:

    def __init__(self):

        self.state: AnalyticsState | None = None

        logger.info("Analytics Engine initialized.")

    # ==========================================================
    # LOAD BACKTEST DATA
    # ==========================================================

    def load_backtest(
        self,
        backtest_state: Any,
        strategy_name: str,
    ) -> AnalyticsState:

        self.state = AnalyticsState(
            strategy_name=strategy_name,
        )

        diagnostics = backtest_state.diagnostics

        # ==========================================================
        # EXTRACT CORE METRICS
        # ==========================================================

        self.state.metrics = {
            "cagr": diagnostics.get("cagr", 0.0),
            "sharpe_ratio": diagnostics.get("sharpe_ratio", 0.0),
            "sortino_ratio": diagnostics.get("sortino_ratio", 0.0),
            "max_drawdown": diagnostics.get("max_drawdown", 0.0),
            "win_rate": diagnostics.get("win_rate", 0.0),
            "profit_factor": diagnostics.get("profit_factor", 0.0),
            "cumulative_return": diagnostics.get("cumulative_return", 0.0),
            "risk_adjusted_score": diagnostics.get("risk_adjusted_score", 0.0),
        }

        # ==========================================================
        # EQUITY CURVE EXTRACTION
        # ==========================================================

        self.state.equity_analysis = {
            "equity_curve": diagnostics.get("normalized_equity_curve", []),
            "returns": diagnostics.get("returns", []),
            "volatility": diagnostics.get("volatility", 0.0),
        }

        # ==========================================================
        # TRADE INSIGHTS RAW
        # ==========================================================

        self.state.trade_insights = {
            "trade_breakdown": diagnostics.get("trade_breakdown", {}),
            "performance": diagnostics.get("performance", {}),
            "symbol_stats": diagnostics.get("symbol_stats", {}),
        }

        return self.state

    # ==========================================================
    # METRIC NORMALIZATION
    # ==========================================================

    def normalize_metrics(self) -> None:

        m = self.state.metrics

        normalized = {}

        normalized["cagr"] = m.get("cagr", 0.0)

        normalized["sharpe"] = m.get("sharpe_ratio", 0.0)

        normalized["sortino"] = m.get("sortino_ratio", 0.0)

        normalized["drawdown_score"] = 1 - min(m.get("max_drawdown", 0.0), 1.0)

        normalized["win_rate"] = m.get("win_rate", 0.0)

        normalized["profit_factor"] = (
            min(
                m.get("profit_factor", 0.0),
                10.0,
            )
            / 10.0
        )

        self.state.diagnostics["normalized_metrics"] = normalized

    # ==========================================================
    # PERFORMANCE VECTOR BUILD
    # ==========================================================

    def build_performance_vector(self) -> list[float]:

        m = self.state.metrics

        vector = [
            m.get("cagr", 0.0),
            m.get("sharpe_ratio", 0.0),
            m.get("sortino_ratio", 0.0),
            m.get("win_rate", 0.0),
            1 - min(m.get("max_drawdown", 0.0), 1.0),
            min(m.get("profit_factor", 0.0), 10.0) / 10.0,
        ]

        self.state.diagnostics["performance_vector"] = vector

        return vector

    # ==========================================================
    # STABILITY SCORE
    # ==========================================================

    def compute_stability_score(self) -> float:

        returns = self.state.equity_analysis.get("returns", [])

        if not returns:

            self.state.diagnostics["stability_score"] = 0.0

            return 0.0

        mean = np.mean(returns)

        std = np.std(returns)

        stability = mean / max(std, 1e-9)

        stability = max(-10.0, min(10.0, stability))

        self.state.diagnostics["stability_score"] = stability

        return stability

    # ==========================================================
    # TRADE BEHAVIOR ANALYSIS
    # ==========================================================

    def analyze_trade_behavior(self) -> None:

        trade_breakdown = self.state.trade_insights.get(
            "trade_breakdown",
            {},
        )

        performance = self.state.trade_insights.get(
            "performance",
            {},
        )

        total = trade_breakdown.get("total", 0)

        filled = trade_breakdown.get("filled", 0)

        rejected = trade_breakdown.get("rejected", 0)

        partial = trade_breakdown.get("partial", 0)

        fill_ratio = filled / max(total, 1)

        rejection_ratio = rejected / max(total, 1)

        partial_ratio = partial / max(total, 1)

        self.state.diagnostics["trade_behavior"] = {
            "fill_ratio": fill_ratio,
            "rejection_ratio": rejection_ratio,
            "partial_ratio": partial_ratio,
            "avg_slippage": performance.get(
                "avg_slippage",
                0.0,
            ),
            "avg_brokerage": performance.get(
                "avg_brokerage",
                0.0,
            ),
        }

    # ==========================================================
    # CONSISTENCY SCORE
    # ==========================================================

    def compute_consistency_score(self) -> float:

        metrics = self.state.metrics

        drawdown = metrics.get("max_drawdown", 0.0)

        win_rate = metrics.get("win_rate", 0.0)

        profit_factor = metrics.get("profit_factor", 0.0)

        consistency = (
            (win_rate * 0.4)
            + (min(profit_factor, 5) / 5 * 0.4)
            + ((1 - min(drawdown, 1.0)) * 0.2)
        )

        consistency = max(0.0, min(1.0, consistency))

        self.state.diagnostics["consistency_score"] = consistency

        return consistency

    # ==========================================================
    # SYMBOL DOMINANCE ANALYSIS
    # ==========================================================

    def analyze_symbol_dominance(self) -> None:

        symbol_stats = self.state.trade_insights.get(
            "symbol_stats",
            {},
        )

        dominance = []

        for symbol, stats in symbol_stats.items():

            trades = stats.get("trades", 0)

            slippage = stats.get("slippage", 0.0)

            filled = stats.get("filled", 0)

            score = (filled / max(trades, 1)) * 0.5 - (slippage / max(trades, 1)) * 0.5

            dominance.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "trades": trades,
                    "fill_rate": filled / max(trades, 1),
                }
            )

        dominance.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        self.state.diagnostics["symbol_dominance"] = dominance

    # ==========================================================
    # MARKET REGIME DETECTION
    # ==========================================================

    def detect_market_regime(self) -> str:

        volatility = self.state.equity_analysis.get(
            "volatility",
            0.0,
        )

        returns = self.state.equity_analysis.get(
            "returns",
            [],
        )

        if not returns:

            regime = "UNKNOWN"

        else:

            mean_ret = float(np.mean(returns))
            std_ret = float(np.std(returns))

            if volatility > 0.02 and std_ret > 0.01:

                regime = "HIGH_VOLATILITY"

            elif mean_ret > 0 and std_ret < 0.01:

                regime = "TRENDING"

            elif abs(mean_ret) < 0.001 and std_ret < 0.01:

                regime = "SIDEWAYS"

            else:

                regime = "MIXED"

        self.state.diagnostics["market_regime"] = regime

        return regime

    # ==========================================================
    # VOLATILITY CLUSTERING SIGNAL
    # ==========================================================

    def volatility_clustering(self) -> float:

        returns = self.state.equity_analysis.get(
            "returns",
            [],
        )

        if len(returns) < 5:

            self.state.diagnostics["vol_clustering"] = 0.0

            return 0.0

        squared_returns = [r**2 for r in returns]

        clustering = float(
            np.corrcoef(
                squared_returns[:-1],
                squared_returns[1:],
            )[0, 1]
        )

        clustering = max(-1.0, min(1.0, clustering))

        self.state.diagnostics["vol_clustering"] = clustering

        return clustering

    # ==========================================================
    # MARKET EFFICIENCY SCORE
    # ==========================================================

    def compute_market_efficiency(self) -> float:

        returns = self.state.equity_analysis.get(
            "returns",
            [],
        )

        if not returns:

            self.state.diagnostics["market_efficiency"] = 0.0

            return 0.0

        abs_returns = np.abs(returns)

        inefficiency = float(np.mean(abs_returns) / max(np.std(returns), 1e-9))

        efficiency = 1 / (1 + inefficiency)

        self.state.diagnostics["market_efficiency"] = efficiency

        return efficiency

    # ==========================================================
    # STRATEGY SCORE COMPUTATION
    # ==========================================================

    def compute_strategy_score(self) -> float:

        m = self.state.metrics

        stability = self.state.diagnostics.get(
            "stability_score",
            0.0,
        )

        consistency = self.state.diagnostics.get(
            "consistency_score",
            0.0,
        )

        regime = self.state.diagnostics.get(
            "market_regime",
            "UNKNOWN",
        )

        regime_factor = {
            "TRENDING": 1.2,
            "SIDEWAYS": 0.9,
            "HIGH_VOLATILITY": 0.7,
            "MIXED": 1.0,
            "UNKNOWN": 0.8,
        }.get(regime, 1.0)

        score = (
            m.get("sharpe_ratio", 0.0) * 0.35
            + m.get("sortino_ratio", 0.0) * 0.25
            + consistency * 0.2
            + stability * 0.2
        )

        score *= regime_factor

        self.state.diagnostics["strategy_score"] = score

        return score

    # ==========================================================
    # ALPHA SCORE MODEL
    # ==========================================================

    def compute_alpha_score(self) -> float:

        m = self.state.metrics

        trade = self.state.trade_insights.get(
            "trade_behavior",
            {},
        )

        fill = trade.get("fill_ratio", 0.0)

        reject = trade.get("rejection_ratio", 0.0)

        slip = trade.get("avg_slippage", 0.0)

        alpha = (
            (m.get("cagr", 0.0) * 0.4)
            + (m.get("win_rate", 0.0) * 0.2)
            + (fill * 0.2)
            - (reject * 0.1)
            - (slip * 0.1)
        )

        self.state.diagnostics["alpha_score"] = alpha

        return alpha

    # ==========================================================
    # RISK-ADJUSTED RANKING
    # ==========================================================

    def compute_risk_adjusted_rank(self) -> float:

        m = self.state.metrics

        max_dd = m.get("max_drawdown", 0.0)

        sharpe = m.get("sharpe_ratio", 0.0)

        profit_factor = m.get("profit_factor", 0.0)

        rank = (
            sharpe * 0.4
            + (min(profit_factor, 5) / 5) * 0.3
            + (1 - min(max_dd, 1.0)) * 0.3
        )

        self.state.diagnostics["risk_adjusted_rank"] = rank

        return rank

    # ==========================================================
    # ANOMALY DETECTION (PERFORMANCE OUTLIERS)
    # ==========================================================

    def detect_anomalies(self) -> None:

        metrics = self.state.metrics

        anomalies = []

        sharpe = metrics.get("sharpe_ratio", 0.0)

        cagr = metrics.get("cagr", 0.0)

        max_dd = metrics.get("max_drawdown", 0.0)

        win_rate = metrics.get("win_rate", 0.0)

        if sharpe > 3.0:

            anomalies.append("EXTREME_SHARPE")

        if cagr > 2.0:

            anomalies.append("UNREALISTIC_CAGR")

        if max_dd > 0.8:

            anomalies.append("EXTREME_DRAWDOWN")

        if win_rate > 0.95:

            anomalies.append("OVERFIT_WINRATE")

        self.state.diagnostics["anomalies"] = anomalies

    # ==========================================================
    # OVERFITTING SCORE
    # ==========================================================

    def compute_overfitting_score(self) -> float:

        m = self.state.metrics

        trade = self.state.trade_insights.get(
            "trade_behavior",
            {},
        )

        win_rate = m.get("win_rate", 0.0)

        profit_factor = m.get("profit_factor", 0.0)

        fill_ratio = trade.get("fill_ratio", 0.0)

        overfit = (
            (win_rate > 0.85) * 0.4
            + (profit_factor > 3.0) * 0.3
            + (fill_ratio > 0.9) * 0.3
        )

        overfit = min(1.0, overfit)

        self.state.diagnostics["overfitting_score"] = overfit

        return overfit

    # ==========================================================
    # ROBUSTNESS SCORE
    # ==========================================================

    def compute_robustness_score(self) -> float:

        m = self.state.metrics

        volatility = self.state.equity_analysis.get(
            "volatility",
            0.0,
        )

        sharpe = m.get("sharpe_ratio", 0.0)

        sortino = m.get("sortino_ratio", 0.0)

        max_dd = m.get("max_drawdown", 0.0)

        robustness = (sharpe * 0.4) + (sortino * 0.3) + ((1 - max_dd) * 0.3)

        robustness *= 1 - min(volatility * 10, 1.0)

        self.state.diagnostics["robustness_score"] = robustness

        return robustness

    # ==========================================================
    # COMPOSITE INTELLIGENCE SCORE
    # ==========================================================

    def compute_intelligence_score(self) -> float:

        m = self.state.metrics

        strategy = self.state.diagnostics.get(
            "strategy_score",
            0.0,
        )

        alpha = self.state.diagnostics.get(
            "alpha_score",
            0.0,
        )

        rank = self.state.diagnostics.get(
            "risk_adjusted_rank",
            0.0,
        )

        robustness = self.state.diagnostics.get(
            "robustness_score",
            0.0,
        )

        intelligence = strategy * 0.3 + alpha * 0.3 + rank * 0.2 + robustness * 0.2

        self.state.diagnostics["intelligence_score"] = intelligence

        return intelligence

    # ==========================================================
    # FINAL STRATEGY VERDICT ENGINE
    # ==========================================================

    def compute_verdict(self) -> str:

        score = self.state.diagnostics.get(
            "intelligence_score",
            0.0,
        )

        overfit = self.state.diagnostics.get(
            "overfitting_score",
            0.0,
        )

        anomalies = self.state.diagnostics.get(
            "anomalies",
            [],
        )

        if overfit > 0.7 or len(anomalies) > 2:

            verdict = "UNSTABLE"

        elif score >= 1.5:

            verdict = "EXCELLENT"

        elif score >= 1.0:

            verdict = "GOOD"

        elif score >= 0.5:

            verdict = "MODERATE"

        else:

            verdict = "POOR"

        self.state.diagnostics["verdict"] = verdict

        return verdict

    # ==========================================================
    # FINAL SCORE NORMALIZATION
    # ==========================================================

    def normalize_final_score(self) -> float:

        score = self.state.diagnostics.get(
            "intelligence_score",
            0.0,
        )

        overfit_penalty = (
            self.state.diagnostics.get(
                "overfitting_score",
                0.0,
            )
            * 0.5
        )

        anomaly_penalty = len(self.state.diagnostics.get("anomalies", [])) * 0.1

        final_score = score - overfit_penalty - anomaly_penalty

        final_score = max(0.0, final_score)

        self.state.diagnostics["final_score"] = final_score

        return final_score

    # ==========================================================
    # FEATURE IMPORTANCE ESTIMATION
    # ==========================================================

    def estimate_feature_importance(self) -> None:

        m = self.state.metrics

        trade = self.state.trade_insights.get(
            "trade_behavior",
            {},
        )

        features = {
            "cagr": m.get("cagr", 0.0),
            "sharpe": m.get("sharpe_ratio", 0.0),
            "sortino": m.get("sortino_ratio", 0.0),
            "win_rate": m.get("win_rate", 0.0),
            "fill_ratio": trade.get("fill_ratio", 0.0),
            "slippage": trade.get("avg_slippage", 0.0),
            "drawdown": m.get("max_drawdown", 0.0),
        }

        total = sum(abs(v) for v in features.values())

        importance = {k: (abs(v) / max(total, 1e-9)) for k, v in features.items()}

        self.state.diagnostics["feature_importance"] = importance

    # ==========================================================
    # SIGNAL DECOMPOSITION
    # ==========================================================

    def decompose_signal(self) -> dict[str, float]:

        m = self.state.metrics

        trend_component = m.get("cagr", 0.0) * m.get("sharpe_ratio", 0.0)

        risk_component = 1 - min(m.get("max_drawdown", 0.0), 1.0)

        efficiency_component = m.get("win_rate", 0.0) * m.get("profit_factor", 0.0)

        noise_component = self.state.diagnostics.get("vol_clustering", 0.0)

        decomposition = {
            "trend": trend_component,
            "risk": risk_component,
            "efficiency": efficiency_component,
            "noise": noise_component,
        }

        self.state.diagnostics["signal_decomposition"] = decomposition

        return decomposition

    # ==========================================================
    # REGIME WEIGHTED SCORING
    # ==========================================================

    def regime_weighted_score(self) -> float:

        regime = self.state.diagnostics.get(
            "market_regime",
            "UNKNOWN",
        )

        base_score = self.state.diagnostics.get(
            "final_score",
            0.0,
        )

        regime_weights = {
            "TRENDING": 1.25,
            "SIDEWAYS": 0.9,
            "HIGH_VOLATILITY": 0.75,
            "MIXED": 1.0,
            "UNKNOWN": 0.85,
        }

        weighted_score = base_score * regime_weights.get(
            regime,
            1.0,
        )

        self.state.diagnostics["regime_weighted_score"] = weighted_score

        return weighted_score

    # ==========================================================
    # FINAL ANALYTICS REPORT
    # ==========================================================

    def report(self) -> str:

        d = self.state.diagnostics

        m = self.state.metrics

        lines = []

        lines.append("=" * 120)
        lines.append("ANALYTICS REPORT")
        lines.append("=" * 120)
        lines.append("")

        lines.append("CORE PERFORMANCE")
        lines.append("-" * 60)

        lines.append(f"CAGR                    : {m.get('cagr', 0.0):.4f}")
        lines.append(f"Sharpe Ratio            : {m.get('sharpe_ratio', 0.0):.4f}")
        lines.append(f"Sortino Ratio           : {m.get('sortino_ratio', 0.0):.4f}")
        lines.append(f"Max Drawdown            : {m.get('max_drawdown', 0.0):.4f}")
        lines.append(f"Win Rate                : {m.get('win_rate', 0.0):.4f}")
        lines.append(f"Profit Factor           : {m.get('profit_factor', 0.0):.4f}")

        lines.append("")
        lines.append("INTELLIGENCE MODEL")
        lines.append("-" * 60)

        lines.append(f"Strategy Score          : {d.get('strategy_score', 0.0):.4f}")
        lines.append(f"Alpha Score             : {d.get('alpha_score', 0.0):.4f}")
        lines.append(
            f"Risk Adjusted Rank      : {d.get('risk_adjusted_rank', 0.0):.4f}"
        )
        lines.append(f"Robustness Score        : {d.get('robustness_score', 0.0):.4f}")
        lines.append(
            f"Intelligence Score      : {d.get('intelligence_score', 0.0):.4f}"
        )
        lines.append(f"Final Score             : {d.get('final_score', 0.0):.4f}")
        lines.append(f"Verdict                 : {d.get('verdict', 'N/A')}")

        lines.append("")
        lines.append("RISK & STABILITY")
        lines.append("-" * 60)

        lines.append(f"Consistency Score       : {d.get('consistency_score', 0.0):.4f}")
        lines.append(f"Overfitting Score       : {d.get('overfitting_score', 0.0):.4f}")
        lines.append(f"Stability Score         : {d.get('stability_score', 0.0):.4f}")
        lines.append(f"Market Regime           : {d.get('market_regime', 'UNKNOWN')}")
        lines.append(f"Volatility Clustering   : {d.get('vol_clustering', 0.0):.4f}")

        lines.append("")
        lines.append("SIGNAL BREAKDOWN")
        lines.append("-" * 60)

        decomposition = d.get("signal_decomposition", {})

        for k, v in decomposition.items():

            lines.append(f"{k:<25}: {v:.6f}")

        lines.append("")
        lines.append("FEATURE IMPORTANCE")
        lines.append("-" * 60)

        importance = d.get("feature_importance", {})

        for k, v in importance.items():

            lines.append(f"{k:<25}: {v:.4f}")

        lines.append("")
        lines.append("=" * 120)
        lines.append("END ANALYTICS REPORT")
        lines.append("=" * 120)

        return "\n".join(lines)

    # ==========================================================
    # EXPORT SUMMARY
    # ==========================================================

    def summary_dict(self) -> dict[str, Any]:

        return {
            "strategy_name": self.state.strategy_name,
            "final_score": self.state.diagnostics.get("final_score", 0.0),
            "intelligence_score": self.state.diagnostics.get("intelligence_score", 0.0),
            "verdict": self.state.diagnostics.get("verdict", "UNKNOWN"),
            "cagr": self.state.metrics.get("cagr", 0.0),
            "sharpe": self.state.metrics.get("sharpe_ratio", 0.0),
            "max_drawdown": self.state.metrics.get("max_drawdown", 0.0),
        }


# ==========================================================
# END OF FILE
# ==========================================================
