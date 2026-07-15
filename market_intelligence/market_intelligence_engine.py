"""
MARKET INTELLIGENCE ENGINE

Completely independent from the production trading strategy. This is
NOT part of the Decision Engine and NEVER generates BUY, SELL, or EXIT
signals — it never calls the scanner, Entry Engine, or Exit Engine, and
never modifies the Virtual Portfolio, Trade Diary, or any probability.

Purpose: research, monitoring, and early warning ONLY.

    News / Macro / Results / Global Events
        |
    Research (this module)
        |
    Telegram Alert (advisory text only, via core.notifications)
        |
    Human review — the human (or the existing Exit Engine, on its own
    separate schedule) decides what, if anything, to do about it.

Everything this engine observes is stored to
storage/reports/market_intelligence_log.jsonl for the Analysis/Learning/
Optimizer modules to consume later — it does not feed back into today's
trading decisions directly.

Reuses existing infrastructure rather than duplicating it:
    - market/macro_intelligence.py's sector_bias() for theme detection
    - data/news_data.py for news fetching (same provider as the scanner)
    - news/sentiment_engine.py for sentiment scoring
    - core/notifications.py for severity classification + dedup + sending
      (the SAME shared helper every other module uses — no separate copy)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.notifications import notify, severity_from_magnitude
from core.trading_calendar import now_ist
from data.news_data import NewsDataProvider
from market import macro_intelligence
from news.sentiment_engine import SentimentEngine

logger = get_logger(__name__)

LOG_PATH = "storage/reports/market_intelligence_log.jsonl"

# Sector impact themes reused as-is from market/macro_intelligence.py —
# NOT reimplemented here (see that module for the full theme table).
MACRO_KEYWORDS = [kw for keywords, _ in macro_intelligence.THEMES for kw in keywords]

# Thresholds for "is this significant enough to alert on" — advisory
# only, tune freely without touching any production trading threshold.
NEWS_ALERT_THRESHOLD = 0.5   # |signed bias| beyond this is "significant"
SENTIMENT_SCORE_NEUTRAL = 50.0


def _signed_bias(scored_item: dict[str, Any]) -> float:
    """
    SentimentEngine.evaluate() returns an UNSIGNED 0-100 magnitude in
    "impact_score" (50=weak/neutral, 100=strong) plus a separate polarity
    string in "sentiment" (POSITIVE/NEGATIVE/NEUTRAL) — it does not encode
    direction as a signed number itself. This converts the pair into a
    single signed bias in roughly [-1, +1] for this engine's own use.
    """
    impact = float(scored_item.get("impact_score", 50.0))
    magnitude = max(0.0, (impact - 50.0) / 50.0)  # 0 (neutral) .. 1 (max)
    polarity = scored_item.get("sentiment", "NEUTRAL")
    if polarity == "POSITIVE":
        return magnitude
    if polarity == "NEGATIVE":
        return -magnitude
    return 0.0


class MarketIntelligenceEngine:
    """
    Research-only. Call run() once per scheduled run with the list of
    currently open positions (symbol + direction) — it never reads or
    writes the Virtual Portfolio/Trade Diary itself, keeping it
    decoupled; the caller supplies the position list.
    """

    def __init__(
        self,
        news_provider: NewsDataProvider | None = None,
        sentiment_engine: SentimentEngine | None = None,
    ):
        self.news_provider = news_provider or NewsDataProvider()
        self.sentiment_engine = sentiment_engine or SentimentEngine()

    # ==========================================================
    # MAIN ENTRY POINT
    # ==========================================================

    def run(self, open_positions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        open_positions: [{"symbol": "INFY.NS", "direction": "BUY", "sector": "IT"}, ...]
        Read-only input — this engine never mutates portfolio state.
        """
        ist_now = now_ist()
        notify(
            event_type="market_intelligence_started",
            message=(
                f"🧠 Market Intelligence Started\n"
                f"Time (IST): {ist_now.strftime('%H:%M:%S')}\n"
                f"Monitoring Window\n"
                f"Checking:\n"
                f"• Company News\n"
                f"• Company Results\n"
                f"• Exchange Announcements\n"
                f"• Global Markets\n"
                f"• Macro Events\n"
                f"• Sector News\n"
                f"This is an advisory-only research cycle.\n"
                f"No trading decisions will be made."
            ),
            # Timestamp-precision dedup key (not date-only) — this cycle
            # runs 6x/day, and each of those 6 runs should get its own
            # start notification, not be suppressed as a "duplicate" of
            # an earlier run from the same day.
            dedup_key=f"mi_started::{ist_now.strftime('%Y-%m-%d %H:%M:%S.%f')}",
        )

        macro_headlines = self._safe_fetch_market_news()
        macro_observation = self._analyze_macro(macro_headlines)

        position_observations = []
        alerts_sent = []
        for pos in open_positions:
            obs = self._analyze_position(pos, macro_headlines)
            position_observations.append(obs)
            if obs["alert_triggered"]:
                sent = notify(
                    event_type="market_intelligence",
                    message=obs["alert_body"],
                    severity=obs["severity"],
                    dedup_key=obs["signature"],
                )
                if sent:
                    alerts_sent.append(obs["alert_body"])

        record = {
            "timestamp": time.time(),
            "macro": macro_observation,
            "positions": position_observations,
            "alerts_sent": alerts_sent,
        }
        self._store(record)
        logger.info(
            "Market Intelligence run complete: %d positions checked, %d alerts sent.",
            len(open_positions), len(alerts_sent),
        )
        return record

    # ==========================================================
    # MACRO ANALYSIS (research only — no signals)
    # ==========================================================

    def _safe_fetch_market_news(self) -> list[str]:
        try:
            return self.news_provider.fetch_market_news()
        except Exception as exc:
            logger.warning("Market news fetch failed: %s", exc)
            return []

    def _analyze_macro(self, headlines: list[str]) -> dict[str, Any]:
        text = " ".join(h.lower() for h in headlines)
        critical_events = [kw for kw in MACRO_KEYWORDS if kw in text]

        macro_risk_score = min(100.0, len(critical_events) * 20.0)

        scored = self.sentiment_engine.evaluate([{"title": h} for h in headlines]) if headlines else []
        if scored:
            avg_bias = sum(_signed_bias(s) for s in scored) / len(scored)
            sentiment_score = max(0.0, min(100.0, SENTIMENT_SCORE_NEUTRAL + avg_bias * 50.0))
        else:
            sentiment_score = SENTIMENT_SCORE_NEUTRAL

        if macro_risk_score >= 60:
            global_risk_level = "HIGH"
        elif macro_risk_score >= 30:
            global_risk_level = "MEDIUM"
        else:
            global_risk_level = "LOW"

        return {
            "overall_market_sentiment_score": round(sentiment_score, 2),
            "macro_risk_score": round(macro_risk_score, 2),
            "global_risk_level": global_risk_level,
            "critical_events": critical_events,
            "headlines_seen": len(headlines),
        }

    # ==========================================================
    # PER-POSITION RESEARCH (advisory only)
    # ==========================================================

    def _analyze_position(self, position: dict[str, Any], macro_headlines: list[str]) -> dict[str, Any]:
        symbol = position["symbol"]
        direction = position.get("direction", "BUY")
        sector = position.get("sector")

        try:
            company_news = self.news_provider.fetch(symbol=symbol, limit=10)
        except Exception as exc:
            logger.warning("Company news fetch failed for %s: %s", symbol, exc)
            company_news = []

        scored_news = self.sentiment_engine.evaluate(company_news) if company_news else []
        avg_impact = (
            sum(_signed_bias(n) for n in scored_news) / len(scored_news)
            if scored_news else 0.0
        )
        top_headline = ""
        if scored_news:
            top_headline = max(scored_news, key=lambda n: abs(_signed_bias(n))).get("title", "")

        macro_bias = macro_intelligence.sector_bias(macro_headlines, sector) if sector else 0.0

        alert_triggered = False
        alert_body = None
        signature = None
        severity = None

        adverse_signal = -avg_impact if direction == "BUY" else avg_impact
        adverse_macro = -macro_bias if direction == "BUY" else macro_bias

        if avg_impact != 0.0 and abs(avg_impact) >= NEWS_ALERT_THRESHOLD and adverse_signal > 0:
            polarity = "Negative" if direction == "BUY" else "Positive"
            signature = f"news::{symbol}::{top_headline}"
            alert_triggered = True
            severity = severity_from_magnitude(avg_impact)
            alert_body = (
                f"{polarity} news detected for {symbol}"
                + (f": {top_headline}" if top_headline else ".") + "\n"
                f"You currently hold a {direction} position.\n"
                f"Please review this position.\n"
                f"No automatic action has been taken."
            )
        elif macro_bias != 0.0 and abs(macro_bias) >= 0.3 and adverse_macro > 0 and sector:
            signature = f"macro::{sector}::{symbol}"
            alert_triggered = True
            severity = severity_from_magnitude(macro_bias)
            alert_body = (
                f"Macro development detected affecting the {sector} sector.\n"
                f"This may affect your {direction} position in {symbol}.\n"
                f"No automatic action has been taken."
            )

        return {
            "symbol": symbol,
            "direction": direction,
            "sector": sector,
            "news_impact_score": round(avg_impact, 3),
            "macro_bias": macro_bias,
            "alert_triggered": alert_triggered,
            "alert_body": alert_body,
            "severity": severity,
            "signature": signature,
        }

    # ==========================================================
    # STORAGE (for future Analysis/Learning/Optimizer consumption)
    # ==========================================================

    def _store(self, record: dict[str, Any]) -> None:
        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
