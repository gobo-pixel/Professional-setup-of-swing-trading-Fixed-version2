"""
Watchlist management.

Responsibilities:
- Load watchlist
- Save watchlist
- Validate symbols
- Remove duplicates
"""

from __future__ import annotations

import json
from pathlib import Path

from core.exceptions import ValidationError
from core.logger import get_logger

logger = get_logger(__name__)


class WatchlistManager:
    """Manage watchlist persistence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[str]:
        """Load watchlist from disk."""
        if not self._path.exists():
            logger.warning("Watchlist not found: %s", self._path)
            return []

        with self._path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        if not isinstance(data, list):
            raise ValidationError("Watchlist must be a JSON list.")

        symbols = self._normalize(data)
        logger.info("Loaded %d symbols.", len(symbols))
        return symbols

    def save(self, symbols: list[str]) -> None:
        """Save watchlist to disk."""
        normalized = self._normalize(symbols)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with self._path.open("w", encoding="utf-8") as fp:
            json.dump(normalized, fp, indent=2)

        logger.info("Saved %d symbols.", len(normalized))

    @staticmethod
    def _normalize(symbols: list[str]) -> list[str]:
        """Normalize, validate and deduplicate symbols."""
        cleaned: list[str] = []
        seen: set[str] = set()

        for symbol in symbols:
            if not isinstance(symbol, str):
                raise ValidationError("Symbol must be a string.")

            value = symbol.strip().upper()

            if not value:
                continue

            if value not in seen:
                seen.add(value)
                cleaned.append(value)

        return cleaned
