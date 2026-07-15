from core.logger import get_logger

logger = get_logger(__name__)


class ReasonGenerator:

    def generate(self, decision: dict, signals: dict, risk: dict, market: dict) -> dict:

        reasons = []

        # SIGNAL REASONING

        if signals.get("buy_strength", 0) > 0.7:

            reasons.append("Strong buy signal detected")

        if signals.get("sell_strength", 0) > 0.7:

            reasons.append("Strong sell signal detected")

        # RISK REASONING

        if risk.get("grade") == "A":

            reasons.append("Low risk environment")

        elif risk.get("grade") in ["D", "F"]:

            reasons.append("High risk environment - caution applied")

        # MARKET CONTEXT

        if market.get("trend") == "BULLISH":

            reasons.append("Market trend is bullish")

        elif market.get("trend") == "BEARISH":

            reasons.append("Market trend is bearish")

        # FINAL DECISION EXPLANATION

        explanation = {
            "decision": decision.get("action"),
            "confidence": decision.get("confidence", 0),
            "reasons": reasons,
        }

        logger.info(f"Decision Explanation Generated: {explanation}")

        return explanation
