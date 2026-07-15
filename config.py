"""
Global configuration for the Quant Trading Platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent

STORAGE_DIR = PROJECT_ROOT / "storage"
CACHE_DIR = STORAGE_DIR / "cache"
LOG_DIR = STORAGE_DIR / "logs"
TRADE_DIR = STORAGE_DIR / "trades"
REPORT_DIR = STORAGE_DIR / "reports"
MODEL_DIR = STORAGE_DIR / "models"
SNAPSHOT_DIR = STORAGE_DIR / "snapshots"


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "Quant Trading Platform"
    timezone: str = "Asia/Kolkata"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    market: str = os.getenv("MARKET", "NSE")
    interval: str = os.getenv("INTERVAL", "1d")

    max_workers: int = int(os.getenv("MAX_WORKERS", "4"))
    cache_enabled: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    data_dir: Path = STORAGE_DIR
    cache_dir: Path = CACHE_DIR
    log_dir: Path = LOG_DIR
    trade_dir: Path = TRADE_DIR
    report_dir: Path = REPORT_DIR
    model_dir: Path = MODEL_DIR
    snapshot_dir: Path = SNAPSHOT_DIR


CONFIG = AppConfig()


def initialize_directories() -> None:
    """Create required storage directories."""
    for directory in (
        CONFIG.data_dir,
        CONFIG.cache_dir,
        CONFIG.log_dir,
        CONFIG.trade_dir,
        CONFIG.report_dir,
        CONFIG.model_dir,
        CONFIG.snapshot_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


initialize_directories()
