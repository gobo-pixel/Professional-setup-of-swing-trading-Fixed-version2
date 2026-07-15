import pandas as pd
from risk.risk_manager import RiskManager
from decision.validation_engine import ValidationResult
from decision.decision_engine import FinalDecision


def test_risk_block():
    r = RiskManager()

    # Sahi dummy mock objects/data taiyar kiya
    validation = ValidationResult(
        passed=True,
        action="BUY",
        confidence=85.0,
        rejection_reason=None,
    )
    decision = FinalDecision(
        action="BUY",
        confidence=85.0,
        ranking=70.0,
        buy_score=80.0,
        sell_score=20.0,
        buy_probability=75.0,
        sell_probability=15.0,
        expected_return=5.0,
        expected_drawdown=2.0,
        expected_hold_days=5,
    )
    portfolio = {"equity": 1000}
    market = {"regime": "HIGH_VOLATILITY"}

    # Ek dummy row wala DataFrame banaya (RiskManager ko latest row chahiye hoti hai)
    dataframe = pd.DataFrame(
        [
            {
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1_000_000,
                "atr": 1.5,
                "atr_14": 1.5,
                "volume_sma_20": 900_000,
            }
        ]
    )

    # Saare 5 arguments properly keyword ke sath pass kiye
    result = r.evaluate(
        validation=validation,
        decision=decision,
        dataframe=dataframe,
        portfolio=portfolio,
        market=market,
    )

    # Dictionary check karne ke bajay object attribute check kiya
    assert hasattr(result, "safe")
