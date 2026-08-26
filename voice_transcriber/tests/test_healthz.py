"""GET /healthz - liveness/readiness probe, including the graceful-shutdown
readiness flag added alongside live_sessions.py.
"""
from voice_transcriber import server


def test_healthz_ok_when_db_reachable(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


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
    assert r.json() == {"status": "degraded", "database": "unreachable"}
