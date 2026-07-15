import csv
import json
import os
import time

from core.logger import get_logger

logger = get_logger(__name__)


class ReportGenerator:

    MASTER_CSV = "storage/reports/master_report.csv"

    FIELDNAMES = [
        "timestamp",
        "cycle_id",
        "equity",
        "pnl",
        "exposure",
        "risk_level",
        "buy_candidates",
        "sell_candidates",
        "orders_executed",
    ]

    def generate(self, analytics: dict, portfolio: dict, risk: dict) -> dict:

        report = {
            "timestamp": time.time(),
            "analytics": analytics,
            "portfolio": portfolio,
            "risk": risk,
            "summary": {
                "equity": portfolio.get("equity", 0),
                "pnl": portfolio.get("pnl", 0),
                "risk_level": risk.get("grade", "UNKNOWN"),
            },
        }

        logger.info("Report generated")

        return report

    def save_json(self, report: dict, path: str = None):

        path = path or f"storage/reports/report_{int(time.time())}.json"

        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w") as f:

            json.dump(report, f, indent=2, default=str)

        logger.info(f"Report saved at {path}")

    def append_master_report(self, report: dict, extra: dict | None = None) -> None:
        """Append one row per cycle/day into a single running master CSV,
        so the whole history is readable in one place (Excel/pandas/etc.)
        instead of scattered timestamped JSON files.
        """
        extra = extra or {}
        row = {
            "timestamp": report.get("timestamp", time.time()),
            "cycle_id": extra.get("cycle_id", ""),
            "equity": report["summary"].get("equity", 0),
            "pnl": report["summary"].get("pnl", 0),
            "exposure": report.get("portfolio", {}).get("exposure", 0),
            "risk_level": report["summary"].get("risk_level", "UNKNOWN"),
            "buy_candidates": extra.get("buy_candidates", 0),
            "sell_candidates": extra.get("sell_candidates", 0),
            "orders_executed": extra.get("orders_executed", 0),
        }

        os.makedirs(os.path.dirname(self.MASTER_CSV), exist_ok=True)
        file_exists = os.path.isfile(self.MASTER_CSV)
        with open(self.MASTER_CSV, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        logger.info("Master report updated at %s", self.MASTER_CSV)
