"""
Common type aliases used across the Quant Trading Platform.

This module must remain free of business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping, MutableMapping, Sequence, TypeAlias

# ----- Trading -----

Signal: TypeAlias = Literal["BUY", "SELL", "NO_TRADE"]
PositionSide: TypeAlias = Literal["LONG", "SHORT"]
MarketName: TypeAlias = Literal["NSE", "BSE"]

# ----- Generic containers -----

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]

ConfigDict: TypeAlias = Mapping[str, Any]
MutableConfigDict: TypeAlias = MutableMapping[str, Any]

# ----- Data -----

Symbol: TypeAlias = str
SymbolList: TypeAlias = Sequence[Symbol]

Price: TypeAlias = float
Volume: TypeAlias = int | float
Timestamp: TypeAlias = str

FeatureMap: TypeAlias = Mapping[str, float]
MetricMap: TypeAlias = Mapping[str, float]

# ----- Paths -----

PathLike: TypeAlias = str | Path

# ----- Results -----

ReasonList: TypeAlias = list[str]
