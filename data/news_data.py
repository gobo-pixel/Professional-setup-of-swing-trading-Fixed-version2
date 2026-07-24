"""
News data provider.

Responsibilities:
- Fetch raw news headlines
- Normalize output
- No sentiment analysis
- No AI/event detection
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yfinance as yf

from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)

# Broad-market index tickers used as macro-headline sources. Using more
# than one avoids a single-point-of-failure: if one index's news feed
# is sparse/empty on a given fetch, the others can still surface real
# macro headlines instead of the whole macro-risk check going blind.
MACRO_NEWS_SOURCES = ["^NSEI", "^BSESN"]

# How many attempts (including the first) before giving up on a fetch.
_RETRY_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.5

MACRO_CACHE_PATH = "storage/reports/macro_headlines_cache.json"


def _fetch_ticker_news_with_retry(ticker_symbol: str) -> list[dict[str, Any]] | None:
    """Fetch .news for one ticker, retrying on transient failures.
    Returns None only if every attempt failed with an exception —
    an empty (but successful) result returns [] as normal."""
    last_exc: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return yf.Ticker(ticker_symbol).news
        except Exception as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS:
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s — retrying.",
                    attempt, _RETRY_ATTEMPTS, ticker_symbol, exc,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
    logger.warning("All %d fetch attempts failed for %s: %s", _RETRY_ATTEMPTS, ticker_symbol, last_exc)
    return None


class NewsDataProvider:
    """Fetch raw company news."""

    def fetch(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        Fetch recent news for a symbol.

        Returns:
            List of normalized news dictionaries.
        """
        news = _fetch_ticker_news_with_retry(symbol)
        if news is None:
            raise DataError(f"Unable to fetch news for '{symbol}'.")

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
        news wouldn't reliably surface.

        Resilience (this fetch affects EVERY open position's macro-risk
        check in one shot, so a gap here is high-impact):
        - Queries multiple broad-market index tickers (MACRO_NEWS_SOURCES),
          not just one, and combines whatever each source returns.
        - Retries each source on transient failure.
        - If every source comes back genuinely empty, falls back to the
          last successfully-fetched non-empty headline set (cached on
          disk) rather than silently treating it as "no macro risk" —
          yesterday's macro headlines are usually still relevant, not
          instantly stale.
        """
        combined: list[str] = []
        any_source_had_content = False

        for source in MACRO_NEWS_SOURCES:
            news = _fetch_ticker_news_with_retry(source)
            if news is None:
                continue  # this source failed entirely, try the next
            if not news:
                logger.warning("Market news fetch for %s returned 0 headlines.", source)
                continue
            titles = [item.get("title", "") for item in news[:limit] if item.get("title")]
            if titles:
                any_source_had_content = True
                combined.extend(titles)
                logger.info("Loaded %d market/macro headlines from %s.", len(titles), source)

        # De-duplicate while preserving order (different indices often
        # surface the same broad-market headline).
        seen = set()
        deduped = []
        for title in combined:
            if title not in seen:
                seen.add(title)
                deduped.append(title)
        deduped = deduped[:limit]

        if deduped:
            self._save_macro_cache(deduped)
            return deduped

        if not any_source_had_content:
            logger.warning(
                "All macro news sources (%s) returned 0 headlines this run — "
                "falling back to last known-good cached headlines if available.",
                ", ".join(MACRO_NEWS_SOURCES),
            )
        cached = self._load_macro_cache()
        if cached:
            logger.warning(
                "Using %d cached macro headline(s) from a previous successful "
                "fetch (today's live fetch was empty).", len(cached),
            )
            return cached

        logger.warning("No live or cached macro headlines available — macro risk analysis sees an empty list.")
        return []

    @staticmethod
    def _save_macro_cache(headlines: list[str]) -> None:
        try:
            Path(MACRO_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(MACRO_CACHE_PATH, "w") as f:
                json.dump({"headlines": headlines, "fetched_at": time.time()}, f)
        except OSError as exc:
            logger.warning("Could not write macro headline cache: %s", exc)

    @staticmethod
    def _load_macro_cache() -> list[str]:
        try:
            with open(MACRO_CACHE_PATH) as f:
                data = json.load(f)
            return data.get("headlines", [])
        except (OSError, json.JSONDecodeError):
            return []
