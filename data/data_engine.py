"""
Central Data Engine.

Responsibilities:
- Coordinate all data providers
- Return a unified data bundle
- No feature engineering
- No indicators
- No strategy logic
"""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from data.market_data import MarketDataProvider
from data.fundamental_data import FundamentalDataProvider
from data.news_data import NewsDataProvider
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class DataBundle:
    symbol: str
    market: pd.DataFrame
    fundamentals: dict
    news: list[dict]


class DataEngine:
    """Orchestrates all data providers."""

    def __init__(
        self,
        market_provider: MarketDataProvider | None = None,
        fundamental_provider: FundamentalDataProvider | None = None,
        news_provider: NewsDataProvider | None = None,
    ) -> None:
        self.market_provider = market_provider or MarketDataProvider()
        self.fundamental_provider = fundamental_provider or FundamentalDataProvider()
        self.news_provider = news_provider or NewsDataProvider()

    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "1y",
        news_limit: int = 20,
    ) -> DataBundle:
        """
        Fetch all required data for a single symbol.
        """
        logger.info("Loading data for %s", symbol)

        market = self.market_provider.fetch(
            symbol=symbol,
            interval=interval,
            period=period,
        )

        # Fundamentals/news APIs (Yahoo Finance) are flaky — a rate-limit or
        # missing-data hiccup on ONE of them shouldn't drop the whole symbol
        # from the scan. Only market price data (needed for every indicator)
        # is treated as fatal; fundamentals/news degrade gracefully to
        # empty/default so the strategy engines (which already handle
        # missing fundamentals safely) can still evaluate the symbol.
        try:
            fundamentals = self.fundamental_provider.fetch(symbol)
        except Exception as exc:
            logger.warning("Fundamentals unavailable for %s: %s", symbol, exc)
            fundamentals = {}

        try:
            news = self.news_provider.fetch(
                symbol=symbol,
                limit=news_limit,
            )
        except Exception as exc:
            logger.warning("News unavailable for %s: %s", symbol, exc)
            news = []

        logger.info("Completed data load for %s", symbol)

        return DataBundle(
            symbol=symbol,
            market=market,
            fundamentals=fundamentals,
            news=news,
        )
