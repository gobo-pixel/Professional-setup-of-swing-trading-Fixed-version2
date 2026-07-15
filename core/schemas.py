"""
Core data schemas shared across the Quant Trading Platform.

Rules:
- No business logic
- Immutable where possible
- Used by all modules
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .types import FeatureMap, ReasonList, Signal


@dataclass(slots=True, frozen=True)
class MarketData:
    """
    Normalized market data for a single symbol.
    """

    symbol: str
    timeframe: str
    timestamp: datetime

    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class FeatureSet:
    """
    Calculated technical/fundamental features.

    Example:
        EMA20
        RSI14
        MACD
        ATR
        ADX
        VWAP
        Ichimoku...
    """

    symbol: str
    timeframe: str
    values: FeatureMap = field(default_factory=dict)


@dataclass(slots=True)
class MarketContext:
    """
    Overall market environment.
    """

    regime: str
    sector: str
    volatility: str
    sentiment: str


@dataclass(slots=True)
class TradeSignal:
    """
    Output from Decision Engine.
    """

    symbol: str

    signal: Signal

    confidence: float

    score: float

    expected_return: float

    expected_hold_days: int

    reasons: ReasonList = field(default_factory=list)


@dataclass(slots=True)
class Position:
    """
    Active position.
    """

    symbol: str

    quantity: int

    entry_price: float

    current_price: float

    stop_loss: float

    target: float

    signal: Signal


@dataclass(slots=True)
class PortfolioState:
    """
    Portfolio snapshot.
    """

    capital: float

    cash: float

    invested: float

    open_positions: list[Position] = field(default_factory=list)


@dataclass(slots=True)
class ScanResult:
    """
    Complete output of scanner.
    """

    timestamp: datetime

    signals: list[TradeSignal] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
