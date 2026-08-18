"""Fast regression check for the /service-worker.js route: it must be
served from "/" (not /static/) with Service-Worker-Allowed: / - a service
worker's default scope is capped at the directory it's served from, so
without that header (or a root-served path) it could never control
non-/static/ requests, defeating the offline shell it exists to provide.
"""


def test_service_worker_served_from_root_with_allowed_scope(client):
    r = client.get("/service-worker.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["service-worker-allowed"] == "/"
    assert "self.addEventListener" in r.text
