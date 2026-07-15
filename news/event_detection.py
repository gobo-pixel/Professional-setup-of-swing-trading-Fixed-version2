"""
Event Detection Engine.

Responsibilities:
- Detect important market events from normalized news
- Assign severity
- Normalize event structure

No sentiment analysis.
No BUY/SELL logic.
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)


class EventDetectionEngine:
    """Detect structured events from news."""

    EVENT_MAP = {
        "MERGER": ["merger", "merge", "acquisition", "acquire"],
        "RESULT": ["result", "earnings", "quarter", "guidance"],
        "DIVIDEND": ["dividend"],
        "BUYBACK": ["buyback"],
        "ORDER": ["order", "contract"],
        "SEBI": ["sebi"],
        "LITIGATION": ["litigation", "lawsuit", "court"],
        "RATING_UPGRADE": ["upgrade"],
        "RATING_DOWNGRADE": ["downgrade"],
    }

    SEVERITY = {
        "MERGER": 90,
        "BUYBACK": 85,
        "RESULT": 75,
        "ORDER": 70,
        "DIVIDEND": 60,
        "RATING_UPGRADE": 65,
        "RATING_DOWNGRADE": 65,
        "SEBI": 95,
        "LITIGATION": 90,
        "GENERAL": 25,
    }

    def detect(self, news: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        for item in news:
            title = str(item.get("title", ""))
            event = self._event_type(title)

            events.append(
                {
                    **item,
                    "event_type": event,
                    "severity": self.SEVERITY[event],
                }
            )

        logger.info("Detected %d events.", len(events))
        return events

    def _event_type(self, title: str) -> str:
        text = title.lower()

        for event, keywords in self.EVENT_MAP.items():
            if any(word in text for word in keywords):
                return event

        return "GENERAL"
