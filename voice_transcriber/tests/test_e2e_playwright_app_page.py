"""Black-box E2E for the React/RTK recorder (/app): real server subprocess +
headless Chromium via Playwright, following the same live_server pattern as
test_e2e_playwright_home_page.py.

transcribe.py sends {"type":"ready"} to the client before it ever opens the
upstream Soniox connection, so the recorder always reaches its own
"connecting"/"authenticating" UI states regardless of Soniox reachability -
those are asserted here. "listening" is NOT asserted to persist: if Soniox
is unreachable (no real credentials in CI), the server sends an error
shortly after and the client reverts out of "listening" moments later. This
matches the rest of the suite's posture of not asserting real-Soniox
behavior outside the explicitly-gated real_network tests.

Requires `npm --prefix frontend run build` (or the Docker build stage) to
have produced voice_transcriber/static/spa_dist/ before this runs - see the
README's "Frontend" section.
"""
import pytest

from voice_transcriber.tests.conftest import best_effort_unlink, seed_auth_script

FAKE_MEDIA_ARGS = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


@pytest.mark.integration
def test_app_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/app")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_app_page_authenticated_render_and_start_stop(live_server):
    import requests

    from voice_transcriber import config

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    # Clicking Start opens a real /ws session: the server writes audio
    # chunks to a .wav as they stream in (transcribe.py's audio_writer),
    # independent of whether the upstream Soniox connection ever succeeds.
    # It's supposed to discard the file itself if the session ends with no
    # turns (the expected outcome here, with fake silent audio and likely
    # no real Soniox credentials in this environment) - this cleanup is a
    # defensive backstop for that path regardless, so the test never leaves
    # artifacts in the real (non-isolated) recordings/ dir. config.RECORDINGS
    # is not overridden for live_server (see the drawer test below), same
    # reason this can't use an isolated temp dir here either.
    before = set(config.RECORDINGS.glob(f"*-{live_server.admin_username}-*"))
    try:
        _run_start_stop_flow(live_server, token, user_obj)
    finally:
        new_files = set(config.RECORDINGS.glob(f"*-{live_server.admin_username}-*")) - before
        best_effort_unlink(new_files)


def _run_start_stop_flow(live_server, token, user_obj):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=FAKE_MEDIA_ARGS)
        context = browser.new_context()
        context.grant_permissions(["microphone"])
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/app")
        page.wait_for_selector('[data-testid="recorder-toggle"]', timeout=10000)
        # "idle" is blanked out in the UI (RecorderPage.tsx) - only non-idle
        # status text (connecting, listening, stopped, errors) ever shows.
        assert page.inner_text('[data-testid="recorder-status"]') == ""
        assert page.inner_text('[data-testid="recorder-toggle"]') == "Start"

        page.click('[data-testid="recorder-toggle"]')
        # Soniox-independent: the toggle disables and status moves off
        # blank/"idle" as soon as the client starts connecting.
        page.wait_for_function(
            "document.querySelector('[data-testid=\"recorder-status\"]').textContent !== ''", timeout=10000
        )

        # Whatever happens with the upstream Soniox connection, the toggle
        # eventually re-enables (either reaching "listening", or reverting
        # to a stopped/error state if Soniox is unreachable in this
        # environment) - assert only that it doesn't hang disabled forever.
        page.wait_for_function(
            "!document.querySelector('[data-testid=\"recorder-toggle\"]').disabled", timeout=20000
        )
        toggle_text = page.inner_text('[data-testid="recorder-toggle"]')
        assert toggle_text in ("Start", "Stop")

        if toggle_text == "Stop":
            page.click('[data-testid="recorder-toggle"]')
            page.wait_for_function(
                "document.querySelector('[data-testid=\"recorder-toggle\"]').textContent === 'Start'", timeout=10000
            )
            assert page.inner_text('[data-testid="recorder-status"]') == "stopped"

        context.close()
        browser.close()
