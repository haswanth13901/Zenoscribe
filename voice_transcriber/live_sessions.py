"""Process-local registry of active live WebSocket sessions
(transcribe.py's /ws, translate.py's /ws/translate), used only to drain
connections gracefully on shutdown (see server.py's shutdown hook).

This is deliberately NOT shared/cross-replica state - it only ever needs to
reflect the sessions running in *this* process, which is exactly the kind
of state SCALABILITY_AUDIT.md finding F8 says is safe to keep process-local
(a WS connection is already pinned to one replica for its life; nothing
here creates a dependency on a second request reaching that same replica).
A plain in-memory set is the correct, simplest tool for it - unlike
rate_limit.py's counters, this must NOT move to Redis.
"""
import asyncio


class Session:
    """One registered live session handle. `stop_requested` is checked by
    the WS handler's existing watchdog/idle loop (alongside its normal idle
    timers) so a graceful shutdown reuses the same teardown path as a
    natural end-of-session, rather than a separate, less-tested code path."""

    def __init__(self, registry: "set"):
        self.stop_requested = asyncio.Event()
        self._registry = registry
        self._registry.add(self)

    def unregister(self) -> None:
        self._registry.discard(self)


_active: set = set()


def register() -> Session:
    return Session(_active)


def active_count() -> int:
    return len(_active)


async def request_shutdown_and_wait(grace_sec: float) -> int:
    """Signals every currently active session to wrap up, then waits up to
    grace_sec for them to unregister themselves (i.e. their WS handler's
    `finally` block has run, meaning any in-progress recording was
    persisted). Returns the number of sessions still active when the wait
    ended - the caller should treat a nonzero result as "did not fully
    drain in time" (log it), not as an error: whatever's still running when
    the process actually exits behaves exactly like today's un-graceful
    restart already does (session lost - see SCALABILITY_AUDIT.md §5),
    which is a real but pre-existing, documented limitation, not a
    regression introduced by adding this best-effort drain.
    """
    for session in list(_active):
        session.stop_requested.set()
    if not _active:
        return 0
    loop = asyncio.get_event_loop()
    deadline = loop.time() + grace_sec
    while _active and loop.time() < deadline:
        await asyncio.sleep(0.2)
    return len(_active)
