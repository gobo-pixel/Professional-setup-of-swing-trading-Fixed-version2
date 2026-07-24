"""
Fundamental data provider.

Responsibilities:
- Fetch company fundamentals
- Normalize values
- No scoring
- No strategy logic
"""

from __future__ import annotations

import time
from typing import Any

import yfinance as yf

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)

_RETRY_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.5

# Standard GICS industry -> sector mapping, used ONLY as a fallback
# when yfinance's own "sector" field is missing but the more granular
# "industry" field IS present. This is a real classification (not a
# guess) — reduces genuine "UNKNOWN" cases without fabricating data.
# Not exhaustive of every possible yfinance industry string, but
# covers the common ones seen across NSE-listed companies.
_INDUSTRY_TO_SECTOR = {
    "oil & gas e&p": "Energy", "oil & gas midstream": "Energy",
    "oil & gas refining & marketing": "Energy", "oil & gas integrated": "Energy",
    "software - infrastructure": "Technology", "software - application": "Technology",
    "information technology services": "Technology", "semiconductors": "Technology",
    "consumer electronics": "Technology", "electronic components": "Technology",
    "banks - regional": "Financial Services", "banks - diversified": "Financial Services",
    "capital markets": "Financial Services", "credit services": "Financial Services",
    "insurance - life": "Financial Services", "insurance - diversified": "Financial Services",
    "asset management": "Financial Services", "mortgage finance": "Financial Services",
    "auto manufacturers": "Consumer Cyclical", "auto parts": "Consumer Cyclical",
    "specialty retail": "Consumer Cyclical", "apparel manufacturing": "Consumer Cyclical",
    "packaging & containers": "Consumer Cyclical", "leisure": "Consumer Cyclical",
    "packaged foods": "Consumer Defensive", "beverages - non-alcoholic": "Consumer Defensive",
    "household & personal products": "Consumer Defensive", "grocery stores": "Consumer Defensive",
    "tobacco": "Consumer Defensive", "farm products": "Consumer Defensive",
    "drug manufacturers - general": "Healthcare", "drug manufacturers - specialty & generic": "Healthcare",
    "biotechnology": "Healthcare", "diagnostics & research": "Healthcare",
    "medical devices": "Healthcare", "medical care facilities": "Healthcare",
    "engineering & construction": "Industrials", "specialty industrial machinery": "Industrials",
    "railroads": "Industrials", "aerospace & defense": "Industrials",
    "conglomerates": "Industrials", "electrical equipment & parts": "Industrials",
    "utilities - regulated electric": "Utilities", "utilities - renewable": "Utilities",
    "utilities - diversified": "Utilities",
    "steel": "Basic Materials", "copper": "Basic Materials", "chemicals": "Basic Materials",
    "specialty chemicals": "Basic Materials", "agricultural inputs": "Basic Materials",
    "real estate - development": "Real Estate", "real estate services": "Real Estate",
    "reit - diversified": "Real Estate",
    "telecom services": "Communication Services", "entertainment": "Communication Services",
}


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
        info = None
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                info = yf.Ticker(symbol).info
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _RETRY_ATTEMPTS:
                    logger.warning(
                        "Fundamentals fetch attempt %d/%d failed for %s: %s — retrying.",
                        attempt, _RETRY_ATTEMPTS, symbol, exc,
                    )
                    time.sleep(_RETRY_DELAY_SECONDS)
        if info is None:
            raise DataError(f"Unable to fetch fundamentals for '{symbol}'.") from last_exc

        if not info:
            raise DataError(f"No fundamental data available for '{symbol}'.")

        result: dict[str, Any] = {"symbol": symbol}

        for source_key, target_key in self._FIELDS.items():
            result[target_key] = info.get(source_key)

        # Industry-based sector fallback — only when yfinance's own
        # "sector" is genuinely missing but "industry" is present.
        if not result.get("sector") and result.get("industry"):
            inferred = _INDUSTRY_TO_SECTOR.get(str(result["industry"]).strip().lower())
            if inferred:
                result["sector"] = inferred
                logger.info(
                    "Sector missing for %s — inferred '%s' from industry '%s'.",
                    symbol, inferred, result["industry"],
                )

        if not result.get("sector"):
            logger.warning(
                "No sector could be determined for %s (yfinance sector/industry both "
                "missing or unmapped) — will fall back to UNKNOWN downstream.", symbol,
            )

        logger.info("Loaded fundamentals for %s", symbol)

        return result
