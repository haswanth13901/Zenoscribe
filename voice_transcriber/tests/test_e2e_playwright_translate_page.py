"""Black-box E2E for the React/RTK translate page (/translate): real server
subprocess + headless Chromium via Playwright, following the same
live_server pattern as test_e2e_playwright_app_page.py.

translate.py opens the upstream Soniox connection BEFORE sending
{"type":"ready"} (the opposite order from transcribe.py, which the recorder
uses) - confirmed by reading the source. With no real Soniox credentials
(this test suite deliberately forces an invalid SONIOX_API_KEY for every
integration test - see conftest.py's live_server fixture), the client
therefore never reaches "ready"/"listening" at all, unlike the recorder,
where reaching "listening" briefly IS reachable without real credentials.
Tests here only assert what's actually reachable: "connecting", then
settling into a non-busy state (whatever it is) without hanging. No
assertions on real caption/translation content or actual TTS audio
playback - that needs real API credits, same posture as the recorder.
"""
import pytest

from voice_transcriber.tests.conftest import seed_auth_script


@pytest.mark.integration
def test_translate_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/translate")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_translate_page_mode_toggle_swaps_language_fields(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/translate")
        page.wait_for_selector('[data-testid="translate-status"]', timeout=10000)
        assert page.inner_text('[data-testid="translate-status"]') == "idle"

        assert page.query_selector("#target-language") is not None
        assert page.query_selector("#language-a") is None

        page.click('[data-testid="mode-two-way"]')
        page.wait_for_selector("#language-a", timeout=5000)
        assert page.query_selector("#target-language") is None
        assert page.query_selector("#language-b") is not None

        context.close()
        browser.close()


@pytest.mark.integration
def test_translate_page_start_reaches_connecting_then_settles(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
        )
        context = browser.new_context()
        context.grant_permissions(["microphone"])
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/translate")
        page.wait_for_selector('[data-testid="translate-toggle"]', timeout=10000)
        assert page.inner_text('[data-testid="translate-toggle"]') == "Start"

        page.click('[data-testid="translate-toggle"]')
        # Soniox-independent: the toggle disables and status moves off
        # "idle" as soon as the client starts connecting.
        page.wait_for_function(
            "document.querySelector('[data-testid=\"translate-status\"]').textContent !== 'idle'", timeout=10000
        )

        # Without real Soniox credentials, "ready" is unreachable (the
        # upstream STT connection is opened before ready is sent) - assert
        # only that the toggle doesn't hang disabled forever, not that it
        # reaches "listening".
        page.wait_for_function(
            "!document.querySelector('[data-testid=\"translate-toggle\"]').disabled", timeout=20000
        )
        toggle_text = page.inner_text('[data-testid="translate-toggle"]')
        assert toggle_text in ("Start", "Stop")

        if toggle_text == "Stop":
            page.click('[data-testid="translate-toggle"]')
            page.wait_for_function(
                "document.querySelector('[data-testid=\"translate-toggle\"]').textContent === 'Start'", timeout=10000
            )

        context.close()
        browser.close()


@pytest.mark.integration
def test_translate_page_restart_does_not_hang(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/translate")
        page.wait_for_selector('[data-testid="translate-restart"]', timeout=10000)

        # Not running: Restart just clears (shows "cleared"), no 400ms
        # re-start delay to wait out.
        page.click('[data-testid="translate-restart"]')
        page.wait_for_function(
            "document.querySelector('[data-testid=\"translate-status\"]').textContent === 'cleared'", timeout=5000
        )

        context.close()
        browser.close()


@pytest.mark.integration
def test_translate_page_view_switcher(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/translate")
        page.wait_for_selector('[data-testid="view-columns"]', timeout=10000)

        # Default view is "stacked" (readStoredView()'s default with no
        # saved localStorage value) - explicitly select Columns first.
        page.click('[data-testid="view-columns"]')
        page.wait_for_selector("text=Source speech appears here.", timeout=5000)

        page.click('[data-testid="view-stacked"]')
        page.wait_for_selector("text=Nothing yet.", timeout=5000)

        page.click('[data-testid="view-focus"]')
        page.wait_for_selector("text=Nothing yet.", timeout=5000)

        context.close()
        browser.close()
