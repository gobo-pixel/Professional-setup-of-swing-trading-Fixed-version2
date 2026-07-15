"""
LIVE OPERATIONS SYSTEM

Purpose:
--------
• Real-time monitoring + control layer over trading system
• Converts system state into actionable operations
• Handles alerts, health tracking, and operational decisions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import time

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# LIVE OPS STATE
# ==========================================================


@dataclass
class LiveOpsState:

    last_health_score: float = 0.0

    last_risk_grade: str = "UNKNOWN"

    active_alerts: list[dict[str, Any]] = None

    system_mode: str = "IDLE"  # IDLE / MONITORING / ALERT / EMERGENCY

    last_update_time: float = 0.0


# ==========================================================
# LIVE OPERATIONS ENGINE
# ==========================================================


class LiveOperationsEngine:

    def __init__(self):

        self.state = LiveOpsState(active_alerts=[])

        logger.info("LIVE OPERATIONS ENGINE INITIALIZED")

    # ==========================================================
    # HEALTH UPDATE ENGINE (REAL-TIME INGESTION)
    # ==========================================================

    def update_health(
        self,
        analytics: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> float:

        pnl = portfolio.get("pnl", 0.0)

        equity = portfolio.get("equity", 1.0)

        drawdown = portfolio.get("max_drawdown", 0.0)

        latency = analytics.get("latency", 0.0)

        anomalies = len(analytics.get("anomalies", []))

        # ==========================================================
        # HEALTH SCORE MODEL
        # ==========================================================

        health_score = (
            (1 - min(drawdown, 1.0)) * 0.35
            + max(min(pnl / max(equity, 1e-9), 1.0), -1.0) * 0.25
            + (1 - min(latency / 2.0, 1.0)) * 0.20
            + (1 - min(anomalies / 5.0, 1.0)) * 0.20
        )

        health_score = max(0.0, min(1.0, health_score))

        self.state.last_health_score = health_score

        self.state.last_update_time = time.time()

        logger.info("LIVE HEALTH UPDATED: %.3f", health_score)

        return health_score

    # ==========================================================
    # RISK GRADE CLASSIFIER
    # ==========================================================

    def compute_risk_grade(
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

        self.state.last_risk_grade = grade

        logger.info("LIVE RISK GRADE: %s", grade)

        return grade

    # ==========================================================
    # SYSTEM STATUS CLASSIFIER
    # ==========================================================

    def system_status(self) -> str:

        h = self.state.last_health_score

        grade = self.state.last_risk_grade

        if grade == "F" or h < 0.35:

            status = "CRITICAL"

        elif grade in ["D"]:

            status = "DEGRADED"

        elif grade in ["C"]:

            status = "WARNING"

        elif grade in ["A", "B"]:

            status = "STABLE"

        else:

            status = "UNKNOWN"

        self.state.system_mode = status

        logger.info("SYSTEM STATUS: %s", status)

        return status

    # ==========================================================
    # ALERT GENERATION ENGINE
    # ==========================================================

    def create_alert(
        self,
        level: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        alert = {
            "timestamp": time.time(),
            "level": level,  # INFO / WARNING / CRITICAL / EMERGENCY
            "message": message,
            "context": context or {},
            "acknowledged": False,
        }

        self.state.active_alerts.append(alert)

        logger.warning(
            "ALERT GENERATED [%s]: %s",
            level,
            message,
        )

        return alert

    # ==========================================================
    # ALERT DEDUPLICATION ENGINE
    # ==========================================================

    def deduplicate_alerts(
        self,
        time_window: int = 60,
    ) -> None:

        current_time = time.time()

        unique = []

        seen = set()

        for alert in self.state.active_alerts:

            key = (alert["level"], alert["message"])

            if key in seen:

                continue

            if current_time - alert["timestamp"] > time_window:

                continue

            seen.add(key)

            unique.append(alert)

        self.state.active_alerts = unique

    # ==========================================================
    # ALERT ESCALATION LOGIC
    # ==========================================================

    def escalate_alerts(self) -> None:

        for alert in self.state.active_alerts:

            level = alert["level"]

            if level == "WARNING" and self.state.last_health_score < 0.5:

                alert["level"] = "CRITICAL"

                logger.critical(
                    "ALERT ESCALATED: %s",
                    alert["message"],
                )

            elif level == "CRITICAL" and self.state.last_health_score < 0.3:

                alert["level"] = "EMERGENCY"

                logger.critical(
                    "EMERGENCY ALERT: %s",
                    alert["message"],
                )

    # ==========================================================
    # ALERT ROUTER (OUTPUT CHANNELS)
    # ==========================================================

    def route_alert(
        self,
        alert: dict[str, Any],
    ) -> None:

        level = alert["level"]

        if level in ["INFO"]:

            logger.info(alert["message"])

        elif level in ["WARNING"]:

            logger.warning(alert["message"])

        elif level in ["CRITICAL", "EMERGENCY"]:

            logger.critical(alert["message"])

            # hook: telegram / dashboard / external systems

            # self.telegram.send(alert)

            # self.dashboard.push(alert)

    # ==========================================================
    # CONTROL INTERVENTION ENGINE
    # ==========================================================

    def apply_intervention(
        self,
        portfolio: dict[str, Any],
        risk_grade: str,
    ) -> dict[str, Any]:

        intervention = {
            "action": "NONE",
            "reason": None,
        }

        # ==========================================================
        # HARD SHUTDOWN CONDITIONS
        # ==========================================================

        if risk_grade == "F" or self.state.last_health_score < 0.25:

            intervention["action"] = "EMERGENCY_SHUTDOWN"

            intervention["reason"] = "CRITICAL_SYSTEM_FAILURE"

            self.state.system_mode = "EMERGENCY"

            logger.critical("INTERVENTION: EMERGENCY SHUTDOWN TRIGGERED")

            return intervention

        # ==========================================================
        # TRADING HALT CONDITIONS
        # ==========================================================

        if risk_grade == "D" or self.state.last_health_score < 0.40:

            intervention["action"] = "HALT_TRADING"

            intervention["reason"] = "DEGRADED_SYSTEM_HEALTH"

            self.state.system_mode = "DEGRADED"

            logger.warning("INTERVENTION: TRADING HALTED")

            return intervention

        # ==========================================================
        # RISK REDUCTION MODE
        # ==========================================================

        if risk_grade == "C" or self.state.last_health_score < 0.60:

            intervention["action"] = "REDUCE_EXPOSURE"

            intervention["reason"] = "RISK_CONTROL"

            logger.warning("INTERVENTION: EXPOSURE REDUCED")

            return intervention

        # ==========================================================
        # NORMAL OPERATION
        # ==========================================================

        self.state.system_mode = "MONITORING"

        return intervention

    # ==========================================================
    # AUTO RECOVERY ENGINE
    # ==========================================================

    def attempt_recovery(self) -> bool:

        if self.state.system_mode != "EMERGENCY":

            return False

        if self.state.last_health_score > 0.55:

            self.state.system_mode = "MONITORING"

            logger.info("RECOVERY SUCCESSFUL: SYSTEM RESTORED")

            return True

        logger.warning("RECOVERY FAILED: CONDITIONS NOT MET")

        return False

    # ==========================================================
    # SYSTEM FREEZE CONTROL
    # ==========================================================

    def freeze_system(self) -> None:

        self.state.system_mode = "FROZEN"

        logger.critical("SYSTEM FROZEN: ALL ACTIONS HALTED")

    # ==========================================================
    # MANUAL OVERRIDE HOOK
    # ==========================================================

    def manual_override(
        self,
        command: str,
    ) -> dict[str, Any]:

        if command == "STOP_ALL":

            self.freeze_system()

            return {
                "status": "OK",
                "action": "SYSTEM_FROZEN",
            }

        if command == "RESUME" and self.state.system_mode == "FROZEN":

            self.state.system_mode = "MONITORING"

            return {
                "status": "OK",
                "action": "SYSTEM_RESUMED",
            }

        return {
            "status": "IGNORED",
            "action": None,
        }

    # ==========================================================
    # HEARTBEAT ENGINE (SYSTEM LIVENESS CHECK)
    # ==========================================================

    def heartbeat(self) -> dict[str, Any]:

        now = time.time()

        last = self.state.last_update_time

        latency = now - last if last else 0.0

        alive = latency < 10.0

        heartbeat_signal = {
            "timestamp": now,
            "alive": alive,
            "latency": latency,
            "system_mode": self.state.system_mode,
            "health_score": self.state.last_health_score,
        }

        if not alive:

            logger.critical("HEARTBEAT FAILED: SYSTEM STALLED")

            self.create_alert(
                level="CRITICAL",
                message="SYSTEM HEARTBEAT LOST",
                context=heartbeat_signal,
            )

        return heartbeat_signal

    # ==========================================================
    # WATCHDOG MONITOR LOOP
    # ==========================================================

    def watchdog_check(
        self,
        portfolio: dict[str, Any],
        analytics: dict[str, Any],
    ) -> None:

        health = self.update_health(
            analytics=analytics,
            portfolio=portfolio,
        )

        risk_grade = self.compute_risk_grade(health)

        self.escalate_alerts()

        self.deduplicate_alerts()

        intervention = self.apply_intervention(
            portfolio=portfolio,
            risk_grade=risk_grade,
        )

        if intervention["action"] == "EMERGENCY_SHUTDOWN":

            self.create_alert(
                level="EMERGENCY",
                message="WATCHDOG TRIGGERED EMERGENCY SHUTDOWN",
                context=intervention,
            )

        elif intervention["action"] == "HALT_TRADING":

            self.create_alert(
                level="CRITICAL",
                message="WATCHDOG HALTED TRADING",
                context=intervention,
            )

        elif intervention["action"] == "REDUCE_EXPOSURE":

            self.create_alert(
                level="WARNING",
                message="WATCHDOG REDUCED EXPOSURE",
                context=intervention,
            )

    # ==========================================================
    # SILENT FAILURE DETECTION
    # ==========================================================

    def detect_silent_failure(self) -> bool:

        if self.state.last_update_time == 0:

            return True

        lag = time.time() - self.state.last_update_time

        if lag > 30:

            logger.critical("SILENT FAILURE DETECTED")

            self.create_alert(
                level="EMERGENCY",
                message="SYSTEM NOT UPDATING (SILENT FAILURE)",
                context={"lag": lag},
            )

            return True

        return False

    # ==========================================================
    # SYSTEM STATUS REPORT (OPS SUMMARY)
    # ==========================================================

    def system_report(self) -> dict[str, Any]:

        report = {
            "system_mode": self.state.system_mode,
            "health_score": self.state.last_health_score,
            "risk_grade": self.state.last_risk_grade,
            "active_alerts": len(self.state.active_alerts),
            "last_update": self.state.last_update_time,
            "heartbeat": self.heartbeat(),
        }

        logger.info("SYSTEM REPORT GENERATED")

        return report

    # ==========================================================
    # OPS DASHBOARD PAYLOAD
    # ==========================================================

    def dashboard_payload(self) -> dict[str, Any]:

        payload = {
            "health": self.state.last_health_score,
            "mode": self.state.system_mode,
            "risk": self.state.last_risk_grade,
            "alerts": [
                {
                    "level": a["level"],
                    "message": a["message"],
                    "time": a["timestamp"],
                }
                for a in self.state.active_alerts[-10:]
            ],
            "heartbeat_alive": self.heartbeat()["alive"],
        }

        return payload

    # ==========================================================
    # INTEGRATION HOOK (ORCHESTRATOR CONNECTOR)
    # ==========================================================

    def attach_to_orchestrator(
        self,
        orchestrator: Any,
    ) -> None:

        self.orchestrator = orchestrator

        logger.info("LIVE OPS ATTACHED TO ORCHESTRATOR")

    # ==========================================================
    # CLEAN SHUTDOWN EXPORT
    # ==========================================================

    def export_state(self) -> dict[str, Any]:

        state_dump = {
            "system_mode": self.state.system_mode,
            "health_score": self.state.last_health_score,
            "risk_grade": self.state.last_risk_grade,
            "alerts": self.state.active_alerts,
            "last_update": self.state.last_update_time,
        }

        logger.info("LIVE OPS STATE EXPORTED")

        return state_dump


# ==========================================================
# FINAL INTEGRATION ENTRYPOINT
# ==========================================================


def initialize_live_operations() -> LiveOperationsEngine:

    engine = LiveOperationsEngine()

    logger.info("LIVE OPERATIONS SYSTEM READY")

    return engine


# ==========================================================
# END OF LIVE OPERATIONS SYSTEM
# ==========================================================
