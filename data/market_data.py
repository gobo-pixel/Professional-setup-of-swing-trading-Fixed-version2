"""
Market data provider.

Responsibilities:
- Download OHLCV market data
- Normalize columns
- Return MarketData records
- No indicator calculations
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Iterable

import pandas as pd
import yfinance as yf

from core.schemas import MarketData
from core.exceptions import DataError
from core.logger import get_logger

logger = get_logger(__name__)


class MarketDataProvider:
    """Fetch and normalize market data."""

    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "1y",
    ) -> pd.DataFrame:
        """Return normalized OHLCV dataframe."""
        try:
            df = yf.download(
                tickers=symbol,
                interval=interval,
                period=period,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            raise DataError(f"Failed to download data for {symbol}") from exc

        if df.empty:
            raise DataError(f"No data returned for {symbol}")

        # Newer yfinance versions return MultiIndex columns
        # (e.g. ("Close", "AAPL")) even for a single ticker. Flatten to the
        # first level ("Close") before doing anything else with the columns.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # The date/datetime index (e.g. named "Date") only becomes a real
        # column after reset_index() — so lowercase AFTER that, not before,
        # or the index-turned-column keeps its original capitalization and
        # the "date"/"datetime" -> "timestamp" rename below silently misses it.
        df = df.reset_index()
        df.columns = [str(c).lower() for c in df.columns]

        df = df.rename(
            columns={
                "date": "timestamp",
                "datetime": "timestamp",
                "index": "timestamp",
            }
        )

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise DataError(f"Missing columns: {missing}")

        if "timestamp" not in df.columns:
            raise DataError(
                f"Could not find a date/timestamp column for {symbol}; "
                f"got columns: {list(df.columns)}"
            )

        df["symbol"] = symbol
        df["timeframe"] = interval

        df = df[
            [
                "timestamp",
                "symbol",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ].copy()

        # ROOT-CAUSE FIX: yfinance can occasionally append an incomplete
        # placeholder row for the current calendar date before that
        # day's actual trading data exists on Yahoo's backend (most
        # common right after a calendar-day rollover, well before NSE
        # opens for the new session) — its OHLC values come back NaN.
        # This affects every symbol identically (a data-provider timing
        # quirk, not a per-symbol data problem), which is exactly what
        # was observed: all monitored positions failing at once with
        # the same "NaN/invalid close price" error.
        #
        # Trim ONLY trailing rows with NaN OHLC (never historical rows —
        # a genuine historical gap is a separate, legitimate data-quality
        # concern already handled by validation elsewhere), falling back
        # to the last genuinely complete trading session.
        ohlc_cols = ["open", "high", "low", "close"]
        trimmed = 0
        while len(df) > 0 and df.iloc[-1][ohlc_cols].isna().any():
            df = df.iloc[:-1]
            trimmed += 1
        if trimmed:
            logger.warning(
                "Trimmed %d trailing incomplete/placeholder row(s) with NaN "
                "OHLC for %s (kept %d valid rows).", trimmed, symbol, len(df),
            )
        if df.empty:
            raise DataError(f"No valid (non-NaN) OHLC data available for {symbol}")

        return df

    def to_schema(self, dataframe: pd.DataFrame) -> list[MarketData]:
        """Convert dataframe into MarketData schema objects."""
        records: list[MarketData] = []

        for row in dataframe.to_dict("records"):
            records.append(
                MarketData(
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    timestamp=pd.to_datetime(row["timestamp"]).to_pydatetime(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

        return records
