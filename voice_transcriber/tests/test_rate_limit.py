"""Unit tests for voice_transcriber.rate_limit - the sliding-window limiter
and its FastAPI dependency wrapper. Deliberately doesn't hit real routes
dozens of times to trip a limit; that's redundant with what these unit
tests already prove directly, and would just slow the suite down.
"""
import pytest
from fastapi import HTTPException

from voice_transcriber import rate_limit


@pytest.fixture(autouse=True)
def _clean_state():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


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
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    assert rate_limit.hit("k", 1, 10) is True
    assert rate_limit.hit("k", 1, 10) is False
    now[0] += 11
    assert rate_limit.hit("k", 1, 10) is True


def test_rejected_hits_are_not_themselves_counted():
    # A client stuck at the limit and retrying shouldn't burn through any
    # more of its own quota than the successful hits already used.
    assert rate_limit.hit("k", 1, 60) is True
    for _ in range(5):
        assert rate_limit.hit("k", 1, 60) is False
    with rate_limit._lock:
        assert len(rate_limit._buckets["k"]) == 1


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
