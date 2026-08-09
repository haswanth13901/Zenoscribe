"""POST /internal/test-hook/transcribe_mode: gating semantics.

Ports run_test_hook_check.py, plus new coverage of the 404/403/403/400
gating branches the old script never actually exercised (it only checked the
happy path). config mutations go through monkeypatch, so - unlike the old
script, which flipped these process-wide with no restore at all - they're
automatically undone after each test.

TestClient reports its own host as "testserver" (confirmed by the old
script's own comment), which is never in the localhost allow-list, so it's
what makes test_hook_non_localhost_returns_403_when_restricted work without
any special setup.
"""
from voice_transcriber import config


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_hook_disabled_by_default_returns_404(client, make_user):
    make_user("hook_admin_a", "HookAdminAPass123!", role="admin")
    headers = _login(client, "hook_admin_a", "HookAdminAPass123!")
    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "ok"}, headers=headers)
    assert r.status_code == 404


def test_hook_wrong_secret_returns_403(client, make_user, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", True)
    monkeypatch.setattr(config, "TEST_HOOK_SECRET", "right-secret")
    monkeypatch.setattr(config, "RESTRICT_TEST_HOOK_TO_LOCALHOST", False)
    make_user("hook_admin_b", "HookAdminBPass123!", role="admin")
    headers = _login(client, "hook_admin_b", "HookAdminBPass123!")
    headers["X-TEST-HOOK-SECRET"] = "wrong-secret"
    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "ok"}, headers=headers)
    assert r.status_code == 403


def test_hook_non_localhost_returns_403_when_restricted(client, make_user, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", True)
    monkeypatch.setattr(config, "TEST_HOOK_SECRET", None)
    monkeypatch.setattr(config, "RESTRICT_TEST_HOOK_TO_LOCALHOST", True)
    make_user("hook_admin_c", "HookAdminCPass123!", role="admin")
    headers = _login(client, "hook_admin_c", "HookAdminCPass123!")
    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "ok"}, headers=headers)
    assert r.status_code == 403


def test_hook_invalid_mode_returns_400(client, make_user, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", True)
    monkeypatch.setattr(config, "TEST_HOOK_SECRET", None)
    monkeypatch.setattr(config, "RESTRICT_TEST_HOOK_TO_LOCALHOST", False)
    make_user("hook_admin_d", "HookAdminDPass123!", role="admin")
    headers = _login(client, "hook_admin_d", "HookAdminDPass123!")
    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "bogus"}, headers=headers)
    assert r.status_code == 400


def test_hook_valid_mode_sets_and_clears_fake_mode(client, make_user, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", True)
    monkeypatch.setattr(config, "TEST_HOOK_SECRET", None)
    monkeypatch.setattr(config, "RESTRICT_TEST_HOOK_TO_LOCALHOST", False)
    make_user("hook_admin_e", "HookAdminEPass123!", role="admin")
    headers = _login(client, "hook_admin_e", "HookAdminEPass123!")

    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "ok"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["mode"] == "ok"

    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["mode"] is None


def test_hook_requires_admin_role(client, make_user, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", True)
    monkeypatch.setattr(config, "TEST_HOOK_SECRET", None)
    monkeypatch.setattr(config, "RESTRICT_TEST_HOOK_TO_LOCALHOST", False)
    make_user("hook_plain_user", "HookPlainPass123!", role="user")
    headers = _login(client, "hook_plain_user", "HookPlainPass123!")
    r = client.post("/internal/test-hook/transcribe_mode", json={"mode": "ok"}, headers=headers)
    assert r.status_code == 403
