"""
Fundamental data provider.

Responsibilities:
- Fetch company fundamentals
- Normalize values
- No scoring
- No strategy logic
"""

from __future__ import annotations

from typing import Any

import yfinance as yf

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class FundamentalDataProvider:
    """Fetch normalized fundamental metrics."""

    _FIELDS = {
        "marketCap": "market_cap",
        "trailingPE": "pe",
        "priceToBook": "pb",
        "pegRatio": "peg",
        "returnOnEquity": "roe",
        "debtToEquity": "debt_to_equity",
        "earningsGrowth": "earnings_growth",
        "revenueGrowth": "revenue_growth",
        "totalCash": "cash",
        "operatingCashflow": "operating_cashflow",
        "ebitda": "ebitda",
        "bookValue": "book_value",
        "sector": "sector",
        "industry": "industry",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        """
        Fetch normalized fundamental data for a symbol.
        """
        try:
            info = yf.Ticker(symbol).info
        except Exception as exc:
            raise DataError(f"Unable to fetch fundamentals for '{symbol}'.") from exc

        if not info:
            raise DataError(f"No fundamental data available for '{symbol}'.")

        result: dict[str, Any] = {"symbol": symbol}

        for source_key, target_key in self._FIELDS.items():
            result[target_key] = info.get(source_key)

        logger.info("Loaded fundamentals for %s", symbol)

        return result
