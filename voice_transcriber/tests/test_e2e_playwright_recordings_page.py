"""Black-box E2E for the /recordings page: real server subprocess + headless
Chromium via Playwright, following the same live_server pattern as the rest
of the suite. Replaces the old /app-hosted RecordingsDrawer, which this page
supersedes.
"""
import pytest

from voice_transcriber.tests.conftest import seed_auth_script


@pytest.mark.integration
def test_recordings_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/recordings")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_recordings_page_lists_own_recordings_filtered_by_date(live_server):
    import requests

    from voice_transcriber import config, db

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

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

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_init_script(seed_auth_script(token, user_obj))
            page = context.new_page()

            page.goto(live_server.base_url + "/recordings")
            page.wait_for_selector("text=hello from the seeded recording", timeout=10000)

            # Sidebar highlights My recordings, not Recorder, while on this page.
            recorder_class = page.get_attribute("a:has-text('Recorder')", "class")
            my_recordings_class = page.get_attribute("a:has-text('My recordings')", "class")
            assert recorder_class is None or "active" not in recorder_class
            assert my_recordings_class is not None and "active" in my_recordings_class

            # A date range excluding the seeded recording (2026-01-01) filters it out.
            page.fill("#my-rec-filter-from", "2026-02-01")
            page.wait_for_selector("text=No recordings yet.", timeout=10000)

            page.fill("#my-rec-filter-from", "")
            page.wait_for_selector("text=hello from the seeded recording", timeout=10000)

            with page.expect_download() as download_info:
                page.click("text=Transcript")
            download = download_info.value
            assert download.suggested_filename == f"{rec_id}.txt"

            # No delete feature on this page - a user can't remove their own
            # recordings from here (unlike admin's All Recordings pane).
            assert page.query_selector("text=Delete") is None

            context.close()
            browser.close()
    finally:
        txt_path.unlink(missing_ok=True)
