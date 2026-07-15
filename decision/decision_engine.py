"""
Decision Engine

Institutional Production Version

Responsibilities
----------------
- Merge BUY and SELL engines
- Compare probabilities
- Resolve conflicts
- Generate final AI decision
- Generate confidence
- Generate ranking
- Explain every decision

Consumes

BuyDecision
SellDecision

BuyScore
SellScore

BuyProbability
SellProbability

Produces

BUY
SELL
NO_TRADE

This module DOES NOT execute trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strategy.buy_strategy import BuyDecision
from strategy.sell_strategy import SellDecision

from strategy.buy_scoring import BuyScore
from strategy.sell_scoring import SellScore

from strategy.buy_probability import BuyProbability
from strategy.sell_probability import SellProbability

from core.constants import BUY
from core.constants import SELL
from core.constants import NO_TRADE

from core.logger import get_logger

logger = get_logger(__name__)


# ==========================================================
# RESULT
# ==========================================================


@dataclass(slots=True)
class FinalDecision:

    action: str

    confidence: float

    ranking: float

    buy_score: float

    sell_score: float

    buy_probability: float

    sell_probability: float

    expected_return: float

    expected_drawdown: float

    expected_hold_days: int

    reasons: list[str] = field(default_factory=list)

    diagnostics: dict = field(default_factory=dict)


# ==========================================================
# ENGINE
# ==========================================================


def explanation(probability: Any, score: Any) -> list[str]:
    """
    Build human-readable explanation lines from a Buy/SellProbability and
    its matching Buy/SellScore. Both probability dataclasses expose the
    same shape (a "rate" field, expected_drawdown, expected_hold_days,
    confidence) under slightly different names, so pull whichever is
    present instead of assuming one specific dataclass.
    """
    rate = getattr(probability, "win_probability", None)
    if rate is None:
        rate = getattr(probability, "success_probability", 0.0)

    move = getattr(probability, "expected_return", None)
    if move is None:
        move = getattr(probability, "expected_fall", 0.0)

    lines = [
        f"Estimated probability: {rate:.1f}%",
        f"Expected move: {move:.2f}%",
        f"Expected drawdown risk: {getattr(probability, 'expected_drawdown', 0.0):.2f}%",
        f"Expected holding period: {getattr(probability, 'expected_hold_days', 0)} days",
        f"Probability model confidence: {getattr(probability, 'confidence', 0.0):.1f}%",
        f"Composite score: {getattr(score, 'overall', 0.0):.1f}/100",
    ]
    return lines


class DecisionEngine:
    """
    Central AI Decision Engine

            BUY Engine
                  │
                  ▼
            BUY Score
                  │
                  ▼
        BUY Probability
                  │
                  │
                  ├──────────────┐
                  │              │
                  ▼              ▼
            Decision Engine ◄──── SELL Engine
                  │
                  ▼
            BUY / SELL / NO_TRADE
    """

    BUY_THRESHOLD = 70.0

    SELL_THRESHOLD = 70.0

    MIN_CONFIDENCE = 65.0

    MIN_PROBABILITY = 60.0

    # Combined weighted threshold — replaces the old rigid
    # "score>=70 AND probability>=60 AND confidence>=65" triple-AND gate,
    # where failing just ONE of the three (even by a hair) rejected an
    # otherwise strong trade. A weighted blend lets a very strong score
    # compensate for a slightly-below-bar confidence, and vice versa —
    # "total Probability and Confidence decide, not one failed check."
    COMBINED_THRESHOLD = 65.0

    SCORE_DIFFERENCE = 5.0

    def evaluate(
        self,
        buy_decision: BuyDecision,
        sell_decision: SellDecision,
        buy_score: BuyScore,
        sell_score: SellScore,
        buy_probability: BuyProbability,
        sell_probability: SellProbability,
    ) -> FinalDecision:

        reasons = []

        diagnostics = {}

        logger.info("Starting AI decision engine.")
        # ==========================================================
        # EXTRACT ENGINE OUTPUTS
        # ==========================================================

        buy_signal = buy_decision.passed and buy_decision.action == BUY

        sell_signal = sell_decision.passed and sell_decision.action == SELL

        buy_score_value = float(buy_score.overall)

        sell_score_value = float(sell_score.overall)

        buy_probability_value = float(buy_probability.win_probability)

        sell_probability_value = float(sell_probability.success_probability)

        diagnostics["buy_signal"] = buy_signal

        diagnostics["sell_signal"] = sell_signal

        diagnostics["buy_score"] = buy_score_value

        diagnostics["sell_score"] = sell_score_value

        diagnostics["buy_probability"] = buy_probability_value

        diagnostics["sell_probability"] = sell_probability_value

        # ==========================================================
        # BUY VALIDATION
        # ==========================================================

        buy_combined = (
            buy_score_value * 0.35
            + buy_probability_value * 0.35
            + buy_decision.confidence * 0.30
        )

        diagnostics["buy_combined"] = round(buy_combined, 2)

        buy_valid = buy_signal and buy_combined >= self.COMBINED_THRESHOLD

        diagnostics["buy_valid"] = buy_valid

        if buy_valid:

            reasons.append(f"BUY engine validation passed (combined score {buy_combined:.1f}).")

        else:

            reasons.append(f"BUY engine validation failed (combined score {buy_combined:.1f}, need {self.COMBINED_THRESHOLD:.0f}).")

        # ==========================================================
        # SELL VALIDATION
        # ==========================================================

        sell_combined = (
            sell_score_value * 0.35
            + sell_probability_value * 0.35
            + sell_decision.confidence * 0.30
        )

        diagnostics["sell_combined"] = round(sell_combined, 2)

        sell_valid = sell_signal and sell_combined >= self.COMBINED_THRESHOLD

        diagnostics["sell_valid"] = sell_valid

        if sell_valid:

            reasons.append(f"SELL engine validation passed (combined score {sell_combined:.1f}).")

        else:

            reasons.append(f"SELL engine validation failed (combined score {sell_combined:.1f}, need {self.COMBINED_THRESHOLD:.0f}).")

        # ==========================================================
        # PREPARE METRICS
        # ==========================================================

        buy_strength = buy_score_value * 0.50 + buy_probability_value * 0.50

        sell_strength = sell_score_value * 0.50 + sell_probability_value * 0.50

        diagnostics["buy_strength"] = round(
            buy_strength,
            2,
        )

        diagnostics["sell_strength"] = round(
            sell_strength,
            2,
        )

        reasons.append(f"BUY Strength : {buy_strength:.2f}")

        reasons.append(f"SELL Strength : {sell_strength:.2f}")
        # ==========================================================
        # CONFLICT RESOLUTION
        # ==========================================================

        action = NO_TRADE

        confidence = 0.0

        ranking = 0.0

        expected_return = 0.0

        expected_drawdown = 0.0

        expected_hold_days = 0

        # --------------------------------------------------
        # NO SIGNAL
        # --------------------------------------------------

        if not buy_valid and not sell_valid:

            reasons.append("Neither BUY nor SELL satisfied minimum requirements.")

            action = NO_TRADE

            # Report the stronger side's REAL confidence (not a hard 0) so
            # a rejected trade can still be audited — e.g. "SELL confidence
            # was 41%, needed 58%" is useful; "confidence 0" hides why it
            # was actually rejected.
            confidence = max(buy_decision.confidence, sell_decision.confidence)

            ranking = max(buy_strength, sell_strength)

        # --------------------------------------------------
        # BUY ONLY
        # --------------------------------------------------

        elif buy_valid and not sell_valid:

            action = BUY

            confidence = buy_decision.confidence

            ranking = buy_strength

            expected_return = buy_probability.expected_return

            expected_drawdown = buy_probability.expected_drawdown

            expected_hold_days = buy_probability.expected_hold_days

            reasons.append("BUY engine selected.")

        # --------------------------------------------------
        # SELL ONLY
        # --------------------------------------------------

        elif sell_valid and not buy_valid:

            action = SELL

            confidence = sell_decision.confidence

            ranking = sell_strength

            expected_return = sell_probability.expected_fall

            expected_drawdown = sell_probability.expected_drawdown

            expected_hold_days = sell_probability.expected_hold_days

            reasons.append("SELL engine selected.")

        # --------------------------------------------------
        # BUY vs SELL
        # --------------------------------------------------

        else:

            difference = abs(buy_strength - sell_strength)

            diagnostics["strength_difference"] = round(
                difference,
                2,
            )

            # ----------------------------------------------
            # BUY WINS
            # ----------------------------------------------

            if buy_strength > sell_strength and difference >= self.SCORE_DIFFERENCE:

                action = BUY

                confidence = buy_decision.confidence

                ranking = buy_strength

                expected_return = buy_probability.expected_return

                expected_drawdown = buy_probability.expected_drawdown

                expected_hold_days = buy_probability.expected_hold_days

                reasons.append("BUY engine won conflict resolution.")

            # ----------------------------------------------
            # SELL WINS
            # ----------------------------------------------

            elif sell_strength > buy_strength and difference >= self.SCORE_DIFFERENCE:

                action = SELL

                confidence = sell_decision.confidence

                ranking = sell_strength

                expected_return = sell_probability.expected_fall

                expected_drawdown = sell_probability.expected_drawdown

                expected_hold_days = sell_probability.expected_hold_days

                reasons.append("SELL engine won conflict resolution.")

            # ----------------------------------------------
            # TOO CLOSE
            # ----------------------------------------------

            else:

                action = NO_TRADE

                confidence = max(
                    buy_decision.confidence,
                    sell_decision.confidence,
                )

                ranking = max(
                    buy_strength,
                    sell_strength,
                )

                reasons.append("BUY and SELL signals are too close. Trade rejected.")

                diagnostics["conflict"] = True
        # ==========================================================
        # AI CONFIDENCE REFINEMENT
        # ==========================================================

        if action != NO_TRADE:

            probability = (
                buy_probability.win_probability
                if action == BUY
                else sell_probability.success_probability
            )

            confidence = confidence * 0.60 + probability * 0.40

            confidence = round(
                min(
                    confidence,
                    100.0,
                ),
                2,
            )

        # ==========================================================
        # RANKING NORMALIZATION
        # ==========================================================

        ranking = round(
            max(
                0.0,
                min(
                    ranking,
                    100.0,
                ),
            ),
            2,
        )

        # ==========================================================
        # DECISION QUALITY SCORE
        # ==========================================================

        quality_score = ranking * 0.50 + confidence * 0.50

        quality_score = round(
            quality_score,
            2,
        )

        diagnostics["quality_score"] = quality_score

        # ==========================================================
        # TRADE GRADE
        # ==========================================================

        if action == NO_TRADE:

            trade_grade = "REJECT"

        elif quality_score >= 95:

            trade_grade = "A+"

        elif quality_score >= 90:

            trade_grade = "A"

        elif quality_score >= 80:

            trade_grade = "B+"

        elif quality_score >= 70:

            trade_grade = "B"

        elif quality_score >= 60:

            trade_grade = "C"

        else:

            trade_grade = "REJECT"

        diagnostics["trade_grade"] = trade_grade

        reasons.append(f"Trade Grade : {trade_grade}")

        reasons.append(f"Decision Quality : {quality_score:.2f}")

        # ==========================================================
        # DECISION FLAGS
        # ==========================================================

        diagnostics["final_action"] = action

        diagnostics["ranking"] = ranking

        diagnostics["confidence"] = confidence

        diagnostics["expected_return"] = round(
            expected_return,
            2,
        )

        diagnostics["expected_drawdown"] = round(
            expected_drawdown,
            2,
        )

        diagnostics["expected_hold_days"] = expected_hold_days

        diagnostics["buy_engine_passed"] = buy_valid

        diagnostics["sell_engine_passed"] = sell_valid

        logger.info(
            "Decision=%s | Grade=%s | Rank=%.2f | Confidence=%.2f",
            action,
            trade_grade,
            ranking,
            confidence,
        )
        # ==========================================================
        # AI REASON GENERATOR
        # ==========================================================

        reasons.append("")

        reasons.append("========== AI DECISION ==========")

        if action == BUY:

            reasons.append("Final Action : BUY")

            reasons.append("AI selected BUY after evaluating all engines.")

        elif action == SELL:

            reasons.append("Final Action : SELL")

            reasons.append("AI selected SELL after evaluating all engines.")

        else:

            reasons.append("Final Action : NO_TRADE")

            reasons.append("AI rejected the trade due to insufficient conviction.")

        # ==========================================================
        # BUY / SELL EXPLANATION
        # ==========================================================

        if action == BUY:

            reasons.append("")

            reasons.append("BUY Explanation:")

            reasons.extend(buy_decision.reasons)

            reasons.extend(
                explanation(
                    buy_probability,
                    buy_score,
                )
            )

        elif action == SELL:

            reasons.append("")

            reasons.append("SELL Explanation:")

            reasons.extend(sell_decision.reasons)

            reasons.extend(
                explanation(
                    sell_probability,
                    sell_score,
                )
            )

        # ==========================================================
        # MARKET SUMMARY
        # ==========================================================

        reasons.append("")

        reasons.append(f"BUY Score : {buy_score_value:.2f}")

        reasons.append(f"SELL Score : {sell_score_value:.2f}")

        reasons.append(f"BUY Probability : {buy_probability_value:.2f}%")

        reasons.append(f"SELL Probability : {sell_probability_value:.2f}%")

        reasons.append(f"Ranking : {ranking:.2f}")

        reasons.append(f"Confidence : {confidence:.2f}%")

        # ==========================================================
        # RISK SUMMARY
        # ==========================================================

        reasons.append("")

        reasons.append(f"Expected Return : {expected_return:.2f}%")

        reasons.append(f"Expected Drawdown : {expected_drawdown:.2f}%")

        reasons.append(f"Expected Hold : {expected_hold_days} days")

        reasons.append(f"Trade Grade : {trade_grade}")
        # ==========================================================
        # ENGINE DIAGNOSTICS
        # ==========================================================

        diagnostics["engines"] = {
            "buy": {
                "signal": buy_signal,
                "validated": buy_valid,
                "strategy_confidence": round(
                    buy_decision.confidence,
                    2,
                ),
                "score": round(
                    buy_score_value,
                    2,
                ),
                "probability": round(
                    buy_probability_value,
                    2,
                ),
                "strength": round(
                    buy_strength,
                    2,
                ),
            },
            "sell": {
                "signal": sell_signal,
                "validated": sell_valid,
                "strategy_confidence": round(
                    sell_decision.confidence,
                    2,
                ),
                "score": round(
                    sell_score_value,
                    2,
                ),
                "probability": round(
                    sell_probability_value,
                    2,
                ),
                "strength": round(
                    sell_strength,
                    2,
                ),
            },
        }

        # ==========================================================
        # AI METADATA
        # ==========================================================

        diagnostics["ai"] = {
            "winner": action,
            "ranking": ranking,
            "confidence": confidence,
            "quality_score": quality_score,
            "trade_grade": trade_grade,
            "buy_threshold": self.BUY_THRESHOLD,
            "sell_threshold": self.SELL_THRESHOLD,
            "minimum_probability": self.MIN_PROBABILITY,
            "minimum_confidence": self.MIN_CONFIDENCE,
        }

        # ==========================================================
        # ENGINE COMPARISON
        # ==========================================================

        diagnostics["comparison"] = {
            "score_difference": round(
                buy_score_value - sell_score_value,
                2,
            ),
            "probability_difference": round(
                buy_probability_value - sell_probability_value,
                2,
            ),
            "strength_difference": round(
                buy_strength - sell_strength,
                2,
            ),
        }

        # ==========================================================
        # DECISION SUMMARY
        # ==========================================================

        diagnostics["summary"] = {
            "action": action,
            "ranking": ranking,
            "confidence": confidence,
            "expected_return": round(
                expected_return,
                2,
            ),
            "expected_drawdown": round(
                expected_drawdown,
                2,
            ),
            "expected_hold_days": expected_hold_days,
        }

        logger.info("Decision diagnostics prepared.")
        # ==========================================================
        # FINAL CONSISTENCY VALIDATION
        # ==========================================================

        validation_errors: list[str] = []

        if action not in (BUY, SELL, NO_TRADE):
            validation_errors.append("Invalid action generated.")

        if not (0.0 <= confidence <= 100.0):
            validation_errors.append("Confidence out of range.")

        if not (0.0 <= ranking <= 100.0):
            validation_errors.append("Ranking out of range.")

        if expected_hold_days < 0:
            validation_errors.append("Negative holding period.")

        if expected_drawdown < 0:
            validation_errors.append("Negative drawdown.")

        diagnostics["validation_errors"] = validation_errors

        # --------------------------------------------------
        # FAIL SAFE
        # --------------------------------------------------

        if validation_errors:

            logger.error(
                "Decision validation failed: %s",
                validation_errors,
            )

            reasons.append("Internal validation failed.")

            action = NO_TRADE

            confidence = 0.0

            ranking = 0.0

            expected_return = 0.0

            expected_drawdown = 0.0

            expected_hold_days = 0

            diagnostics["fail_safe"] = True

        else:

            diagnostics["fail_safe"] = False

        # ==========================================================
        # BUILD FINAL OBJECT
        # ==========================================================

        final_decision = FinalDecision(
            action=action,
            confidence=round(
                confidence,
                2,
            ),
            ranking=round(
                ranking,
                2,
            ),
            buy_score=round(
                buy_score_value,
                2,
            ),
            sell_score=round(
                sell_score_value,
                2,
            ),
            buy_probability=round(
                buy_probability_value,
                2,
            ),
            sell_probability=round(
                sell_probability_value,
                2,
            ),
            expected_return=round(
                expected_return,
                2,
            ),
            expected_drawdown=round(
                expected_drawdown,
                2,
            ),
            expected_hold_days=expected_hold_days,
            reasons=reasons,
            diagnostics=diagnostics,
        )

        logger.info("Final decision object created.")

        return final_decision

    # ==========================================================
    # EXPORT
    # ==========================================================

    @staticmethod
    def to_dict(
        decision: FinalDecision,
    ) -> dict:

        return {
            "action": decision.action,
            "confidence": decision.confidence,
            "ranking": decision.ranking,
            "buy_score": decision.buy_score,
            "sell_score": decision.sell_score,
            "buy_probability": decision.buy_probability,
            "sell_probability": decision.sell_probability,
            "expected_return": decision.expected_return,
            "expected_drawdown": decision.expected_drawdown,
            "expected_hold_days": decision.expected_hold_days,
            "reasons": decision.reasons,
            "diagnostics": decision.diagnostics,
        }

    # ==========================================================
    # SUMMARY
    # ==========================================================

    @staticmethod
    def summary(
        decision: FinalDecision,
    ) -> str:

        return (
            f"{decision.action}"
            f" | Rank={decision.ranking:.2f}"
            f" | Confidence={decision.confidence:.2f}%"
            f" | Return={decision.expected_return:.2f}%"
            f" | Drawdown={decision.expected_drawdown:.2f}%"
            f" | Hold={decision.expected_hold_days}d"
        )

    # ==========================================================
    # DEBUG REPORT
    # ==========================================================

    @staticmethod
    def debug_report(
        decision: FinalDecision,
    ) -> str:

        report = []

        report.append("=" * 70)

        report.append("FINAL AI DECISION REPORT")

        report.append("=" * 70)

        report.append("")

        report.append(f"Action               : {decision.action}")

        report.append(f"Confidence           : {decision.confidence:.2f}%")

        report.append(f"Ranking              : {decision.ranking:.2f}")

        report.append(f"BUY Score            : {decision.buy_score:.2f}")

        report.append(f"SELL Score           : {decision.sell_score:.2f}")

        report.append(f"BUY Probability      : {decision.buy_probability:.2f}%")

        report.append(f"SELL Probability     : {decision.sell_probability:.2f}%")

        report.append(f"Expected Return      : {decision.expected_return:.2f}%")

        report.append(f"Expected Drawdown    : {decision.expected_drawdown:.2f}%")

        report.append(f"Expected Hold        : {decision.expected_hold_days} days")

        report.append("")

        report.append("Reasons")

        report.append("-" * 70)

        for reason in decision.reasons:

            report.append(f"• {reason}")

        report.append("")

        report.append("Diagnostics")

        report.append("-" * 70)

        for key, value in sorted(decision.diagnostics.items()):

            report.append(f"{key:<25} : {value}")

        report.append("")

        report.append("=" * 70)

        return "\n".join(report)


# ==========================================================
# END OF FILE
# ==========================================================
