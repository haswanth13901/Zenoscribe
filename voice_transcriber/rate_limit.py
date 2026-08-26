"""Redis-backed sliding-window rate limiting - shared across every replica.

The previous implementation kept counters in a plain in-memory dict, which
is fine for exactly one process but silently loses precision the moment a
second replica exists (see SCALABILITY_AUDIT.md finding F2): a per-user
limit effectively multiplies by however many replicas a load balancer
happens to route a given user across. This module preserves the exact same
public API and semantics (sliding window, rejected hits don't consume
quota, independent per-key budgets) but backs them with Redis instead, so
every replica enforces the same counters.

Two ways to use it:
  - `per_user(limit, window_sec, scope)` - a FastAPI dependency factory for
    ordinary HTTP routes, keyed by the authenticated user (depends on
    auth.current_user, so it always runs after auth resolves).
  - `hit(key, limit, window_sec)` - the raw check, for call sites that can't
    use a FastAPI dependency: the two WebSocket routes (auth happens via a
    frame, not a header) and GlobalRateLimitMiddleware (runs below FastAPI's
    dependency system entirely, as raw ASGI).

`/api/login` keeps its own dedicated, DB-backed limiter (routes_api.py) -
that one needs to survive process restarts and was already correctly shared
across replicas before this module existed (Postgres-backed); it isn't
touched here.

Failure mode: if Redis is unreachable, `hit()` raises RateLimiterUnavailable
rather than silently allowing or blocking traffic. Every call site below
turns that into a 503 (or a WS close), distinct from a normal 429 rejection
- a deliberate fail-closed choice (never silently drop rate limiting/abuse
protection just because its backing store had a blip).
"""
import asyncio
import logging
import time

from fastapi import Depends, HTTPException, status
from redis import RedisError

try:
    from . import auth
    from . import redis_client
except ImportError:  # run flat from inside the package dir
    import auth
    import redis_client

log = logging.getLogger("rate_limit")

