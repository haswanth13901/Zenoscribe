"""Login, /api/me, brute-force lockout, deactivation, and admin user CRUD.

Ports (with real assertions and automatic isolation/cleanup) the old
deactivated_user_test.py, tc06_bruteforce_test.py, and the login/me/admin-CRUD
portions of full_endpoint_test.py.
"""
from voice_transcriber import config


def test_login_success_returns_token_and_user(client, make_user):
    make_user("alice", "AlicePass123!")
    r = client.post("/api/login", json={"username": "alice", "password": "AlicePass123!"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["username"] == "alice"


def test_login_wrong_password_returns_401(client, make_user):
    make_user("bob", "BobPass123!")
    r = client.post("/api/login", json={"username": "bob", "password": "WrongPass"})
    assert r.status_code == 401


def test_login_deactivated_account_returns_403(client, make_user):
    user_id = make_user("carol", "CarolPass123!")
    from voice_transcriber import db
    db.set_active(user_id, False)
    r = client.post("/api/login", json={"username": "carol", "password": "CarolPass123!"})
    assert r.status_code == 403


def test_me_returns_current_user_profile(client, make_user):
    make_user("dave", "DavePass123!", full_name="Dave Tester")
    token = client.post(
        "/api/login", json={"username": "dave", "password": "DavePass123!"}
    ).json()["token"]
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "dave"
    assert r.json()["full_name"] == "Dave Tester"


def test_me_without_token_returns_401(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_login_attempt_limit_then_429(client, make_user):
    make_user("eve", "EvePass123!")
    for i in range(config.LOGIN_ATTEMPT_LIMIT):
        r = client.post("/api/login", json={"username": "eve", "password": "WrongPass"})
        assert r.status_code == 401, f"attempt {i + 1} expected 401, got {r.status_code}"
    r = client.post("/api/login", json={"username": "eve", "password": "WrongPass"})
    assert r.status_code == 429


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_deactivating_user_invalidates_existing_token(client, make_user):
    user_id = make_user("frank", "FrankPass123!")
    make_user("frank_admin", "FrankAdminPass123!", role="admin")
    user_headers = _login(client, "frank", "FrankPass123!")
    admin_headers = _login(client, "frank_admin", "FrankAdminPass123!")

    assert client.get("/api/me", headers=user_headers).status_code == 200

    r = client.post(
        f"/api/admin/users/{user_id}/active",
        headers=admin_headers, json={"is_active": False},
    )
    assert r.status_code == 200

    r = client.get("/api/me", headers=user_headers)
    assert r.status_code in (401, 403)


def test_admin_cannot_deactivate_last_admin(client, make_user):
    admin_id = make_user("only_admin", "OnlyAdminPass123!", role="admin")
    headers = _login(client, "only_admin", "OnlyAdminPass123!")
    r = client.post(
        f"/api/admin/users/{admin_id}/active",
        headers=headers, json={"is_active": False},
    )
    assert r.status_code == 400


def test_admin_cannot_deactivate_self(client, make_user):
    make_user("second_admin_a", "SecondAdminAPass123!", role="admin")
    self_id = make_user("second_admin_b", "SecondAdminBPass123!", role="admin")
    headers = _login(client, "second_admin_b", "SecondAdminBPass123!")
    r = client.post(
        f"/api/admin/users/{self_id}/active",
        headers=headers, json={"is_active": False},
    )
    assert r.status_code == 400


def test_admin_can_list_users(client, make_user):
    make_user("grace", "GracePass123!")
    make_user("grace_admin", "GraceAdminPass123!", role="admin")
    headers = _login(client, "grace_admin", "GraceAdminPass123!")
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert "grace" in usernames


def test_admin_can_create_user(client, make_user):
    make_user("heidi_admin", "HeidiAdminPass123!", role="admin")
    headers = _login(client, "heidi_admin", "HeidiAdminPass123!")
    r = client.post(
        "/api/admin/users", headers=headers,
        json={"username": "api_created", "password": "ApiPass123!",
              "full_name": "API Created", "email": "api@example.com", "role": "user"},
    )
    assert r.status_code == 200
    assert r.json()["id"]


def test_admin_can_reset_user_password(client, make_user):
    user_id = make_user("ivan", "IvanPass123!")
    make_user("ivan_admin", "IvanAdminPass123!", role="admin")
    headers = _login(client, "ivan_admin", "IvanAdminPass123!")
    r = client.post(
        f"/api/admin/users/{user_id}/password",
        headers=headers, json={"password": "NewIvanPass123!"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r = client.post("/api/login", json={"username": "ivan", "password": "NewIvanPass123!"})
    assert r.status_code == 200


def test_admin_can_reactivate_user(client, make_user):
    user_id = make_user("judy", "JudyPass123!")
    make_user("judy_admin", "JudyAdminPass123!", role="admin")
    headers = _login(client, "judy_admin", "JudyAdminPass123!")
    client.post(f"/api/admin/users/{user_id}/active", headers=headers, json={"is_active": False})
    r = client.post(f"/api/admin/users/{user_id}/active", headers=headers, json={"is_active": True})
    assert r.status_code == 200
    r = client.post("/api/login", json={"username": "judy", "password": "JudyPass123!"})
    assert r.status_code == 200


def test_admin_can_delete_user(client, make_user):
    user_id = make_user("mallory", "MalloryPass123!")
    make_user("mallory_admin", "MalloryAdminPass123!", role="admin")
    headers = _login(client, "mallory_admin", "MalloryAdminPass123!")
    r = client.delete(f"/api/admin/users/{user_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_non_admin_cannot_access_admin_endpoints(client, make_user):
    make_user("oscar", "OscarPass123!")
    headers = _login(client, "oscar", "OscarPass123!")
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 403


def test_admin_write_rate_limit_then_429(client, make_user):
    """Proves rate_limit.per_user() is actually wired into a real route via
    Depends() and produces a real 429 over HTTP, not just that the pure
    limiter function works in isolation (see test_rate_limit.py for that).
    The rate-limit dependency runs before the route body, so it 429s on
    attempt 61 even though every one of these targets a user id that
    doesn't exist (each would otherwise 404)."""
    make_user("rl_admin", "RlAdminPass123!", role="admin")
    headers = _login(client, "rl_admin", "RlAdminPass123!")
    for i in range(60):
        r = client.post(
            "/api/admin/users/nonexistent-id/active",
            headers=headers, json={"is_active": True},
        )
        assert r.status_code == 404, f"attempt {i + 1} expected 404, got {r.status_code}"
    r = client.post(
        "/api/admin/users/nonexistent-id/active",
        headers=headers, json={"is_active": True},
    )
    assert r.status_code == 429


def test_admin_create_user_rejects_unsafe_username(client, make_user):
    """A username becomes part of every recording's storage key (see
    storage/base.py's recording_key()) - reject anything that could reach a
    local-backend filesystem path unsafely (a slash, or a ".." sequence),
    found and closed during the storage-abstraction security review rather
    than a previously-reported bug."""
    make_user("username_admin", "UsernameAdminPass123!", role="admin")
    headers = _login(client, "username_admin", "UsernameAdminPass123!")

    for bad_username in ("../../etc/passwd", "a/b", "a\\b", "a..b", "user name"):
        r = client.post(
            "/api/admin/users", headers=headers,
            json={"username": bad_username, "password": "SomePass123!"},
        )
        assert r.status_code == 400, f"{bad_username!r} should have been rejected"

    r = client.post(
        "/api/admin/users", headers=headers,
        json={"username": "a.valid_user-1", "password": "SomePass123!"},
    )
    assert r.status_code == 200
