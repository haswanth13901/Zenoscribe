"""Presence (`users.last_seen`) and its two-layer write debounce.

Layer 1 is db.should_touch_seen(), an in-memory gate callers use to skip the
write entirely. Layer 2 is touch_seen()'s conditional WHERE, which makes a
write that does get issued a no-op when last_seen is already fresh. Both are
exercised here, plus the end-to-end behaviour through an authenticated
request, since the whole point is that the common request stops writing.
"""
import time

import pytest

from voice_transcriber import config, db


@pytest.fixture(autouse=True)
def clean_debounce_cache():
    """db._last_seen_writes is module state shared by every test in the
    process - clear it either side so these tests neither inherit nor leak
    a claimed window."""
    db._last_seen_writes.clear()
    yield
    db._last_seen_writes.clear()


@pytest.fixture
def seen_user(isolated_db, make_user):
    make_user("presence_user", "PresencePass123!")
    return db.get_user_by_username("presence_user")


def _last_seen(user_id):
    return db.get_user(user_id)["last_seen"]


# --- layer 1: the in-memory gate -----------------------------------------

def test_first_call_is_due_and_second_inside_window_is_not(seen_user):
    uid = seen_user["id"]
    assert db.should_touch_seen(uid) is True
    assert db.should_touch_seen(uid) is False
    assert db.should_touch_seen(uid) is False


def test_window_is_per_user(isolated_db, make_user):
    make_user("presence_a", "PresencePassA123!")
    make_user("presence_b", "PresencePassB123!")
    a = db.get_user_by_username("presence_a")["id"]
    b = db.get_user_by_username("presence_b")["id"]

    assert db.should_touch_seen(a) is True
    # b's window is its own - a's claim must not suppress it.
    assert db.should_touch_seen(b) is True
    assert db.should_touch_seen(a) is False


def test_call_is_due_again_once_the_window_expires(seen_user, monkeypatch):
    uid = seen_user["id"]
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 1)
    assert db.should_touch_seen(uid) is True
    assert db.should_touch_seen(uid) is False
    time.sleep(1.1)
    assert db.should_touch_seen(uid) is True


def test_zero_window_disables_the_debounce(seen_user, monkeypatch):
    """Escape hatch: LAST_SEEN_DEBOUNCE_SEC=0 restores a write per request."""
    uid = seen_user["id"]
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 0)
    assert db.should_touch_seen(uid) is True
    assert db.should_touch_seen(uid) is True


def test_window_is_read_fresh_not_captured_at_import(seen_user, monkeypatch):
    uid = seen_user["id"]
    assert db.should_touch_seen(uid) is True
    assert db.should_touch_seen(uid) is False
    # Widening/narrowing config mid-process must take effect immediately,
    # the same way DATABASE_URL does for pool creation.
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 0)
    assert db.should_touch_seen(uid) is True


def test_cache_is_bounded(isolated_db, seen_user):
    """A pathological number of distinct ids must not grow the cache without
    limit - the sweep drops expired entries, and clears if none are."""
    for i in range(db._LAST_SEEN_CACHE_MAX + 50):
        db.should_touch_seen("synthetic-%d" % i)
    assert len(db._last_seen_writes) <= db._LAST_SEEN_CACHE_MAX


# --- layer 2: the conditional UPDATE -------------------------------------

def test_touch_seen_writes_when_last_seen_is_stale(seen_user, monkeypatch):
    uid = seen_user["id"]
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 0)
    db.touch_seen(uid)
    first = _last_seen(uid)
    assert first is not None


def test_touch_seen_is_a_no_op_while_last_seen_is_fresh(seen_user, monkeypatch):
    """Layer 2 on its own: call touch_seen directly, bypassing the gate.
    The second call must not move last_seen, i.e. Postgres wrote no new row
    version."""
    uid = seen_user["id"]
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 0)
    db.touch_seen(uid)
    first = _last_seen(uid)

    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 3600)
    db.touch_seen(uid)
    assert _last_seen(uid) == first


# --- end to end through an authenticated request -------------------------

def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return {"Authorization": "Bearer %s" % r.json()["token"]}


def test_authenticated_requests_inside_the_window_do_not_move_last_seen(
    client, make_user, monkeypatch,
):
    make_user("presence_http", "PresenceHttpPass123!")
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 3600)
    db._last_seen_writes.clear()
    headers = _login(client, "presence_http", "PresenceHttpPass123!")
    uid = db.get_user_by_username("presence_http")["id"]

    assert client.get("/api/me", headers=headers).status_code == 200
    after_first = _last_seen(uid)
    assert after_first is not None

    for _ in range(5):
        assert client.get("/api/me", headers=headers).status_code == 200
    assert _last_seen(uid) == after_first


def test_presence_still_updates_once_the_window_passes(
    client, make_user, monkeypatch,
):
    """The debounce must not break presence itself - last_seen still moves,
    just at window granularity rather than per request."""
    make_user("presence_moves", "PresenceMovesPass123!")
    monkeypatch.setattr(config, "LAST_SEEN_DEBOUNCE_SEC", 0)
    db._last_seen_writes.clear()
    headers = _login(client, "presence_moves", "PresenceMovesPass123!")
    uid = db.get_user_by_username("presence_moves")["id"]

    assert client.get("/api/me", headers=headers).status_code == 200
    first = _last_seen(uid)
    time.sleep(0.05)
    assert client.get("/api/me", headers=headers).status_code == 200
    assert _last_seen(uid) > first
