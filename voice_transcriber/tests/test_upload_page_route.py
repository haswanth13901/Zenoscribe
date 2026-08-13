"""Fast regression check for the /upload route wiring, mirroring
test_home_page_route.py. Deliberately does not execute any JS - that's
covered by the Playwright test in test_e2e_playwright_upload.py.
"""


def test_upload_route_serves_built_react_shell(client):
    r = client.get("/upload")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="root"' in r.text


def test_upload_trailing_slash_also_works(client):
    r = client.get("/upload/")
    assert r.status_code == 200
    assert 'id="root"' in r.text
