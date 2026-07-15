"""
DEPLOYMENT PHASE CONTROLLER

Purpose:
--------
• Move system from BACKTEST → PAPER → LIVE safely
• Enforce staged rollout
• Prevent direct unsafe live activation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import time

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# DEPLOYMENT STATE
# ==========================================================


@dataclass
class DeploymentState:

    stage: str = "BACKTEST"  # BACKTEST / PAPER / LIVE

    safety_score: float = 0.0

    last_validation_passed: bool = False

    paper_trading_days: int = 0

    live_trading_enabled: bool = False

    kill_switch_enabled: bool = True

    last_metrics: dict[str, Any] = None


# ==========================================================
# DEPLOYMENT CONTROLLER
# ==========================================================


class DeploymentController:

    def __init__(self):

        self.state = DeploymentState()

        logger.info("Deployment Controller initialized")

    # ==========================================================
    # BACKTEST VALIDATION GATE
    # ==========================================================

    def validate_backtest(
        self,
        analytics_summary: dict[str, Any],
    ) -> bool:

        sharpe = analytics_summary.get("sharpe", 0.0)

        cagr = analytics_summary.get("cagr", 0.0)

        max_dd = analytics_summary.get("max_drawdown", 0.0)

        win_rate = analytics_summary.get("win_rate", 0.0)

        profit_factor = analytics_summary.get("profit_factor", 0.0)

        # ==========================================================
        # HARD THRESHOLDS (NO EXCEPTIONS)
        # ==========================================================

        if sharpe < 0.5:

            logger.warning("BACKTEST FAIL: LOW SHARPE")

            return False

        if cagr <= 0:

            logger.warning("BACKTEST FAIL: NON-POSITIVE CAGR")

            return False

        if max_dd > 0.25:

            logger.warning("BACKTEST FAIL: EXCESSIVE DRAWDOWN")

            return False

        if win_rate < 0.4:

            logger.warning("BACKTEST FAIL: LOW WIN RATE")

            return False

        if profit_factor < 1.2:

            logger.warning("BACKTEST FAIL: LOW PROFIT FACTOR")

            return False

        self.state.last_validation_passed = True

        self.state.safety_score = (
            sharpe * 0.3 + cagr * 0.3 + (1 - max_dd) * 0.2 + win_rate * 0.2
        )

        logger.info(
            "BACKTEST VALIDATION PASSED | SafetyScore=%.3f",
            self.state.safety_score,
        )

        return True

    # ==========================================================
    # OVERFITTING GUARD
    # ==========================================================

    def detect_overfitting_risk(
        self,
        analytics: dict[str, Any],
    ) -> bool:

        anomalies = analytics.get("anomalies", [])

        overfit_score = analytics.get("overfitting_score", 0.0)

        if overfit_score > 0.6:

            logger.error("OVERFITTING DETECTED")

            return True

        if len(anomalies) > 2:

            logger.error("MULTIPLE ANOMALIES DETECTED")

            return True

        return False

    # ==========================================================
    # ENTER PAPER TRADING MODE
    # ==========================================================

    def enter_paper_mode(
        self,
        backtest_metrics: dict[str, Any],
    ) -> bool:

        if not self.validate_backtest(backtest_metrics):

            logger.error("CANNOT ENTER PAPER MODE")

            return False

        if self.detect_overfitting_risk(backtest_metrics):

            logger.error("PAPER MODE BLOCKED DUE TO OVERFITTING")

            return False

        self.state.stage = "PAPER"

        self.state.paper_trading_days = 0

        self.state.live_trading_enabled = False

        logger.info("ENTERED PAPER TRADING MODE")

        return True

    # ==========================================================
    # PAPER TRADING DAILY UPDATE
    # ==========================================================

    def update_paper_performance(
        self,
        paper_metrics: dict[str, Any],
    ) -> None:

        if self.state.stage != "PAPER":

            logger.warning("NOT IN PAPER MODE")

            return

        self.state.paper_trading_days += 1

        self.state.last_metrics = paper_metrics

        logger.info(
            "PAPER DAY %d UPDATED",
            self.state.paper_trading_days,
        )

    # ==========================================================
    # PAPER MODE STABILITY CHECK
    # ==========================================================

    def paper_stability_check(
        self,
        paper_metrics: dict[str, Any],
    ) -> bool:

        sharpe = paper_metrics.get("sharpe", 0.0)

        drawdown = paper_metrics.get("max_drawdown", 0.0)

        if sharpe < 0.3:

            logger.warning("PAPER FAIL: SHARPE TOO LOW")

            return False

        if drawdown > 0.30:

            logger.warning("PAPER FAIL: DRAWDOWN TOO HIGH")

            return False

        if self.state.paper_trading_days < 5:

            logger.warning("PAPER MODE INSUFFICIENT DATA")

            return False

        logger.info("PAPER STABILITY PASSED")

        return True

    # ==========================================================
    # PAPER → LIVE READINESS CHECK
    # ==========================================================

    def ready_for_live(self) -> bool:

        if self.state.stage != "PAPER":

            return False

        if self.state.paper_trading_days < 10:

            logger.warning("NOT ENOUGH PAPER TRADING HISTORY")

            return False

        if self.state.last_metrics is None:

            return False

        return self.paper_stability_check(self.state.last_metrics)

    # ==========================================================
    # LIVE DEPLOYMENT APPROVAL GATE
    # ==========================================================

    def approve_live_deployment(
        self,
        paper_metrics: dict[str, Any],
    ) -> bool:

        if self.state.stage != "PAPER":

            logger.error("LIVE REJECTED: NOT IN PAPER MODE")

            return False

        if not self.ready_for_live():

            logger.error("LIVE REJECTED: PAPER STABILITY FAILED")

            return False

        sharpe = paper_metrics.get("sharpe", 0.0)

        drawdown = paper_metrics.get("max_drawdown", 0.0)

        win_rate = paper_metrics.get("win_rate", 0.0)

        # ==========================================================
        # STRICT LIVE THRESHOLDS
        # ==========================================================

        if sharpe < 0.4:

            logger.error("LIVE REJECTED: SHARPE TOO LOW")

            return False

        if drawdown > 0.20:

            logger.error("LIVE REJECTED: DRAWDOWN TOO HIGH")

            return False

        if win_rate < 0.45:

            logger.error("LIVE REJECTED: WIN RATE TOO LOW")

            return False

        self.state.stage = "LIVE"

        self.state.live_trading_enabled = True

        self.state.kill_switch_enabled = True

        logger.critical("LIVE DEPLOYMENT APPROVED")

        return True

    # ==========================================================
    # LIVE EXPOSURE CONTROL (GRADUAL RAMP-UP)
    # ==========================================================

    def exposure_ramp_up(
        self,
        current_exposure: float,
        target_exposure: float,
        step: float = 0.05,
    ) -> float:

        if self.state.stage != "LIVE":

            return current_exposure

        new_exposure = min(
            current_exposure + step,
            target_exposure,
        )

        logger.info(
            "EXPOSURE RAMP: %.2f → %.2f",
            current_exposure,
            new_exposure,
        )

        return new_exposure

    # ==========================================================
    # LIVE SAFETY MONITOR
    # ==========================================================

    def live_safety_monitor(
        self,
        live_metrics: dict[str, Any],
    ) -> bool:

        pnl = live_metrics.get("pnl", 0.0)

        drawdown = live_metrics.get("max_drawdown", 0.0)

        exposure = live_metrics.get("exposure", 0.0)

        if pnl < -0.05:

            logger.critical("LIVE HALT: DAILY LOSS LIMIT")

            return False

        if drawdown > 0.15:

            logger.critical("LIVE HALT: DRAWDOWN LIMIT")

            return False

        if exposure > 0.90:

            logger.critical("LIVE HALT: EXCESS EXPOSURE")

            return False

        return True

    # ==========================================================
    # EMERGENCY ROLLBACK (LIVE → PAPER)
    # ==========================================================

    def rollback_to_paper(
        self,
        reason: str = "UNSAFE_LIVE_BEHAVIOR",
    ) -> None:

        if self.state.stage != "LIVE":

            logger.warning("ROLLBACK IGNORED: NOT IN LIVE MODE")

            return

        self.state.stage = "PAPER"

        self.state.live_trading_enabled = False

        logger.critical(
            "ROLLBACK EXECUTED | Reason: %s",
            reason,
        )

    # ==========================================================
    # AUTO CORRUPTION DETECTION
    # ==========================================================

    def detect_system_corruption(
        self,
        live_metrics: dict[str, Any],
    ) -> bool:

        anomalies = live_metrics.get("anomalies", [])

        data_latency = live_metrics.get("latency", 0.0)

        execution_mismatch = live_metrics.get("exec_mismatch", False)

        if len(anomalies) > 3:

            logger.error("CORRUPTION: TOO MANY ANOMALIES")

            return True

        if data_latency > 2.0:

            logger.error("CORRUPTION: HIGH LATENCY")

            return True

        if execution_mismatch:

            logger.error("CORRUPTION: EXECUTION MISMATCH")

            return True

        return False

    # ==========================================================
    # EMERGENCY STOP OVERRIDE (GLOBAL SHUTDOWN)
    # ==========================================================

    def emergency_shutdown(
        self,
        reason: str = "CRITICAL_FAILURE",
    ) -> None:

        self.state.stage = "HALTED"

        self.state.live_trading_enabled = False

        self.state.kill_switch_enabled = True

        logger.critical(
            "SYSTEM SHUTDOWN | Reason: %s",
            reason,
        )

    # ==========================================================
    # FAILSAFE RECOVERY MODE
    # ==========================================================

    def recovery_mode(
        self,
    ) -> None:

        if self.state.stage != "HALTED":

            return

        logger.warning("ATTEMPTING SAFE RECOVERY")

        self.state.stage = "PAPER"

        self.state.live_trading_enabled = False

        self.state.paper_trading_days = 0

        logger.info("RECOVERY MODE ACTIVATED (PAPER ONLY)")

    # ==========================================================
    # SYSTEM HEALTH SCORE (REAL-TIME)
    # ==========================================================

    def compute_health_score(
        self,
        live_metrics: dict[str, Any],
    ) -> float:

        pnl = live_metrics.get("pnl", 0.0)

        drawdown = live_metrics.get("max_drawdown", 0.0)

        latency = live_metrics.get("latency", 0.0)

        anomalies = len(live_metrics.get("anomalies", []))

        # ==========================================================
        # NORMALIZED HEALTH MODEL
        # ==========================================================

        health = (
            (1 - min(drawdown, 1.0)) * 0.35
            + max(min(pnl, 1.0), -1.0) * 0.25
            + (1 - min(latency / 2.0, 1.0)) * 0.20
            + (1 - min(anomalies / 5.0, 1.0)) * 0.20
        )

        health = max(0.0, min(1.0, health))

        logger.info("SYSTEM HEALTH SCORE: %.3f", health)

        return health

    # ==========================================================
    # DEPLOYMENT RISK GRADE (A–F)
    # ==========================================================

    def risk_grade(
        self,
        health_score: float,
    ) -> str:

        if health_score >= 0.85:

            grade = "A"

        elif health_score >= 0.70:

            grade = "B"

        elif health_score >= 0.55:

            grade = "C"

        elif health_score >= 0.40:

            grade = "D"

        else:

            grade = "F"

        logger.info("RISK GRADE ASSIGNED: %s", grade)

        return grade

    # ==========================================================
    # STABILITY INDEX (LONG TERM BEHAVIOR)
    # ==========================================================

    def stability_index(
        self,
        history: list[dict[str, Any]],
    ) -> float:

        if len(history) < 5:

            return 0.0

        pnl_series = [h.get("pnl", 0.0) for h in history[-10:]]

        mean = sum(pnl_series) / len(pnl_series)

        variance = sum((x - mean) ** 2 for x in pnl_series) / len(pnl_series)

        stability = 1 / (1 + variance)

        logger.info("STABILITY INDEX: %.3f", stability)

        return stability

    # ==========================================================
    # DEPLOYMENT CONFIDENCE SCORE
    # ==========================================================

    def deployment_confidence(
        self,
        health_score: float,
        stability_index: float,
        risk_grade: str,
    ) -> float:

        grade_weight = {
            "A": 1.0,
            "B": 0.8,
            "C": 0.6,
            "D": 0.3,
            "F": 0.0,
        }.get(risk_grade, 0.0)

        confidence = health_score * 0.5 + stability_index * 0.3 + grade_weight * 0.2

        confidence = max(0.0, min(1.0, confidence))

        logger.info("DEPLOYMENT CONFIDENCE: %.3f", confidence)

        return confidence

    # ==========================================================
    # MODE TRANSITION CONTROLLER (CONTROL PLANE)
    # ==========================================================

    def switch_mode(
        self,
        target_mode: str,
        metrics: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> bool:

        current_health = self.compute_health_score(metrics)

        risk_grade = self.risk_grade(current_health)

        stability = self.stability_index(history)

        confidence = self.deployment_confidence(
            current_health,
            stability,
            risk_grade,
        )

        # ==========================================================
        # BACKTEST → PAPER TRANSITION
        # ==========================================================

        if self.state.stage == "BACKTEST" and target_mode == "PAPER":

            if confidence < 0.6:

                logger.warning("TRANSITION BLOCKED: LOW CONFIDENCE")

                return False

            self.state.stage = "PAPER"

            self.state.paper_trading_days = 0

            logger.info("TRANSITION: BACKTEST → PAPER")

            return True

        # ==========================================================
        # PAPER → LIVE TRANSITION
        # ==========================================================

        if self.state.stage == "PAPER" and target_mode == "LIVE":

            if confidence < 0.85:

                logger.warning("TRANSITION BLOCKED: INSUFFICIENT CONFIDENCE")

                return False

            if risk_grade not in ["A", "B"]:

                logger.warning("TRANSITION BLOCKED: BAD RISK GRADE")

                return False

            if self.state.paper_trading_days < 10:

                logger.warning("TRANSITION BLOCKED: INSUFFICIENT PAPER HISTORY")

                return False

            self.state.stage = "LIVE"

            self.state.live_trading_enabled = True

            logger.critical("TRANSITION: PAPER → LIVE APPROVED")

            return True

        # ==========================================================
        # LIVE → PAPER (AUTO DOWNGRADE)
        # ==========================================================

        if self.state.stage == "LIVE" and target_mode == "PAPER":

            logger.critical("DOWNGRADE: LIVE → PAPER")

            self.state.stage = "PAPER"

            self.state.live_trading_enabled = False

            return True

        # ==========================================================
        # LIVE → HALT (EMERGENCY STOP)
        # ==========================================================

        if self.state.stage == "LIVE" and target_mode == "HALTED":

            self.emergency_shutdown("MANUAL HALT REQUEST")

            return True

        return False

    # ==========================================================
    # AUTO MODE SUPERVISOR (RUNS EACH CYCLE)
    # ==========================================================

    def auto_supervisor(
        self,
        metrics: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> None:

        health = self.compute_health_score(metrics)

        risk_grade = self.risk_grade(health)

        stability = self.stability_index(history)

        confidence = self.deployment_confidence(
            health,
            stability,
            risk_grade,
        )

        if self.state.stage == "LIVE" and confidence < 0.5:

            logger.critical("AUTO SUPERVISOR: DOWNGRADE TRIGGERED")

            self.rollback_to_paper("LOW_CONFIDENCE")

        if self.state.stage == "PAPER" and confidence > 0.9:

            logger.info("AUTO SUPERVISOR: LIVE READY SIGNAL")

    # ==========================================================
    # FINAL SAFETY CHECKLIST (PRE-DEPLOY)
    # ==========================================================

    def final_safety_check(
        self,
        metrics: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> bool:

        health = self.compute_health_score(metrics)

        stability = self.stability_index(history)

        risk = self.risk_grade(health)

        confidence = self.deployment_confidence(
            health,
            stability,
            risk,
        )

        if confidence < 0.8:

            logger.critical("FINAL CHECK FAILED: LOW CONFIDENCE")

            return False

        if risk in ["D", "F"]:

            logger.critical("FINAL CHECK FAILED: BAD RISK GRADE")

            return False

        logger.info("FINAL SAFETY CHECK PASSED")

        return True

    # ==========================================================
    # FULL DEPLOYMENT PIPELINE (MASTER ENTRYPOINT)
    # ==========================================================

    def deploy(
        self,
        metrics: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> bool:

        logger.info("DEPLOYMENT PIPELINE STARTED")

        # STEP 1: BACKTEST VALIDATION REQUIRED FIRST

        if self.state.stage == "BACKTEST":

            if not self.validate_backtest(metrics):

                logger.critical("DEPLOY FAILED: BACKTEST INVALID")

                return False

            return self.switch_mode(
                target_mode="PAPER",
                metrics=metrics,
                history=history,
            )

        # STEP 2: PAPER → LIVE ATTEMPT

        if self.state.stage == "PAPER":

            if not self.ready_for_live():

                logger.warning("DEPLOY BLOCKED: PAPER NOT READY")

                return False

            return self.switch_mode(
                target_mode="LIVE",
                metrics=metrics,
                history=history,
            )

        # STEP 3: LIVE FINAL SAFETY GATE

        if self.state.stage == "LIVE":

            if not self.final_safety_check(metrics, history):

                logger.critical("LIVE DEPLOYMENT UNSAFE")

                self.rollback_to_paper("FINAL_CHECK_FAILED")

                return False

            logger.critical("SYSTEM FULLY DEPLOYED IN LIVE MODE")

            return True

        return False

    # ==========================================================
    # SYSTEM INITIALIZATION ENTRYPOINT
    # ==========================================================

    def initialize_system(self) -> None:

        logger.info("INITIALIZING DEPLOYMENT SYSTEM")

        self.state.stage = "BACKTEST"

        self.state.live_trading_enabled = False

        self.state.kill_switch_enabled = True

        self.state.paper_trading_days = 0

        logger.info("SYSTEM READY FOR BACKTEST VALIDATION")


# ==========================================================
# END OF DEPLOYMENT SYSTEM
# ==========================================================
