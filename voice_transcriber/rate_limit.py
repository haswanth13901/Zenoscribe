"""In-memory sliding-window rate limiting.

Single-process only - counters live in a plain dict in this process's
memory, not shared across instances. That's fine for the currently
supported single-container deployment (see E2E_Review.md); if this ever
needs to run as multiple instances behind a load balancer, this needs a
shared store (e.g. Redis) instead, the same caveat that already applies to
SERVER_BOOT_ID in auth.py and to local-disk recordings storage.

Two ways to use it:
  - `per_user(limit, window_sec, scope)` - a FastAPI dependency factory for
    ordinary HTTP routes, keyed by the authenticated user (depends on
    auth.current_user, so it always runs after auth resolves).
  - `hit(key, limit, window_sec)` - the raw check, for call sites that can't
    use a FastAPI dependency: the two WebSocket routes (auth happens via a
    frame after connecting, not a header FastAPI can inject) and
    GlobalRateLimitMiddleware (runs below FastAPI's dependency system
    entirely, as raw ASGI).

`/api/login` keeps its own dedicated, DB-backed limiter (routes_api.py) -
that one needs to survive process restarts and already existed before this
module; it isn't touched here.
"""
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, status

try:
    from . import auth
except ImportError:  # run flat from inside the package dir
    import auth

_lock = threading.Lock()
_buckets: dict[str, deque] = {}


def hit(key: str, limit: int, window_sec: int) -> bool:
    """Records a hit for `key`; returns True if it's within `limit` hits in
    the trailing `window_sec` seconds, False if it should be rejected.
    Rejected hits are not themselves counted, so a client being throttled
    doesn't get to consume future quota just by retrying."""
    now = time.monotonic()
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        cutoff = now - window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def reset_all():
    """Test-only: clears every counter. The fast suite's `client` fixture
    reuses one FastAPI `app` (and therefore this module's global state)
    across all tests, so without this, unrelated tests could trip each
    other's limits depending on run order. See conftest.py."""
    with _lock:
        _buckets.clear()


def per_user(limit: int, window_sec: int, scope: str):
    """FastAPI dependency: rate-limits the current user to `limit` hits per
    `window_sec` seconds within `scope` (a short label distinguishing this
    limit from others - e.g. "upload" vs "ws-connect" - so they don't share
    one counter). `auth.current_user` is itself a FastAPI dependency, so
    when a route already declares `user=Depends(auth.current_user)`,
    FastAPI dedupes the two calls within one request - the token is only
    verified once."""

    async def _dep(user=Depends(auth.current_user)):
        if not hit(f"{scope}:{user['id']}", limit, window_sec):
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
        if hit(f"global-ip:{ip}", self.limit, self.window_sec):
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
