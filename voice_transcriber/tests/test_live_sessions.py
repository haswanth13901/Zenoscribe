"""Unit tests for voice_transcriber.live_sessions - the process-local
registry used to drain active WS sessions on graceful shutdown. Fully
testable without a real WS/Soniox connection since it's just bookkeeping;
see transcribe.py's watchdog()/translate.py's keepalive_and_silence() for
how a real session actually reacts to stop_requested (untestable without a
live connection - see SCALABILITY_AUDIT.md's environment note and the final
report's "graceful shutdown" section for the manual VM test needed).
"""
import asyncio

import pytest

from voice_transcriber import live_sessions


@pytest.fixture(autouse=True)
def _clean_registry():
    live_sessions._active.clear()
    yield
    live_sessions._active.clear()


def test_register_adds_to_active_count():
    assert live_sessions.active_count() == 0
    s = live_sessions.register()
    assert live_sessions.active_count() == 1
    s.unregister()
    assert live_sessions.active_count() == 0


def test_unregister_is_idempotent():
    s = live_sessions.register()
    s.unregister()
    s.unregister()  # must not raise
    assert live_sessions.active_count() == 0


async def test_request_shutdown_sets_stop_requested_on_every_session():
    a = live_sessions.register()
    b = live_sessions.register()
    assert not a.stop_requested.is_set()
    assert not b.stop_requested.is_set()

    # Both unregister "immediately" (simulating sessions that react fast),
    # so the wait returns well before the grace period elapses.
    async def _react(session):
        await session.stop_requested.wait()
        session.unregister()

    asyncio.create_task(_react(a))
    asyncio.create_task(_react(b))

    still_active = await live_sessions.request_shutdown_and_wait(grace_sec=5)
    assert still_active == 0
    assert a.stop_requested.is_set()
    assert b.stop_requested.is_set()


async def test_request_shutdown_returns_remaining_count_after_grace_period():
    live_sessions.register()  # never reacts/unregisters
    still_active = await live_sessions.request_shutdown_and_wait(grace_sec=0.3)
    assert still_active == 1


async def test_request_shutdown_with_no_active_sessions_returns_immediately():
    still_active = await live_sessions.request_shutdown_and_wait(grace_sec=30)
    assert still_active == 0
