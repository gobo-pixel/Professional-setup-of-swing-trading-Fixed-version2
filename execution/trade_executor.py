import time
from core.logger import get_logger

logger = get_logger(__name__)


class TradeExecutor:

    def __init__(self, broker, risk_manager):

        self.broker = broker

        self.risk_manager = risk_manager

        self.executed_ids = set()

    def execute(self, orders, portfolio):

        results = []

        for order in orders:

            # prevent duplicate execution

            if order.get("id") in self.executed_ids:

                continue

            start = time.time()

            risk = self.risk_manager.evaluate_order(order, portfolio)

            if not risk.get("approved"):

                continue

            try:

                result = self.broker.place_order(order)

                latency = time.time() - start

                self.executed_ids.add(order.get("id"))

                results.append(
                    {
                        "order": order,
                        "status": "EXECUTED",
                        "latency": latency,
                        "result": result,
                    }
                )

            except Exception as e:

                logger.error(f"EXECUTION FAILED: {e}")

        return results
