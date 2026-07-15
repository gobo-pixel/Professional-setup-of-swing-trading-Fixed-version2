"""
Thread-safe in-memory cache with optional TTL.

Business modules should use this class instead of global dictionaries.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _CacheItem(Generic[T]):
    value: T
    expires_at: float | None


class Cache(Generic[T]):
    """
    Simple thread-safe TTL cache.
    """

    def __init__(self) -> None:
        self._store: dict[str, _CacheItem[T]] = {}
        self._lock = threading.RLock()

    def set(self, key: str, value: T, ttl: int | None = None) -> None:
        expires_at = None if ttl is None else time.time() + ttl
        with self._lock:
            self._store[key] = _CacheItem(value=value, expires_at=expires_at)

    def get(self, key: str) -> T | None:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None

            if item.expires_at is not None and time.time() > item.expires_at:
                del self._store[key]
                return None

            return item.value

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                key
                for key, item in self._store.items()
                if item.expires_at is not None and item.expires_at <= now
            ]
            for key in expired:
                del self._store[key]

    def __len__(self) -> int:
        self.cleanup()
        return len(self._store)
