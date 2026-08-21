"""CORS gating for the dev-only Vite split (frontend :8000, backend :3000 -
see frontend/vite.config.ts). Confirms the preflight headers _DevOnlyCORSMiddleware
(server.py) adds for config.DEV_FRONTEND_ORIGIN in development, and that they
are entirely absent when config.PRODUCTION is True - production stays
same-origin behind Caddy with no CORS surface at all.
"""
from voice_transcriber import config


def _preflight(client, origin="http://localhost:8000"):
    return client.options(
        "/api/languages",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )


def test_cors_preflight_allows_dev_frontend_origin_in_development(client):
    r = _preflight(client)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_rejects_other_origins_in_development(client):
    r = _preflight(client, origin="http://evil.example.com")
    assert "access-control-allow-origin" not in r.headers


def test_cors_headers_absent_in_production(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION", True)
    r = _preflight(client)
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers
