"""
Application-wide constants.

Do not place configurable values here.
Only immutable constants shared across the project.
"""

from __future__ import annotations

from typing import Final

APP_NAME: Final[str] = "Quant Trading Platform"
APP_VERSION: Final[str] = "1.0.0"

BUY: Final[str] = "BUY"
SELL: Final[str] = "SELL"
NO_TRADE: Final[str] = "NO_TRADE"

VALID_SIGNALS: Final[tuple[str, ...]] = (
    BUY,
    SELL,
    NO_TRADE,
)

LONG: Final[str] = "LONG"
SHORT: Final[str] = "SHORT"

NSE: Final[str] = "NSE"
BSE: Final[str] = "BSE"

DATE_FORMAT: Final[str] = "%Y-%m-%d"
DATETIME_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

DEFAULT_FLOAT_PRECISION: Final[int] = 4

LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)s | %(name)s | " "%(filename)s:%(lineno)d | %(message)s"
)
