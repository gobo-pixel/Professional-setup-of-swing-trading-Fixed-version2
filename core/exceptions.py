"""
Custom exceptions used across the Quant Trading Platform.
"""

from __future__ import annotations


class QuantPlatformError(Exception):
    """Base exception for the application."""


class ConfigurationError(QuantPlatformError):
    """Raised when configuration is invalid."""


class DataError(QuantPlatformError):
    """Raised when market/fundamental/news data is invalid or unavailable."""


class ValidationError(QuantPlatformError):
    """Raised when validation checks fail."""


class IndicatorError(QuantPlatformError):
    """Raised when indicator calculation fails."""


class StrategyError(QuantPlatformError):
    """Raised when strategy evaluation fails."""


class DecisionError(QuantPlatformError):
    """Raised when the decision engine cannot determine an action."""


class RiskError(QuantPlatformError):
    """Raised when risk constraints are violated."""


class PortfolioError(QuantPlatformError):
    """Raised for portfolio state or allocation errors."""


class BrokerError(QuantPlatformError):
    """Raised when broker operations fail."""


class APIError(QuantPlatformError):
    """Raised when an external API request fails."""


class CacheError(QuantPlatformError):
    """Raised when cache operations fail."""


class StorageError(QuantPlatformError):
    """Raised when persistence or filesystem operations fail."""
