"""
Volatility Indicators.

Responsibilities:
- ATR
- Bollinger Bands
- Keltner Channel
- Donchian Channel

Adds volatility features to the dataframe.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import IndicatorError
from core.logger import get_logger

logger = get_logger(__name__)


class VolatilityIndicators:
    """Volatility indicator engine."""

    def calculate(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            raise IndicatorError("Empty dataframe received.")

        required = {"high", "low", "close"}
        missing = required.difference(dataframe.columns)
        if missing:
            raise IndicatorError(f"Missing required columns: {sorted(missing)}")

        df = dataframe.copy()

        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # ATR(14)
        df["atr_14"] = tr.rolling(14, min_periods=14).mean()

        # Bollinger Bands(20,2)
        sma20 = df["close"].rolling(20, min_periods=20).mean()
        std20 = df["close"].rolling(20, min_periods=20).std()

        df["bb_middle"] = sma20
        df["bb_upper"] = sma20 + (2 * std20)
        df["bb_lower"] = sma20 - (2 * std20)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20

        # Keltner Channel(20)
        ema20 = df["close"].ewm(span=20, adjust=False).mean()
        atr20 = tr.rolling(20, min_periods=20).mean()

        df["kc_middle"] = ema20
        df["kc_upper"] = ema20 + (2 * atr20)
        df["kc_lower"] = ema20 - (2 * atr20)

        # Donchian Channel(20)
        df["dc_upper"] = df["high"].rolling(20, min_periods=20).max()
        df["dc_lower"] = df["low"].rolling(20, min_periods=20).min()
        df["dc_middle"] = (df["dc_upper"] + df["dc_lower"]) / 2

        # Supertrend(10, 3) — required by buy/sell strategy engines.
        st_period = 10
        st_multiplier = 3.0
        st_atr = tr.rolling(st_period, min_periods=st_period).mean()
        hl2 = (df["high"] + df["low"]) / 2
        upperband = hl2 + (st_multiplier * st_atr)
        lowerband = hl2 - (st_multiplier * st_atr)

        supertrend = pd.Series(index=df.index, dtype="float64")
        direction = pd.Series(index=df.index, dtype="bool")  # True = uptrend

        for i in range(len(df)):
            if i == 0 or pd.isna(upperband.iloc[i - 1]):
                direction.iloc[i] = True
                supertrend.iloc[i] = lowerband.iloc[i]
                continue

            prev_supertrend = supertrend.iloc[i - 1]
            close_prev = df["close"].iloc[i - 1]

            curr_upper = (
                upperband.iloc[i]
                if (upperband.iloc[i] < prev_supertrend or close_prev > prev_supertrend)
                else prev_supertrend
            )
            curr_lower = (
                lowerband.iloc[i]
                if (lowerband.iloc[i] > prev_supertrend or close_prev < prev_supertrend)
                else prev_supertrend
            )

            if direction.iloc[i - 1] and df["close"].iloc[i] < curr_lower:
                direction.iloc[i] = False
            elif (not direction.iloc[i - 1]) and df["close"].iloc[i] > curr_upper:
                direction.iloc[i] = True
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            supertrend.iloc[i] = curr_lower if direction.iloc[i] else curr_upper

        # True (uptrend / price above supertrend line) is treated as bullish signal.
        df["supertrend"] = direction

        # Volatility regime state, used by risk + strategy engines.
        atr_ma = df["atr_14"].rolling(20, min_periods=20).mean()
        df["volatility_state"] = "NORMAL"
        df.loc[df["atr_14"] > atr_ma * 1.20, "volatility_state"] = "HIGH"
        df.loc[df["atr_14"] < atr_ma * 0.80, "volatility_state"] = "LOW"

        logger.info("Volatility indicators calculated.")

        return df
