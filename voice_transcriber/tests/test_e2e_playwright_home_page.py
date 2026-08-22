"""Black-box E2E for the React/RTK /home pilot: real server subprocess +
headless Chromium via Playwright, following the same live_server pattern as
test_e2e_playwright_upload.py.

Requires `npm --prefix frontend run build` (or the Docker build stage) to
have produced voice_transcriber/static/home_dist/ before this runs - see
the README's "Frontend" section.
"""
import json as _json

import pytest


@pytest.mark.integration
def test_home_page_authenticated_render_and_nav(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    r_token = r.json()["token"]
    r_user = r.json()["user"]

    def seed_auth_script():
        return (
            f"sessionStorage.setItem('token', {_json.dumps(r_token)}); "
            f"sessionStorage.setItem('user', {_json.dumps(_json.dumps(r_user))});"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(seed_auth_script())
        page = context.new_page()

        page.goto(live_server.base_url + "/home")

        page.wait_for_selector("text=Good ", timeout=10000)
        assert r_user["username"] in page.content()
        page.wait_for_selector("text=Recent sessions", timeout=10000)

        page.click('[data-testid="go-record"]')
        page.wait_for_url("**/app", timeout=10000)

        page.go_back()
        page.wait_for_selector('[data-testid="go-translate"]', timeout=10000)
        page.click('[data-testid="go-translate"]')
        page.wait_for_url("**/translate", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_home_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/home")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()
