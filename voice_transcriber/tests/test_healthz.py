"""GET /healthz - liveness/readiness probe, including the graceful-shutdown
readiness flag added alongside live_sessions.py.
"""
from voice_transcriber import server


def test_healthz_ok_when_db_reachable(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_healthz_reports_shutting_down_before_touching_db(client, monkeypatch):
    monkeypatch.setattr(server, "_ready", False)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["status"] == "shutting_down"


def test_healthz_degraded_when_db_ping_fails(client, monkeypatch):
    def _raise():
        raise RuntimeError("simulated db outage")

    monkeypatch.setattr(server.db, "ping", _raise)
    r = client.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


def test_healthz_reports_version_and_git_sha(client, monkeypatch):
    monkeypatch.setattr(server.config, "APP_VERSION", "1.2.3")
    monkeypatch.setattr(server.config, "GIT_SHA", "abc1234")
    r = client.get("/healthz")
    body = r.json()
    assert body["version"] == "1.2.3"
    assert body["git_sha"] == "abc1234"
