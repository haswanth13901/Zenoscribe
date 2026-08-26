"""Single place constructing the shared Redis client, so rate_limit.py (and
anything else that later needs shared ephemeral state) doesn't scatter raw
redis.Redis(...) construction across the codebase - mirrors db.py's
_get_pool() singleton pattern.

Redis here is exclusively for ephemeral, reconstructible state (rate-limit
counters) - never durable business data. See SCALABILITY_DESIGN.md §3.
"""
import redis

try:
    from . import config
except ImportError:  # run flat from inside the package dir
    import config

_client = None


def get_client() -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.Redis.from_url(config.REDIS_URL, decode_responses=False)
    return _client


def close_client():
    """Called from the app's shutdown hook, mirroring db.close_pool()."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
