"""
Optimizer Engine

Purpose:
--------
• Optimize strategy parameters using backtest + analytics feedback
• Prevent overfitting via multi-metric scoring
• Support grid search + random search style optimization

This is the "strategy improvement brain" of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import random

from core.logger import get_logger

from backtester.backtester import Backtester
from analytics.analytics import AnalyticsEngine

logger = get_logger(__name__)


# ==========================================================
# OPTIMIZER STATE
# ==========================================================


@dataclass(slots=True)
class OptimizationResult:

    params: dict[str, Any]

    score: float

    sharpe: float

    cagr: float

    drawdown: float

    win_rate: float


# ==========================================================
# OPTIMIZER ENGINE
# ==========================================================


class OptimizerEngine:

    def __init__(self):

        self.backtester = Backtester()

        self.analytics = AnalyticsEngine()

        self.results: list[OptimizationResult] = []

        logger.info("Optimizer Engine initialized.")

    # ==========================================================
    # OBJECTIVE FUNCTION
    # ==========================================================

    def objective_score(
        self,
        analytics_state: Any,
    ) -> float:

        metrics = analytics_state.metrics

        diagnostics = analytics_state.diagnostics

        sharpe = metrics.get("sharpe_ratio", 0.0)

        cagr = metrics.get("cagr", 0.0)

        drawdown = metrics.get("max_drawdown", 0.0)

        win_rate = metrics.get("win_rate", 0.0)

        profit_factor = metrics.get("profit_factor", 0.0)

        overfit = diagnostics.get("overfitting_score", 0.0)

        anomaly_count = len(diagnostics.get("anomalies", []))

        score = (
            sharpe * 0.35
            + cagr * 0.25
            + win_rate * 0.15
            + min(profit_factor, 5) / 5 * 0.15
            + (1 - min(drawdown, 1.0)) * 0.10
        )

        score -= overfit * 0.5

        score -= anomaly_count * 0.1

        return max(0.0, score)

    # ==========================================================
    # PARAMETER EVALUATION
    # ==========================================================

    def evaluate_params(
        self,
        data: dict[str, Any],
        initial_capital: float,
        params: dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> OptimizationResult:

        backtest_state = self.backtester.run_with_params(
            data=data,
            initial_capital=initial_capital,
            params=params,
            start_date=start_date,
            end_date=end_date,
        )

        self.analytics.load_backtest(
            backtest_state,
            strategy_name=str(params.get("name", "strategy")),
        )

        self.analytics.normalize_metrics()

        self.analytics.analyze_trade_behavior()

        self.analytics.detect_market_regime()

        self.analytics.compute_overfitting_score()

        self.analytics.compute_stability_score()

        self.analytics.compute_strategy_score()

        self.analytics.compute_alpha_score()

        self.analytics.compute_risk_adjusted_rank()

        self.analytics.compute_intelligence_score()

        self.analytics.normalize_final_score()

        self.analytics.compute_verdict()

        score = self.objective_score(self.analytics.state)

        metrics = self.analytics.state.metrics

        result = OptimizationResult(
            params=params,
            score=score,
            sharpe=metrics.get("sharpe_ratio", 0.0),
            cagr=metrics.get("cagr", 0.0),
            drawdown=metrics.get("max_drawdown", 0.0),
            win_rate=metrics.get("win_rate", 0.0),
        )

        self.results.append(result)

        return result

    # ==========================================================
    # GRID SEARCH OPTIMIZATION
    # ==========================================================

    def grid_search(
        self,
        data: dict[str, Any],
        initial_capital: float,
        param_grid: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> list[OptimizationResult]:

        results: list[OptimizationResult] = []

        for i, params in enumerate(param_grid):

            logger.info(
                "Grid search %d/%d",
                i + 1,
                len(param_grid),
            )

            result = self.evaluate_params(
                data=data,
                initial_capital=initial_capital,
                params=params,
                start_date=start_date,
                end_date=end_date,
            )

            results.append(result)

        return results

    # ==========================================================
    # RANDOM SEARCH OPTIMIZATION
    # ==========================================================

    def random_search(
        self,
        data: dict[str, Any],
        initial_capital: float,
        param_space: dict[str, Any],
        n_iter: int,
        start_date: str,
        end_date: str,
    ) -> list[OptimizationResult]:

        results: list[OptimizationResult] = []

        for i in range(n_iter):

            sampled_params = {
                k: (random.choice(v) if isinstance(v, list) else v)
                for k, v in param_space.items()
            }

            logger.info(
                "Random search iteration %d/%d",
                i + 1,
                n_iter,
            )

            result = self.evaluate_params(
                data=data,
                initial_capital=initial_capital,
                params=sampled_params,
                start_date=start_date,
                end_date=end_date,
            )

            results.append(result)

        return results

    # ==========================================================
    # PARAMETER MUTATION ENGINE
    # ==========================================================

    def mutate_params(
        self,
        base_params: dict[str, Any],
        mutation_rate: float = 0.1,
    ) -> dict[str, Any]:

        mutated = base_params.copy()

        for k, v in mutated.items():

            if isinstance(v, (int, float)):

                if random.random() < mutation_rate:

                    noise = random.uniform(-0.2, 0.2)

                    mutated[k] = type(v)(v * (1 + noise))

            elif isinstance(v, list) and v:

                if random.random() < mutation_rate:

                    mutated[k] = random.choice(v)

        return mutated

    # ==========================================================
    # EVOLUTIONARY STEP (SINGLE GENERATION)
    # ==========================================================

    def evolutionary_step(
        self,
        data: dict[str, Any],
        initial_capital: float,
        population: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> list[OptimizationResult]:

        evaluated: list[OptimizationResult] = []

        for i, params in enumerate(population):

            logger.info(
                "Evolution step %d/%d",
                i + 1,
                len(population),
            )

            result = self.evaluate_params(
                data=data,
                initial_capital=initial_capital,
                params=params,
                start_date=start_date,
                end_date=end_date,
            )

            evaluated.append(result)

        evaluated.sort(
            key=lambda x: x.score,
            reverse=True,
        )

        return evaluated

    # ==========================================================
    # TOP-K SELECTION
    # ==========================================================

    def select_top_k(
        self,
        results: list[OptimizationResult],
        k: int = 5,
    ) -> list[OptimizationResult]:

        return sorted(
            results,
            key=lambda x: x.score,
            reverse=True,
        )[:k]

    # ==========================================================
    # BREEDING / CROSSOVER
    # ==========================================================

    def crossover(
        self,
        parent_a: dict[str, Any],
        parent_b: dict[str, Any],
    ) -> dict[str, Any]:

        child = {}

        for key in set(parent_a.keys()).union(parent_b.keys()):

            if random.random() < 0.5:

                child[key] = parent_a.get(key)

            else:

                child[key] = parent_b.get(key)

        return child

    # ==========================================================
    # GENERATE NEXT POPULATION
    # ==========================================================

    def generate_next_population(
        self,
        top_results: list[OptimizationResult],
        population_size: int,
        mutation_rate: float = 0.1,
    ) -> list[dict[str, Any]]:

        next_population: list[dict[str, Any]] = []

        elite = [r.params for r in top_results]

        while len(next_population) < population_size:

            parent_a = random.choice(elite)

            parent_b = random.choice(elite)

            child = self.crossover(parent_a, parent_b)

            child = self.mutate_params(child, mutation_rate)

            next_population.append(child)

        return next_population

    # ==========================================================
    # EVOLUTION LOOP (MULTI-GENERATION OPTIMIZER)
    # ==========================================================

    def evolve(
        self,
        data: dict[str, Any],
        initial_capital: float,
        base_population: list[dict[str, Any]],
        generations: int,
        population_size: int,
        start_date: str,
        end_date: str,
    ) -> list[OptimizationResult]:

        population = base_population

        all_results: list[OptimizationResult] = []

        for gen in range(generations):

            logger.info(
                "Generation %d/%d",
                gen + 1,
                generations,
            )

            results = self.evolutionary_step(
                data=data,
                initial_capital=initial_capital,
                population=population,
                start_date=start_date,
                end_date=end_date,
            )

            all_results.extend(results)

            top_k = self.select_top_k(results, k=5)

            population = self.generate_next_population(
                top_k,
                population_size=population_size,
                mutation_rate=0.15,
            )

        return all_results

    # ==========================================================
    # BEST RESULT TRACKING
    # ==========================================================

    def get_best_result(
        self,
        results: list[OptimizationResult],
    ) -> OptimizationResult | None:

        if not results:

            return None

        return max(
            results,
            key=lambda x: x.score,
        )

    # ==========================================================
    # CONVERGENCE DETECTION
    # ==========================================================

    def detect_convergence(
        self,
        recent_results: list[OptimizationResult],
        window: int = 5,
        threshold: float = 0.01,
    ) -> bool:

        if len(recent_results) < window * 2:

            return False

        recent_scores = [r.score for r in recent_results[-window:]]

        previous_scores = [r.score for r in recent_results[-window * 2 : -window]]

        recent_mean = sum(recent_scores) / window

        previous_mean = sum(previous_scores) / window

        improvement = abs(recent_mean - previous_mean)

        return improvement < threshold

    # ==========================================================
    # STABILITY SCORE ACROSS GENERATIONS
    # ==========================================================

    def compute_stability_across_generations(
        self,
        results: list[OptimizationResult],
    ) -> float:

        if not results:

            return 0.0

        scores = [r.score for r in results]

        mean_score = sum(scores) / len(scores)

        variance = sum((x - mean_score) ** 2 for x in scores) / max(len(scores), 1)

        stability = 1 / (1 + variance)

        return stability

    # ==========================================================
    # PARAMETER IMPORTANCE HEURISTIC
    # ==========================================================

    def estimate_param_importance(
        self,
        results: list[OptimizationResult],
    ) -> dict[str, float]:

        importance: dict[str, float] = {}

        if not results:

            return importance

        param_keys = results[0].params.keys()

        base_score = sum(r.score for r in results) / len(results)

        for key in param_keys:

            varied_scores = []

            for r in results:

                if key in r.params:

                    varied_scores.append(r.score)

            if varied_scores:

                importance[key] = abs(
                    sum(varied_scores) / len(varied_scores) - base_score
                )

        return importance

    # ==========================================================
    # OVERFITTING DETECTION
    # ==========================================================

    def detect_overfitting(
        self,
        results: list[OptimizationResult],
        threshold: float = 0.75,
    ) -> dict[str, Any]:

        if not results:

            return {
                "overfitting": False,
                "score": 0.0,
            }

        scores = [r.score for r in results]

        best = max(scores)

        avg = sum(scores) / len(scores)

        overfit_score = (best - avg) / max(best, 1e-9)

        is_overfitting = overfit_score > threshold

        return {
            "overfitting": is_overfitting,
            "score": overfit_score,
            "best_score": best,
            "avg_score": avg,
        }

    # ==========================================================
    # WALK-FORWARD VALIDATION SPLIT
    # ==========================================================

    def walk_forward_split(
        self,
        data: dict[str, Any],
        train_ratio: float = 0.7,
    ) -> tuple[dict[str, Any], dict[str, Any]]:

        train_data = {}

        test_data = {}

        for symbol, df in data.items():

            split_idx = int(len(df) * train_ratio)

            train_data[symbol] = df.iloc[:split_idx]

            test_data[symbol] = df.iloc[split_idx:]

        return train_data, test_data

    # ==========================================================
    # PARAMETER ROBUSTNESS CHECK
    # ==========================================================

    def check_param_robustness(
        self,
        base_params: dict[str, Any],
        data: dict[str, Any],
        initial_capital: float,
        perturbations: int = 5,
        start_date: str = "",
        end_date: str = "",
    ) -> float:

        base_result = self.evaluate_params(
            data=data,
            initial_capital=initial_capital,
            params=base_params,
            start_date=start_date,
            end_date=end_date,
        )

        base_score = base_result.score

        deviations = []

        for _ in range(perturbations):

            mutated = self.mutate_params(base_params)

            result = self.evaluate_params(
                data=data,
                initial_capital=initial_capital,
                params=mutated,
                start_date=start_date,
                end_date=end_date,
            )

            deviations.append(abs(result.score - base_score))

        robustness = 1 / (1 + sum(deviations) / max(len(deviations), 1))

        return robustness

    # ==========================================================
    # FINAL OPTIMIZER SCORE MODEL
    # ==========================================================

    def compute_final_optimizer_score(
        self,
        result: OptimizationResult,
        robustness: float,
        overfitting: dict[str, Any],
    ) -> float:

        base = result.score

        overfit_penalty = overfitting.get("score", 0.0)

        if overfitting.get("overfitting", False):

            overfit_penalty *= 2.0

        final_score = base * 0.6 + robustness * 0.3 - overfit_penalty * 0.4

        return max(0.0, final_score)

    # ==========================================================
    # STRATEGY SELECTION ENGINE
    # ==========================================================

    def select_best_strategy(
        self,
        results: list[OptimizationResult],
        robustness_map: dict[str, float],
        overfit_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:

        best = None

        best_score = -1.0

        for r in results:

            robustness = robustness_map.get(
                str(r.params),
                0.0,
            )

            overfit = overfit_map.get(
                str(r.params),
                {
                    "score": 0.0,
                    "overfitting": False,
                },
            )

            score = self.compute_final_optimizer_score(
                r,
                robustness,
                overfit,
            )

            if score > best_score:

                best_score = score

                best = {
                    "params": r.params,
                    "score": score,
                    "sharpe": r.sharpe,
                    "cagr": r.cagr,
                    "drawdown": r.drawdown,
                    "win_rate": r.win_rate,
                }

        return best or {}

    # ==========================================================
    # TOP STRATEGIES FILTER
    # ==========================================================

    def get_top_strategies(
        self,
        results: list[OptimizationResult],
        top_n: int = 10,
    ) -> list[OptimizationResult]:

        return sorted(
            results,
            key=lambda x: x.score,
            reverse=True,
        )[:top_n]

    # ==========================================================
    # OPTIMIZATION REPORT
    # ==========================================================

    def report(
        self,
        results: list[OptimizationResult],
    ) -> str:

        if not results:

            return "NO OPTIMIZATION RESULTS"

        best = max(results, key=lambda x: x.score)

        worst = min(results, key=lambda x: x.score)

        avg_score = sum(r.score for r in results) / max(len(results), 1)

        lines = []

        lines.append("=" * 120)
        lines.append("OPTIMIZER REPORT")
        lines.append("=" * 120)
        lines.append("")

        lines.append("SUMMARY")
        lines.append("-" * 60)

        lines.append(f"Total Runs        : {len(results)}")
        lines.append(f"Avg Score         : {avg_score:.4f}")
        lines.append(f"Best Score        : {best.score:.4f}")
        lines.append(f"Worst Score       : {worst.score:.4f}")

        lines.append("")
        lines.append("BEST STRATEGY")
        lines.append("-" * 60)

        lines.append(f"Params            : {best.params}")
        lines.append(f"Sharpe            : {best.sharpe:.4f}")
        lines.append(f"CAGR              : {best.cagr:.4f}")
        lines.append(f"Drawdown          : {best.drawdown:.4f}")
        lines.append(f"Win Rate          : {best.win_rate:.4f}")

        lines.append("")
        lines.append("RISK INSIGHT")
        lines.append("-" * 60)

        overfit_map = self.detect_overfitting(results)

        lines.append(f"Overfitting Risk  : {overfit_map['score']:.4f}")

        lines.append(f"Flagged           : {overfit_map['overfitting']}")

        lines.append("")
        lines.append("=" * 120)
        lines.append("END OPTIMIZER REPORT")
        lines.append("=" * 120)

        return "\n".join(lines)

    # ==========================================================
    # BATCH ANALYSIS
    # ==========================================================

    def batch_summary(
        self,
        results: list[OptimizationResult],
    ) -> dict[str, Any]:

        if not results:

            return {}

        scores = [r.score for r in results]

        return {
            "count": len(results),
            "avg_score": sum(scores) / len(scores),
            "max_score": max(scores),
            "min_score": min(scores),
            "score_variance": sum((x - sum(scores) / len(scores)) ** 2 for x in scores)
            / max(len(scores), 1),
        }

    # ==========================================================
    # CLI RUNNER
    # ==========================================================

    def run_cli(
        self,
        data: dict[str, Any],
        initial_capital: float,
        param_grid: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> None:

        results = self.grid_search(
            data=data,
            initial_capital=initial_capital,
            param_grid=param_grid,
            start_date=start_date,
            end_date=end_date,
        )

        print(self.report(results))

    # ==========================================================
    # EXPORT RESULTS
    # ==========================================================

    def export_results(
        self,
        results: list[OptimizationResult],
    ) -> list[dict[str, Any]]:

        return [
            {
                "params": r.params,
                "score": r.score,
                "sharpe": r.sharpe,
                "cagr": r.cagr,
                "drawdown": r.drawdown,
                "win_rate": r.win_rate,
            }
            for r in results
        ]

    # ==========================================================
    # RESET OPTIMIZER
    # ==========================================================

    def reset(self) -> None:

        self.results = []

        logger.info("Optimizer reset completed.")

    # ==========================================================
    # VALIDATION CHECK
    # ==========================================================

    def validate(self, results: list[OptimizationResult]) -> dict[str, Any]:

        issues = []

        if not results:

            return {
                "valid": False,
                "issues": ["NO_RESULTS"],
            }

        scores = [r.score for r in results]

        if max(scores) == min(scores):

            issues.append("NO_VARIANCE_IN_RESULTS")

        if max(scores) > 10:

            issues.append("POSSIBLE_SCORE_EXPLOSION")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }


# ==========================================================
# END OF FILE
# ==========================================================
