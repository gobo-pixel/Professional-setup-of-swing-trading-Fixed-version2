"""
Learning Engine

Purpose:
--------
• Continuous adaptation layer over optimizer + analytics
• Learns from live + backtest performance drift
• Updates strategy parameters dynamically over time

This is the "self-improving brain" of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# LEARNING STATE
# ==========================================================


@dataclass(slots=True)
class LearningState:

    iteration: int = 0

    learning_rate: float = 0.05

    exploration_rate: float = 0.1

    exploitation_bias: float = 0.9

    parameter_memory: list[dict[str, Any]] = field(default_factory=list)

    performance_memory: list[float] = field(default_factory=list)

    regime_memory: list[str] = field(default_factory=list)

    diagnostics: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# LEARNING ENGINE
# ==========================================================


class LearningEngine:

    def __init__(self):

        self.state = LearningState()

        logger.info("Learning Engine initialized.")

    # ==========================================================
    # INGEST OPTIMIZATION + ANALYTICS FEEDBACK
    # ==========================================================

    def ingest_feedback(
        self,
        params: dict[str, Any],
        analytics_state: Any,
    ) -> None:

        metrics = analytics_state.metrics

        diagnostics = analytics_state.diagnostics

        score = diagnostics.get("final_score", 0.0)

        regime = diagnostics.get("market_regime", "UNKNOWN")

        self.state.parameter_memory.append(params)

        self.state.performance_memory.append(score)

        self.state.regime_memory.append(regime)

        self.state.iteration += 1

        self.state.diagnostics["last_ingested"] = {
            "iteration": self.state.iteration,
            "score": score,
            "regime": regime,
        }

    # ==========================================================
    # PERFORMANCE TREND ANALYSIS
    # ==========================================================

    def compute_performance_trend(self) -> float:

        if len(self.state.performance_memory) < 2:

            return 0.0

        values = np.array(self.state.performance_memory)

        trend = np.polyfit(
            np.arange(len(values)),
            values,
            1,
        )[0]

        self.state.diagnostics["performance_trend"] = trend

        return float(trend)

    # ==========================================================
    # REGIME DISTRIBUTION TRACKING
    # ==========================================================

    def regime_distribution(self) -> dict[str, float]:

        if not self.state.regime_memory:

            return {}

        total = len(self.state.regime_memory)

        counts = {}

        for r in self.state.regime_memory:

            counts[r] = counts.get(r, 0) + 1

        distribution = {k: v / total for k, v in counts.items()}

        self.state.diagnostics["regime_distribution"] = distribution

        return distribution

    # ==========================================================
    # ADAPTIVE PARAMETER WEIGHTING
    # ==========================================================

    def compute_param_weights(self) -> dict[str, float]:

        if not self.state.parameter_memory:

            return {}

        latest_params = self.state.parameter_memory[-1]

        weights = {}

        performance = np.array(self.state.performance_memory)

        if len(performance) == 0:

            return {}

        for key in latest_params.keys():

            correlated_scores = []

            for i, params in enumerate(self.state.parameter_memory):

                if key in params:

                    correlated_scores.append(performance[i])

            if correlated_scores:

                weights[key] = float(np.mean(correlated_scores))

        self.state.diagnostics["param_weights"] = weights

        return weights

    # ==========================================================
    # EXPLORATION VS EXPLOITATION BALANCE
    # ==========================================================

    def update_exploration_rate(self) -> float:

        if len(self.state.performance_memory) < 5:

            return self.state.exploration_rate

        recent = self.state.performance_memory[-5:]

        older = self.state.performance_memory[:-5]

        if not older:

            return self.state.exploration_rate

        recent_avg = float(np.mean(recent))

        older_avg = float(np.mean(older))

        improvement = recent_avg - older_avg

        if improvement > 0:

            self.state.exploration_rate *= 0.95

        else:

            self.state.exploration_rate *= 1.05

        self.state.exploration_rate = max(
            0.01,
            min(0.5, self.state.exploration_rate),
        )

        self.state.diagnostics["exploration_rate"] = self.state.exploration_rate

        return self.state.exploration_rate

    # ==========================================================
    # EXPLOITATION BIAS UPDATE
    # ==========================================================

    def update_exploitation_bias(self) -> float:

        bias = 1 - self.state.exploration_rate

        self.state.exploitation_bias = bias

        self.state.diagnostics["exploitation_bias"] = bias

        return bias

    # ==========================================================
    # DYNAMIC MUTATION CONTROL
    # ==========================================================

    def adaptive_mutation_rate(self) -> float:

        if len(self.state.performance_memory) < 5:

            return 0.1

        recent = self.state.performance_memory[-5:]

        variance = float(np.var(recent))

        mutation_rate = 0.05 + (variance * 0.5)

        mutation_rate = max(
            0.01,
            min(0.3, mutation_rate),
        )

        self.state.diagnostics["mutation_rate"] = mutation_rate

        return mutation_rate

    # ==========================================================
    # STRATEGY DRIFT DETECTION
    # ==========================================================

    def detect_strategy_drift(self) -> dict[str, Any]:

        if len(self.state.performance_memory) < 10:

            return {
                "drift": False,
                "score": 0.0,
            }

        early = self.state.performance_memory[:5]

        late = self.state.performance_memory[-5:]

        early_mean = float(np.mean(early))

        late_mean = float(np.mean(late))

        drift_score = abs(late_mean - early_mean)

        drift = drift_score > 0.2

        self.state.diagnostics["strategy_drift"] = {
            "drift": drift,
            "score": drift_score,
            "early_mean": early_mean,
            "late_mean": late_mean,
        }

        return self.state.diagnostics["strategy_drift"]

    # ==========================================================
    # PERFORMANCE DECAY MODEL
    # ==========================================================

    def compute_performance_decay(self) -> float:

        if len(self.state.performance_memory) < 3:

            return 0.0

        values = np.array(self.state.performance_memory)

        decay = float(np.mean(values[:-1] - values[1:]))

        self.state.diagnostics["performance_decay"] = decay

        return decay

    # ==========================================================
    # REWARD FUNCTION (LEARNING SIGNAL)
    # ==========================================================

    def compute_reward(self) -> float:

        if not self.state.performance_memory:

            return 0.0

        latest_score = self.state.performance_memory[-1]

        trend = self.compute_performance_trend()

        decay = self.compute_performance_decay()

        reward = latest_score * 0.6 + trend * 0.3 - decay * 0.2

        self.state.diagnostics["reward"] = reward

        return reward

    # ==========================================================
    # FEEDBACK NORMALIZATION
    # ==========================================================

    def normalize_feedback(self) -> list[float]:

        if not self.state.performance_memory:

            return []

        values = np.array(self.state.performance_memory)

        mean = float(np.mean(values))

        std = float(np.std(values))

        if std == 0:

            normalized = values - mean

        else:

            normalized = (values - mean) / std

        normalized_list = normalized.tolist()

        self.state.diagnostics["normalized_feedback"] = normalized_list

        return normalized_list

    # ==========================================================
    # LEARNING SIGNAL SHAPER
    # ==========================================================

    def shape_learning_signal(self) -> dict[str, float]:

        reward = self.compute_reward()

        trend = self.compute_performance_trend()

        decay = self.compute_performance_decay()

        exploration = self.state.exploration_rate

        exploitation = self.state.exploitation_bias

        signal = {
            "reward_signal": reward,
            "trend_signal": trend,
            "decay_signal": decay,
            "exploration_pressure": exploration,
            "exploitation_pressure": exploitation,
        }

        self.state.diagnostics["learning_signal"] = signal

        return signal

    # ==========================================================
    # ONLINE PARAMETER UPDATE (CORE LEARNING STEP)
    # ==========================================================

    def update_parameters(
        self,
        current_params: dict[str, Any],
    ) -> dict[str, Any]:

        if not self.state.performance_memory:

            return current_params

        weights = self.compute_param_weights()

        reward = self.compute_reward()

        mutation_rate = self.adaptive_mutation_rate()

        updated_params = current_params.copy()

        for key, value in updated_params.items():

            influence = weights.get(key, 0.5)

            adjustment_factor = reward * 0.1 * influence

            if isinstance(value, (int, float)):

                noise = np.random.uniform(
                    -mutation_rate,
                    mutation_rate,
                )

                updated_params[key] = type(value)(
                    value * (1 + adjustment_factor + noise)
                )

            elif isinstance(value, list) and value:

                if np.random.random() < mutation_rate:

                    updated_params[key] = np.random.choice(value)

        self.state.diagnostics["updated_params"] = updated_params

        return updated_params

    # ==========================================================
    # LEARNING STEP (FULL CYCLE UPDATE)
    # ==========================================================

    def learning_step(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:

        self.compute_performance_trend()

        self.regime_distribution()

        self.update_exploration_rate()

        self.update_exploitation_bias()

        updated = self.update_parameters(params)

        self.shape_learning_signal()

        return updated

    # ==========================================================
    # MEMORY PRUNING (CONTROL MEMORY GROWTH)
    # ==========================================================

    def prune_memory(
        self,
        max_size: int = 200,
    ) -> None:

        if len(self.state.performance_memory) > max_size:

            self.state.performance_memory = self.state.performance_memory[-max_size:]

            self.state.parameter_memory = self.state.parameter_memory[-max_size:]

            self.state.regime_memory = self.state.regime_memory[-max_size:]

        self.state.diagnostics["memory_size"] = {
            "performance": len(self.state.performance_memory),
            "parameters": len(self.state.parameter_memory),
            "regimes": len(self.state.regime_memory),
        }

    # ==========================================================
    # CATASTROPHIC FORGETTING PROTECTION
    # ==========================================================

    def prevent_forgetting(self) -> float:

        if len(self.state.performance_memory) < 10:

            return 0.0

        early = self.state.performance_memory[:5]

        recent = self.state.performance_memory[-5:]

        early_mean = float(np.mean(early))

        recent_mean = float(np.mean(recent))

        retention_score = 1 - abs(recent_mean - early_mean)

        retention_score = max(0.0, min(1.0, retention_score))

        self.state.diagnostics["retention_score"] = retention_score

        return retention_score

    # ==========================================================
    # STABILITY LOCK (FREEZE LEARNING IF TOO VOLATILE)
    # ==========================================================

    def stability_lock(self) -> bool:

        if len(self.state.performance_memory) < 10:

            return False

        values = np.array(self.state.performance_memory)

        volatility = float(np.std(values))

        lock = volatility > 1.5

        self.state.diagnostics["stability_lock"] = {
            "locked": lock,
            "volatility": volatility,
        }

        return lock

    # ==========================================================
    # REGIME-AWARE LEARNING CONTROL
    # ==========================================================

    def regime_aware_adjustment(self) -> dict[str, float]:

        if not self.state.regime_memory:

            return {}

        current_regime = self.state.regime_memory[-1]

        adjustments = {
            "TRENDING": {
                "learning_rate": 1.2,
                "exploration_rate": 0.8,
            },
            "SIDEWAYS": {
                "learning_rate": 0.9,
                "exploration_rate": 1.1,
            },
            "HIGH_VOLATILITY": {
                "learning_rate": 0.7,
                "exploration_rate": 1.3,
            },
            "MIXED": {
                "learning_rate": 1.0,
                "exploration_rate": 1.0,
            },
            "UNKNOWN": {
                "learning_rate": 0.85,
                "exploration_rate": 1.0,
            },
        }

        adj = adjustments.get(current_regime, adjustments["UNKNOWN"])

        self.state.learning_rate *= adj["learning_rate"]

        self.state.exploration_rate *= adj["exploration_rate"]

        self.state.learning_rate = max(
            0.001,
            min(0.2, self.state.learning_rate),
        )

        self.state.exploration_rate = max(
            0.01,
            min(0.5, self.state.exploration_rate),
        )

        self.state.diagnostics["regime_adjustment"] = {
            "regime": current_regime,
            "learning_rate": self.state.learning_rate,
            "exploration_rate": self.state.exploration_rate,
        }

        return self.state.diagnostics["regime_adjustment"]

    # ==========================================================
    # ADAPTIVE EXPLORATION SCHEDULER
    # ==========================================================

    def exploration_schedule(self) -> float:

        trend = self.compute_performance_trend()

        decay = self.compute_performance_decay()

        if trend > 0:

            self.state.exploration_rate *= 0.95

        else:

            self.state.exploration_rate *= 1.05

        if decay > 0:

            self.state.exploration_rate *= 1.02

        self.state.exploration_rate = max(
            0.01,
            min(0.6, self.state.exploration_rate),
        )

        self.state.diagnostics["exploration_schedule"] = self.state.exploration_rate

        return self.state.exploration_rate

    # ==========================================================
    # LEARNING RATE DECAY
    # ==========================================================

    def decay_learning_rate(self) -> float:

        if len(self.state.performance_memory) < 5:

            return self.state.learning_rate

        stability = self.prevent_forgetting()

        if stability > 0.7:

            self.state.learning_rate *= 0.98

        elif stability < 0.4:

            self.state.learning_rate *= 1.05

        self.state.learning_rate = max(
            0.001,
            min(0.3, self.state.learning_rate),
        )

        self.state.diagnostics["learning_rate"] = self.state.learning_rate

        return self.state.learning_rate

    # ==========================================================
    # META-LEARNING SCORE
    # ==========================================================

    def compute_meta_learning_score(self) -> float:

        if not self.state.performance_memory:

            return 0.0

        performance = np.array(self.state.performance_memory)

        trend = self.compute_performance_trend()

        stability = self.prevent_forgetting()

        decay = self.compute_performance_decay()

        mean_perf = float(np.mean(performance))

        meta_score = mean_perf * 0.4 + trend * 0.3 + stability * 0.2 - decay * 0.1

        self.state.diagnostics["meta_learning_score"] = meta_score

        return meta_score

    # ==========================================================
    # STRATEGY EVOLUTION INDEX
    # ==========================================================

    def evolution_index(self) -> float:

        if len(self.state.performance_memory) < 5:

            return 0.0

        recent = self.state.performance_memory[-5:]

        older = self.state.performance_memory[:-5]

        if not older:

            return 0.0

        recent_mean = float(np.mean(recent))

        older_mean = float(np.mean(older))

        improvement = recent_mean - older_mean

        volatility = float(np.std(self.state.performance_memory))

        evolution = improvement / max(volatility + 1e-9, 1e-9)

        self.state.diagnostics["evolution_index"] = evolution

        return evolution

    # ==========================================================
    # ADAPTIVE STRATEGY WEIGHT UPDATE
    # ==========================================================

    def update_strategy_weights(
        self,
        strategy_weights: dict[str, float],
    ) -> dict[str, float]:

        meta_score = self.compute_meta_learning_score()

        evolution = self.evolution_index()

        updated_weights = strategy_weights.copy()

        for key in updated_weights:

            adjustment = meta_score * 0.05 + evolution * 0.03

            updated_weights[key] *= 1 + adjustment

        self.state.diagnostics["strategy_weights"] = updated_weights

        return updated_weights

    # ==========================================================
    # FULL LEARNING CYCLE (MAIN ENTRYPOINT)
    # ==========================================================

    def run_learning_cycle(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:

        if self.stability_lock():

            self.state.diagnostics["cycle_status"] = "LOCKED"

            return params

        self.ingest_feedback(
            params=params,
            analytics_state=self.state.diagnostics.get(
                "last_analytics", type("obj", (), {"metrics": {}, "diagnostics": {}})()
            ),
        )

        self.compute_performance_trend()

        self.regime_distribution()

        self.update_exploration_rate()

        self.update_exploitation_bias()

        self.regime_aware_adjustment()

        self.exploration_schedule()

        self.decay_learning_rate()

        updated_params = self.update_parameters(params)

        self.shape_learning_signal()

        self.prune_memory()

        self.state.diagnostics["cycle_status"] = "ACTIVE"

        return updated_params

    # ==========================================================
    # SYSTEM HEALTH CHECK
    # ==========================================================

    def health_check(self) -> dict[str, Any]:

        return {
            "iteration": self.state.iteration,
            "learning_rate": self.state.learning_rate,
            "exploration_rate": self.state.exploration_rate,
            "stability_lock": self.stability_lock(),
            "meta_learning_score": self.state.diagnostics.get(
                "meta_learning_score",
                0.0,
            ),
            "evolution_index": self.state.diagnostics.get(
                "evolution_index",
                0.0,
            ),
        }

    # ==========================================================
    # RESET ENGINE
    # ==========================================================

    def reset(self) -> None:

        self.state = LearningState()

        logger.info("Learning Engine reset completed.")


# ==========================================================
# END OF FILE
# ==========================================================