# Sliding-window check-and-increment, atomic per invocation (Redis executes
# a Lua script as a single, uninterruptible step - no other client's EVAL
# or command can interleave partway through). `now` is supplied by the
# caller (time.time(), a real wall-clock reading - NOT time.monotonic(),
# whose reference epoch is arbitrary per-process and therefore meaningless
# to compare across replicas/machines) so the window is comparable across
# every replica hitting the same Redis instance.
#
# Member uniqueness: each ZSET member must be unique or a second hit at the
# same score silently overwrites the first (undercounting the window) -
# originally used a `now`+math.random() suffix, but `time.time()`'s actual
# resolution is coarse enough on some platforms (confirmed directly: 200
# rapid calls on Windows all returned the exact same value) that many hits
# in a tight loop share one `now`, and relying on math.random() alone to
# disambiguate those turned out to be flaky under real load (an
# intermittent test failure, tracked down to exactly this). `INCR` on a
# per-key sequence counter instead guarantees a distinct member every call,
# independent of clock resolution or Lua's PRNG behavior - the score (still
# `now`) is what the sliding-window trim below actually depends on;
# multiple members legitimately sharing one score is fine.
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', '(' .. tostring(now - window))
local count = redis.call('ZCARD', key)
local ttl_ms = math.floor(window * 1000) + 1000
if count >= limit then
    redis.call('PEXPIRE', key, ttl_ms)
    return 0
end
local seq = redis.call('INCR', key .. ':seq')
redis.call('ZADD', key, now, tostring(seq))
redis.call('PEXPIRE', key, ttl_ms)
redis.call('PEXPIRE', key .. ':seq', ttl_ms)
return 1
"""

_script = None


def _get_script():
    # redis-py's Script object auto-handles the EVALSHA/NOSCRIPT-fallback
    # dance internally, and is safe to reuse across calls/clients as long as
    # the client itself doesn't change - re-registering against whatever
    # client redis_client.get_client() currently returns keeps this correct
    # even if a test monkeypatches the client mid-run.
    global _script
    client = redis_client.get_client()
    if _script is None or _script.registered_client is not client:
        _script = client.register_script(_SLIDING_WINDOW_SCRIPT)
    return _script


class RateLimiterUnavailable(Exception):
    """Raised by hit() when Redis can't be reached. Distinct from a normal
    rate-limit rejection so callers can fail closed with a 503 ("try again,
    this is us") rather than a 429 ("you're doing this too much")."""


def hit(key: str, limit: int, window_sec: int) -> bool:
    """Records a hit for `key`; returns True if it's within `limit` hits in
    the trailing `window_sec` seconds, False if it should be rejected.
    Rejected hits are not themselves counted, so a client being throttled
    doesn't get to consume future quota just by retrying. Raises
    RateLimiterUnavailable if Redis can't be reached - this is a blocking
    network call, so call it via asyncio.to_thread from async code (every
    call site in this codebase already does)."""
    now = time.time()
    try:
        result = _get_script()(keys=[f"ratelimit:{key}"], args=[now, window_sec, limit])
    except RedisError as exc:
        log.error("rate limiter: Redis unavailable for key=%s: %s", key, exc)
        raise RateLimiterUnavailable() from exc
    return bool(result)


def reset_all():
    """Test-only: clears every counter in the current Redis DB. Tests use a
    dedicated fakeredis instance/DB index (see conftest.py's isolated_redis
    fixture), never the real dev/prod Redis."""
    redis_client.get_client().flushdb()


def per_user(limit: int, window_sec: int, scope: str):
    """FastAPI dependency: rate-limits the current user to `limit` hits per
    `window_sec` seconds within `scope` (a short label distinguishing this
    limit from others - e.g. "upload" vs "ws-connect" - so they don't share
    one counter). `auth.current_user` is itself a FastAPI dependency, so
    when a route already declares `user=Depends(auth.current_user)`,
    FastAPI dedupes the two calls within one request - the token is only
    verified once."""

    async def _dep(user=Depends(auth.current_user)):
        try:
            allowed = await asyncio.to_thread(hit, f"{scope}:{user['id']}", limit, window_sec)
        except RateLimiterUnavailable:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Rate limiting temporarily unavailable, try again shortly",
            )
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Rate limit exceeded, try again shortly",
            )
        return user

    return _dep


class GlobalRateLimitMiddleware:
    """Per-IP safety net covering every request AND WebSocket handshake -
    the specific expensive endpoints (uploads, WS connects) get their own
    tighter limits via `per_user`/`hit` above; this one exists to catch
    everything else (scripted flooding, any endpoint nobody thought to tune
    individually) without needing to hand-tune every route.

    Plain ASGI, not Starlette's BaseHTTPMiddleware - that only sees "http"
    scope requests and passes "websocket" scope through untouched, which
    would leave WS connection floods completely uncovered by this net.
    """

    def __init__(self, app, limit: int = 600, window_sec: int = 60):
        self.app = app
        self.limit = limit
        self.window_sec = window_sec

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        ip = client[0] if client else "unknown"

        try:
            allowed = await asyncio.to_thread(hit, f"global-ip:{ip}", self.limit, self.window_sec)
        except RateLimiterUnavailable:
            if scope["type"] == "websocket":
                message = await receive()
                if message["type"] == "websocket.connect":
                    await send({"type": "websocket.close", "code": 1013})  # "Try Again Later"
                return
            await send({
                "type": "http.response.start",
                "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({
                "type": "http.response.body",
                "body": b"Rate limiting temporarily unavailable, try again shortly",
            })
            return

        if allowed:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # A WS handshake must be answered with accept or close before
            # anything else - reject it outright rather than letting the
            # inner app's own accept() run.
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.close", "code": 4429})
            return

        await send({
            "type": "http.response.start",
            "status": status.HTTP_429_TOO_MANY_REQUESTS,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body",
            "body": b"Rate limit exceeded, try again shortly",
        })
