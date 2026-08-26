# Standard
import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """In-memory Time-To-Live (TTL) cache with capacity bounds.

    :param ttl_seconds: Expiration duration in seconds for cached entries.
    :param max_size: Maximum number of entries permitted before LRU/FIFO eviction.
    """

    def __init__(self, ttl_seconds: float = 3600.0, max_size: int = 2000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._store: dict[K, tuple[V, float]] = {}

    def get(self, key: K) -> V | None:
        """Retrieve value if present and not expired.

        :param key: Cache lookup key.
        :returns: Cached value or None if missing or expired.
        """
        item = self._store.get(key)
        if item is None:
            return None
        val, expires_at = item
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return val

    def set(self, key: K, value: V) -> None:
        """Store or update value with current expiration timestamp.

        :param key: Cache key.
        :param value: Value to cache.
        """
        if len(self._store) >= self.max_size and key not in self._store:
            self._evict_expired_or_oldest()
        self._store[key] = (value, time.monotonic() + self.ttl_seconds)

    def _evict_expired_or_oldest(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self.max_size:
            # Evict first inserted item
            oldest = next(iter(self._store))
            del self._store[oldest]

    def clear(self) -> None:
        """Purge all cached entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: K) -> bool:
        return self.get(key) is not None
