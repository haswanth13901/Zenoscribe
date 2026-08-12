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
        assert page.inner_text('[data-testid="recorder-status"]') == "idle"
        assert page.inner_text('[data-testid="recorder-toggle"]') == "Start"

        page.click('[data-testid="recorder-toggle"]')
        # Soniox-independent: the toggle disables and status moves off
        # "idle" as soon as the client starts connecting.
        page.wait_for_function(
            "document.querySelector('[data-testid=\"recorder-status\"]').textContent !== 'idle'", timeout=10000
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


@pytest.mark.integration
def test_app_page_recordings_drawer_download_and_delete(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    from voice_transcriber import config, db

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    # Seeded directly against the live_server fixture's tmp_path/app.db,
    # before the subprocess ever starts writing to it - same pattern the
    # fixture itself already uses to create the admin user. config.RECORDINGS
    # is NOT overridden by live_server (unlike isolated_recordings elsewhere,
    # which can't reach a separate subprocess anyway), so the transcript
    # file has to be written to the real recordings/ dir for the download
    # endpoint's on-disk check to pass - cleaned up in `finally` regardless
    # of outcome, same spirit as recordings/ being gitignored/regenerable.
    rec_id = "20260101-000000-e2e_admin-abc123"
    txt_path = config.RECORDINGS / f"{rec_id}.txt"
    txt_path.write_text("[0.0s] user-1: hello\n", encoding="utf-8")
    try:
        db.add_recording(
            rec_id=rec_id,
            user_id=user_obj["id"],
            wav_file=f"{rec_id}.wav",
            txt_file=f"{rec_id}.txt",
            started_at="2026-01-01T00:00:00+00:00",
            duration=12.3,
            turn_count=2,
            preview="hello from the seeded recording",
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_init_script(seed_auth_script(token, user_obj))
            page = context.new_page()

            page.goto(live_server.base_url + "/app?recordings=1")
            page.wait_for_selector("text=hello from the seeded recording", timeout=10000)

            with page.expect_download() as download_info:
                page.click("text=Transcript")
            download = download_info.value
            assert download.suggested_filename == f"{rec_id}.txt"

            page.once("dialog", lambda dialog: dialog.accept())
            page.click("text=Delete")
            page.wait_for_selector("text=No recordings yet.", timeout=10000)

            context.close()
            browser.close()
    finally:
        txt_path.unlink(missing_ok=True)
