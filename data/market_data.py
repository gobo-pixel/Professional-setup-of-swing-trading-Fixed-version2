"""
Market data provider.

Responsibilities:
- Download OHLCV market data
- Normalize columns
- Return MarketData records
- No indicator calculations
"""

from __future__ import annotations

import time
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
        # Evidence from production: isolated single-symbol fetches
        # reliably return ~273 rows (well above the 250-row validation
        # threshold), but the SAME symbols fail "Insufficient historical
        # candles" when scanned as part of a long, continuous 500-symbol
        # Daily Scan — strongly suggesting Yahoo Finance silently
        # throttles/returns fewer rows under sustained request volume,
        # without raising an exception. Retry once specifically when
        # the row count comes back suspiciously low, rather than
        # blanket-delaying every single fetch (which would make a
        # 500-symbol scan far slower for no benefit in the common case).
        _MIN_EXPECTED_ROWS = 260
        _ROW_COUNT_RETRY_DELAY_SECONDS = 3.0

        for attempt in range(1, 3):
            df = self._download(symbol, interval, period)
            if len(df) >= _MIN_EXPECTED_ROWS or period != "1y" or interval != "1d":
                break
            if attempt == 1:
                logger.warning(
                    "%s returned only %d rows (expected ~273+) — likely transient "
                    "throttling, retrying once after a short delay.", symbol, len(df),
                )
                time.sleep(_ROW_COUNT_RETRY_DELAY_SECONDS)

        return self._normalize(df, symbol, interval)

    def _download(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        """Raw yf.download() call only — kept separate from _normalize()
        so fetch()'s retry loop can check the raw row count before
        spending time on normalization."""
        try:
            if period == "1y" and interval == "1d":
                # period="1y" yields EXACTLY ~250 trading days, which
                # sits right at validation_engine.py's minimum_history
                # threshold (>= 250). After the trailing-NaN-row trim
                # below removes even ONE row, every fetch would land at
                # 249 and universally fail "Insufficient historical
                # candles" — this is exactly what happened in
                # production. Fetch a genuine buffer of extra calendar
                # days instead, so trimming has margin without ever
                # touching the validation threshold itself.
                #
                # CONFIRMED BUG (found via user-reported price mismatch
                # against Zerodha/Google, cross-checked at the same
                # closed-market moment): yfinance's `end` parameter is
                # EXCLUSIVE — end="2026-08-03" returns data only THROUGH
                # 2026-08-02, even though that day's own session has
                # already closed by the time this runs (scan runs at
                # 23:30 IST, hours after the 15:30 IST close). This made
                # "latest_close" silently one trading day stale, always.
                # Adding one day makes the exclusive boundary genuinely
                # include today's already-closed session.
                end = datetime.now() + pd.Timedelta(days=1)
                start = end - pd.Timedelta(days=400)
                df = yf.download(
                    tickers=symbol,
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
            else:
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
        return df

    def _normalize(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
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
