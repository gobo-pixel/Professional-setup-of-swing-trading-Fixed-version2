"""
AI News Engine.

Responsibilities:
- Clean news
- Remove duplicates
- Extract entities
- Detect events
- Prepare normalized news for sentiment engine

No sentiment scoring.
No BUY/SELL logic.
"""

from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


class AINewsEngine:
    """Clean and normalize raw news."""

    EVENT_KEYWORDS = {
        "MERGER": ["merge", "merger", "acquisition", "acquire"],
        "RESULT": ["quarter", "earnings", "result", "guidance"],
        "DIVIDEND": ["dividend"],
        "BUYBACK": ["buyback"],
        "LITIGATION": ["court", "lawsuit", "litigation"],
        "SEBI": ["sebi"],
        "ORDER": ["order", "contract"],
        "RATING": ["upgrade", "downgrade", "rating"],
    }

    def process(
        self,
        news: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Normalize news items.
        """
        if not news:
            return []

        cleaned: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        for item in news:
            title = str(item.get("title", "")).strip()

            if not title:
                continue

            key = title.lower()

            if key in seen_titles:
                continue

            seen_titles.add(key)

            cleaned.append(
                {
                    "title": title,
                    "publisher": item.get("publisher"),
                    "published_at": item.get("published_at"),
                    "link": item.get("link"),
                    "entities": self._extract_entities(title),
                    "event": self._detect_event(title),
                }
            )

        logger.info("Processed %d news items.", len(cleaned))

        return cleaned

    def _extract_entities(self, text: str) -> list[str]:
        """
        Simple entity extraction based on capitalized words.
        """
        entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]*\b", text)
        return sorted(set(entities))

    def _detect_event(self, text: str) -> str:
        """
        Detect the primary event type.
        """
        lower = text.lower()

        for event, keywords in self.EVENT_KEYWORDS.items():
            if any(keyword in lower for keyword in keywords):
                return event

        return "GENERAL"
