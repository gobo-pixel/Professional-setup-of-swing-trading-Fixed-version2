"""
Structured application logger.

Features:
- Console + rotating file logging
- Thread-safe
- Singleton logger instances
- No duplicate handlers
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import CONFIG

_LOGGERS: dict[str, logging.Logger] = {}


def _formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured singleton logger.

    Args:
        name: Logger name.

    Returns:
        Configured logging.Logger instance.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(CONFIG.log_level.upper())
    logger.propagate = False

    if not logger.handlers:
        log_dir = Path(CONFIG.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_dir / "application.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        file_handler.setFormatter(_formatter())

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(_formatter())

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    _LOGGERS[name] = logger
    return logger
