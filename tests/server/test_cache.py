# Standard
import time

from hermes_server.cache import TTLCache


def test_ttl_cache_get_set():
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=10.0)
    cache.set("foo", "bar")
    assert cache.get("foo") == "bar"
    assert "foo" in cache
    assert len(cache) == 1


def test_ttl_cache_expiration(monkeypatch):
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=1.0)
    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    cache.set("key", "val")
    assert cache.get("key") == "val"

    # Advance time past TTL
    now = 102.0
    assert cache.get("key") is None
    assert "key" not in cache
    assert len(cache) == 0


def test_ttl_cache_max_size_eviction():
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=60.0, max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert len(cache) == 2
    # Adding 3rd key should evict oldest (a)
    cache.set("c", 3)
    assert len(cache) == 2
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_ttl_cache_clear():
    cache: TTLCache[str, int] = TTLCache()
    cache.set("a", 1)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None
