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

Failure mode, production: if Redis is unreachable, `hit()` raises
RateLimiterUnavailable rather than silently allowing or blocking traffic.
Every call site below turns that into a 503 (or a WS close), distinct from
a normal 429 rejection - a deliberate fail-closed choice (never silently
drop rate limiting/abuse protection just because its backing store had a
blip).

Failure mode, development: failing closed there only means a bare
`uvicorn` run - the documented host workflow - answers every request with
503 until someone remembers to start Redis, which is friction with no
safety payoff: a single dev process is exactly the case where in-memory
counters are still accurate (the multi-replica drift of finding F2 needs
more than one replica to exist). So outside production, an unreachable
Redis transparently falls back to a process-local sliding window with the
same semantics, logged once per outage rather than once per request, and
retried every `_FALLBACK_RETRY_SEC` so the shared counters resume on their
own the moment Redis comes back. Production never takes this path.
"""
import asyncio
import logging
import threading
import time

from fastapi import Depends, HTTPException, status
from redis import RedisError

try:
    from . import auth
    from . import config
    from . import redis_client
except ImportError:  # run flat from inside the package dir
    import auth
    import config
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


# --- Development-only in-memory fallback ------------------------------------
# Only ever reached when config.PRODUCTION is False (see hit()). Same
# sliding-window semantics as the Lua script above, minus the "shared
# across replicas" property that needs Redis - which is precisely the
# property a single local uvicorn process doesn't have anything to share
# with in the first place.

# How long to keep serving from memory after a Redis failure before probing
# Redis again. Short enough that `docker compose up redis` mid-session is
# picked up without a restart; long enough that a Redis that's simply not
# running doesn't cost every single request a connection attempt.
_FALLBACK_RETRY_SEC = 30

_memory_hits: dict[str, list[float]] = {}
_memory_lock = threading.Lock()
# 0.0 means "circuit closed, talk to Redis"; otherwise the timestamp after
# which Redis is worth retrying. hit() runs in a worker thread (every call
# site uses asyncio.to_thread), so this is guarded by _memory_lock rather
# than relying on any single-threaded assumption.
_fallback_retry_at = 0.0


def _memory_hit(key: str, limit: int, window_sec: int, now: float) -> bool:
    with _memory_lock:
        # Trim first, then decide: mirrors the script's ZREMRANGEBYSCORE
        # exclusive-min trim, so a hit exactly `window_sec` old has aged out
        # in both implementations.
        hits = [t for t in _memory_hits.get(key, ()) if t > now - window_sec]
        if len(hits) >= limit:
            _memory_hits[key] = hits
            return False
        hits.append(now)
        _memory_hits[key] = hits
        return True


def _enter_fallback(exc: BaseException, now: float) -> None:
    """Opens the circuit and logs - but only on the transition into a
    fallback window, so an outage costs one WARNING every
    _FALLBACK_RETRY_SEC instead of one ERROR per request (the log spam this
    whole path exists to stop)."""
    global _fallback_retry_at
    with _memory_lock:
        already_open = now < _fallback_retry_at
        _fallback_retry_at = now + _FALLBACK_RETRY_SEC
    if not already_open:
        log.warning(
            "rate limiter: Redis unavailable (%s) - falling back to "
            "in-memory counters for the next %ds. This is development-only; "
            "production fails closed instead. Start Redis (docker compose up "
            "-d redis) for counters shared across processes.",
            exc, _FALLBACK_RETRY_SEC,
        )


def _leave_fallback() -> None:
    global _fallback_retry_at
    with _memory_lock:
        if not _fallback_retry_at:
            return
        _fallback_retry_at = 0.0
        _memory_hits.clear()
    log.info("rate limiter: Redis reachable again - using shared counters.")


def _reset_fallback_state() -> None:
    """Test-only: forgets any open circuit and in-memory counters, so one
    test's simulated outage can't leak into the next."""
    global _fallback_retry_at
    with _memory_lock:
        _fallback_retry_at = 0.0
        _memory_hits.clear()


def hit(key: str, limit: int, window_sec: int) -> bool:
    """Records a hit for `key`; returns True if it's within `limit` hits in
    the trailing `window_sec` seconds, False if it should be rejected.
    Rejected hits are not themselves counted, so a client being throttled
    doesn't get to consume future quota just by retrying. In production,
    raises RateLimiterUnavailable if Redis can't be reached; outside
    production it falls back to process-local counters instead (see the
    module docstring). This is a blocking network call, so call it via
    asyncio.to_thread from async code (every call site in this codebase
    already does)."""
    now = time.time()
    if not config.PRODUCTION and now < _fallback_retry_at:
        return _memory_hit(key, limit, window_sec, now)
    try:
        result = _get_script()(keys=[f"ratelimit:{key}"], args=[now, window_sec, limit])
    except RedisError as exc:
        if config.PRODUCTION:
            log.error("rate limiter: Redis unavailable for key=%s: %s", key, exc)
            raise RateLimiterUnavailable() from exc
        _enter_fallback(exc, now)
        return _memory_hit(key, limit, window_sec, now)
    if _fallback_retry_at:
        _leave_fallback()
    return bool(result)


def reset_all():
    """Test-only: clears every counter in the current Redis DB. Tests use a
    dedicated fakeredis instance/DB index (see conftest.py's isolated_redis
    fixture), never the real dev/prod Redis."""
    _reset_fallback_state()
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
