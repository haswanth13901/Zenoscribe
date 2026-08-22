"""Fast regression check for the /app route wiring after the React/RTK
recorder migration: server.py serves the built frontend/dist shell
(frontend/dist/index.html), not the old index.html.

Deliberately does not execute any JS - that's covered by the Playwright
test in test_e2e_playwright_app_page.py. This just proves the route/file
wiring survives, independent of a real browser.
"""


def test_app_route_serves_built_react_shell(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="root"' in r.text


def test_app_trailing_slash_also_works(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert 'id="root"' in r.text
