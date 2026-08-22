"""Fast regression check for the /translate route wiring after the
React/RTK migration: server.py serves the built frontend/dist shell
(frontend/dist/index.html), not the old translate.html.

Deliberately does not execute any JS - that's covered by the Playwright
test in test_e2e_playwright_translate_page.py. This just proves the
route/file wiring survives, independent of a real browser.
"""


def test_translate_route_serves_built_react_shell(client):
    r = client.get("/translate")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="root"' in r.text


def test_translate_trailing_slash_also_works(client):
    r = client.get("/translate/")
    assert r.status_code == 200
    assert 'id="root"' in r.text
