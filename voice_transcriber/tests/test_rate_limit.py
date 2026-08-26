"""Unit tests for voice_transcriber.rate_limit - the Redis-backed
sliding-window limiter and its FastAPI dependency wrapper. Deliberately
doesn't hit real routes dozens of times to trip a limit; that's redundant
with what these unit tests already prove directly, and would just slow the
suite down.

Run against a real fakeredis instance (isolated_redis, conftest.py), not a
mocked hit()/per_user() - fakeredis's Lua/EVAL support was verified
separately to actually execute rate_limit.py's sliding-window script
correctly (see test_storage.py's neighbor note and SCALABILITY_AUDIT.md),
so this is real coverage of the script's logic, not a stub.
"""
import pytest
from fastapi import HTTPException
from redis import RedisError

from voice_transcriber import rate_limit


@pytest.fixture(autouse=True)
def _clean_state(isolated_redis):
    yield


def test_hit_allows_up_to_the_limit_then_rejects():
    for _ in range(3):
        assert rate_limit.hit("k", 3, 60) is True
    assert rate_limit.hit("k", 3, 60) is False


def test_hit_is_scoped_per_key():
    for _ in range(3):
        assert rate_limit.hit("a", 3, 60) is True
    # A different key has its own independent budget, unaffected by "a"
    # already being maxed out.
    assert rate_limit.hit("b", 3, 60) is True


def test_hit_allows_again_once_the_window_rolls_past(monkeypatch):
    now = [1000.0]
    # time.time(), not time.monotonic(): the sliding window's score has to
    # be a real wall-clock reading, comparable across replicas/processes -
    # monotonic's reference epoch is arbitrary per-process (see
    # rate_limit.py's module docstring), so it can't be shared this way.
    monkeypatch.setattr(rate_limit.time, "time", lambda: now[0])
    assert rate_limit.hit("k", 1, 10) is True
    assert rate_limit.hit("k", 1, 10) is False
    now[0] += 11
    assert rate_limit.hit("k", 1, 10) is True


def test_rejected_hits_are_not_themselves_counted(isolated_redis):
    # A client stuck at the limit and retrying shouldn't burn through any
    # more of its own quota than the successful hits already used.
    assert rate_limit.hit("k", 1, 60) is True
    for _ in range(5):
        assert rate_limit.hit("k", 1, 60) is False
    assert isolated_redis.zcard("ratelimit:k") == 1


def test_hit_raises_rate_limiter_unavailable_when_redis_down(monkeypatch):
    def _raise(*a, **kw):
        raise RedisError("simulated redis outage")

    monkeypatch.setattr(rate_limit, "_get_script", lambda: _raise)
    with pytest.raises(rate_limit.RateLimiterUnavailable):
        rate_limit.hit("k", 1, 60)


async def test_per_user_dependency_raises_429_once_exceeded():
    dep = rate_limit.per_user(2, 60, "scope")
    user = {"id": "u1"}

    await dep(user=user)
    await dep(user=user)
    with pytest.raises(HTTPException) as exc_info:
        await dep(user=user)
    assert exc_info.value.status_code == 429


async def test_per_user_dependency_scopes_are_independent():
    dep_a = rate_limit.per_user(1, 60, "scope-a")
    dep_b = rate_limit.per_user(1, 60, "scope-b")
    user = {"id": "u1"}

    await dep_a(user=user)
    # Same user, different scope label - its own independent budget, not
    # sharing "scope-a"'s counter.
    await dep_b(user=user)


async def test_per_user_dependency_scopes_are_independent_per_user():
    dep = rate_limit.per_user(1, 60, "scope")
    await dep(user={"id": "u1"})
    # A different user under the same scope has their own budget.
    await dep(user={"id": "u2"})
