"""Fast regression check for the /admin route wiring after the React/RTK
migration: server.py serves the built frontend/dist shell
(voice_transcriber/static/spa_dist/index.html), not the old admin.html.

Deliberately does not execute any JS or exercise the admin-only guard -
that's covered by the Playwright test in test_e2e_playwright_admin_page.py.
This just proves the route/file wiring survives, independent of a real
browser.
"""


def test_admin_route_serves_built_react_shell(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="root"' in r.text


def test_admin_trailing_slash_also_works(client):
    r = client.get("/admin/")
    assert r.status_code == 200
    assert 'id="root"' in r.text
