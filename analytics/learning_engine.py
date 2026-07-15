"""
PHASE 2 — MODULE 2: LEARNING ENGINE (observation only)

Reads closed trades (storage/trades/trades_master.csv) plus the scan
history (reports/full_report.csv) and records — historically, append-only
— which rules/sectors/regimes/news/fundamentals correlate with winning vs
losing trades.

This module NEVER changes strategy parameters. It only observes and
stores observations for analytics/optimizer.py to later turn into
recommendations (which a human still has to approve and apply manually).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from core.notifications import notify
from storage.trades.trade_store import TradeStore


class LearningEngine:

    OBSERVATIONS_PATH = "storage/reports/learning_observations.jsonl"

    def __init__(self, trade_store: TradeStore | None = None, report_path: str = "reports/full_report.csv"):
        self.trade_store = trade_store or TradeStore()
        self.report_path = report_path

    def _load_report_rows(self) -> list[dict[str, Any]]:
        path = Path(self.report_path)
        if not path.exists():
            return []
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    def observe(self) -> dict[str, Any]:
        """Run one observation pass over closed trades and store the
        result (append-only, historical — never overwrites prior runs)."""
        closed = self.trade_store.get_closed_trades()
        report_rows = self._load_report_rows()
        report_by_symbol = {r.get("Stock"): r for r in report_rows}

        observation = {
            "timestamp": time.time(),
            "closed_trades_observed": len(closed),
            "sector_performance": self._sector_performance(closed, report_by_symbol),
            "regime_performance": self._regime_performance(closed, report_by_symbol),
            "news_effectiveness": self._news_effectiveness(closed, report_by_symbol),
            "fundamental_effectiveness": self._fundamental_effectiveness(closed, report_by_symbol),
            "technical_effectiveness": self._technical_effectiveness(closed, report_by_symbol),
            "buy_accuracy": self._accuracy(closed, "BUY"),
            "sell_accuracy": self._accuracy(closed, "SELL"),
        }

        self._append_observation(observation)

        if observation["closed_trades_observed"] > 0:
            notify(
                event_type="learning_summary",
                message=(
                    f"Learning Summary — {observation['closed_trades_observed']} closed trades observed.\n"
                    f"BUY accuracy: {observation['buy_accuracy']}\n"
                    f"SELL accuracy: {observation['sell_accuracy']}"
                ),
                dedup_key=f"learning_summary::{time.strftime('%Y-%m-%d')}",
            )

        return observation

    def _accuracy(self, closed: list[dict], direction: str) -> dict[str, Any]:
        trades = [t for t in closed if t.get("direction") == direction and t.get("status") == "CLOSED"]
        if not trades:
            return {"trades": 0, "win_rate": None}
        wins = sum(1 for t in trades if self._pnl(t) > 0)
        return {"trades": len(trades), "win_rate": round(wins / len(trades) * 100, 2)}

    def _sector_performance(self, closed, report_by_symbol) -> dict[str, Any]:
        by_sector: dict[str, list[float]] = {}
        for t in closed:
            r = report_by_symbol.get(t.get("symbol"))
            sector = r.get("Sector") if r else None
            if not sector:
                continue
            by_sector.setdefault(sector, []).append(self._pnl(t))
        return {
            sector: {"trades": len(pnls), "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 2)}
            for sector, pnls in by_sector.items()
        }

    def _regime_performance(self, closed, report_by_symbol) -> dict[str, Any]:
        by_regime: dict[str, list[float]] = {}
        for t in closed:
            regime = t.get("regime")
            if not regime:
                continue
            by_regime.setdefault(regime, []).append(self._pnl(t))
        return {
            regime: {"trades": len(pnls), "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 2)}
            for regime, pnls in by_regime.items()
        }

    def _news_effectiveness(self, closed, report_by_symbol) -> dict[str, Any]:
        with_news, without_news = [], []
        for t in closed:
            r = report_by_symbol.get(t.get("symbol"))
            if not r:
                continue
            # "No news" is represented as NewsScore == 0.0 in the current
            # architecture (buy_scoring.py hardcodes 0.0 when has_news is
            # False) — NOT the old neutral-50 convention this used to
            # check for. Verified against production data: NewsScore only
            # ever takes 100.0 (positive) or 0.0 (no news) in practice.
            raw = str(r.get("NewsScore") or "").strip()
            has_news = raw not in ("", "0", "0.0")
            (with_news if has_news else without_news).append(self._pnl(t))
        return {
            "with_news_win_rate": self._win_rate(with_news),
            "without_news_win_rate": self._win_rate(without_news),
        }

    def _fundamental_effectiveness(self, closed, report_by_symbol) -> dict[str, Any]:
        strong, weak = [], []
        for t in closed:
            r = report_by_symbol.get(t.get("symbol"))
            if not r:
                continue
            try:
                fscore = float(r.get("FundamentalScore") or 0)
            except ValueError:
                continue
            (strong if fscore >= 60 else weak).append(self._pnl(t))
        return {
            "strong_fundamentals_win_rate": self._win_rate(strong),
            "weak_fundamentals_win_rate": self._win_rate(weak),
        }

    def _technical_effectiveness(self, closed, report_by_symbol) -> dict[str, Any]:
        high_tech, low_tech = [], []
        for t in closed:
            r = report_by_symbol.get(t.get("symbol"))
            if not r:
                continue
            key = "BuyTier2Score" if t.get("direction") == "BUY" else "SellTier2Score"
            try:
                tscore = float(r.get(key) or 0)
            except ValueError:
                continue
            (high_tech if tscore >= 60 else low_tech).append(self._pnl(t))
        return {
            "high_technical_win_rate": self._win_rate(high_tech),
            "low_technical_win_rate": self._win_rate(low_tech),
        }

    @staticmethod
    def _pnl(trade: dict) -> float:
        try:
            return float(trade.get("realized_pnl") or 0)
        except ValueError:
            return 0.0

    @staticmethod
    def _win_rate(pnls: list[float]) -> float | None:
        if not pnls:
            return None
        return round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 2)

    def _append_observation(self, observation: dict) -> None:
        path = Path(self.OBSERVATIONS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(observation, default=str) + "\n")

    def get_history(self) -> list[dict[str, Any]]:
        path = Path(self.OBSERVATIONS_PATH)
        if not path.exists():
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    engine = LearningEngine()
    obs = engine.observe()
    print(json.dumps(obs, indent=2, default=str))
