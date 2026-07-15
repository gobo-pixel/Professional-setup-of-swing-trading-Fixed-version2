from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)


class Dashboard:

    def __init__(self):

        self.latest_state = {}

    def update(self, data: dict[str, Any]):

        self.latest_state = data

        logger.info("Dashboard updated")

    def get_snapshot(self) -> dict[str, Any]:

        return self.latest_state

    def render_summary(self):

        print("\n===== SYSTEM DASHBOARD =====")

        for k, v in self.latest_state.items():

            print(f"{k}: {v}")

        print("===========================\n")
