"""
News data provider.

Responsibilities:
- Fetch raw news headlines
- Normalize output
- No sentiment analysis
- No AI/event detection
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import yfinance as yf

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class NewsDataProvider:
    """Fetch raw company news."""

    def fetch(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        Fetch recent news for a symbol.

        Returns:
            List of normalized news dictionaries.
        """
        try:
            news = yf.Ticker(symbol).news
        except Exception as exc:
            raise DataError(f"Unable to fetch news for '{symbol}'.") from exc

        if not news:
            logger.warning("No news found for %s", symbol)
            return []

        results: list[dict[str, Any]] = []

        for item in news[:limit]:
            ts = item.get("providerPublishTime")
            published = (
                datetime.fromtimestamp(ts).isoformat()
                if isinstance(ts, (int, float))
                else None
            )

            results.append(
                {
                    "symbol": symbol,
                    "title": item.get("title"),
                    "publisher": item.get("publisher"),
                    "published_at": published,
                    "link": item.get("link"),
                    "type": item.get("type"),
                    "uuid": item.get("uuid"),
                }
            )

        logger.info("Loaded %d news items for %s", len(results), symbol)
        return results

    def fetch_market_news(self, limit: int = 20) -> list[str]:
        """
        Fetch broad market/macro headlines (not company-specific) — used
        by market/macro_intelligence.py to detect macro themes (wars, oil
        supply shocks, rate decisions, etc.) that individual per-company
        news wouldn't reliably surface. Uses the Nifty 50 index ticker as
        a proxy source of macro-market headlines.
        """
        try:
            news = yf.Ticker("^NSEI").news
        except Exception as exc:
            logger.warning("Unable to fetch market news: %s", exc)
            return []

        if not news:
            return []

        return [item.get("title", "") for item in news[:limit] if item.get("title")]
