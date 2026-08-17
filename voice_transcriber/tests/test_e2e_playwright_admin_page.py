"""Black-box E2E for the React/RTK admin console (/admin): real server
subprocess + headless Chromium via Playwright, following the same
live_server pattern as test_e2e_playwright_app_page.py.
"""
import pytest

from voice_transcriber.tests.conftest import best_effort_unlink, seed_auth_script


@pytest.mark.integration
def test_admin_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/admin")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_admin_page_redirects_non_admin_to_app(live_server):
    import requests
    from playwright.sync_api import sync_playwright

    from voice_transcriber import auth, db

    # A second, non-admin user seeded directly against the live_server
    # fixture's tmp_path/app.db, before the subprocess ever started writing
    # to it - same trick the fixture itself uses for its own admin user.
    db.create_user("e2e_regular", auth.hash_password("RegularPass123!"), full_name="Regular User", role="user")

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": "e2e_regular", "password": "RegularPass123!"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(seed_auth_script(token, user_obj))
        page = context.new_page()

        page.goto(live_server.base_url + "/admin")
        page.wait_for_url("**/app", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_admin_page_create_user_round_trip(live_server):
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

        page.goto(live_server.base_url + "/admin")
        page.wait_for_selector("text=Register a user", timeout=10000)

        page.fill("#new-user-username", "e2e_created")
        page.fill("#new-user-password", "CreatedPass123!")
        page.click("text=Create user")

        page.wait_for_selector("text=Created e2e_created.", timeout=10000)
        page.wait_for_selector("text=e2e_created", timeout=10000)  # new row in the table

        context.close()
        browser.close()


@pytest.mark.integration
def test_admin_page_self_deactivate_guard_rail_surfaces_inline_not_via_alert(live_server):
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

        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

        page.goto(live_server.base_url + "/admin")
        page.wait_for_selector(f"text={live_server.admin_username}", timeout=10000)

        row = page.locator("tr", has_text=live_server.admin_username)
        row.get_by_role("button", name="Deactivate").click()

        page.wait_for_selector("text=Cannot deactivate yourself", timeout=10000)
        # Regression guard: this used to be alert(e.message) - a stray
        # native dialog here means the fix-while-porting requirement
        # (inline error state, no alert()) has regressed.
        assert dialogs == [], f"unexpected native dialog(s): {dialogs}"

        context.close()
        browser.close()


@pytest.mark.integration
def test_admin_page_tab_deep_link(live_server):
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

        page.goto(live_server.base_url + "/admin?tab=recordings")
        page.wait_for_selector("text=All recordings", timeout=10000)
        assert page.query_selector("text=Register a user") is None

        context.close()
        browser.close()


@pytest.mark.integration
def test_admin_page_recordings_tab_download_and_delete(live_server):
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

    # Same pattern as test_e2e_playwright_app_page.py's recordings-drawer
    # test: config.RECORDINGS isn't overridden for live_server, so the
    # transcript file has to exist for real for the download endpoint's
    # on-disk check to pass - cleaned up in `finally` regardless of outcome.
    rec_id = "20260101-000000-e2e_admin-def456"
    txt_path = config.RECORDINGS / f"{rec_id}.txt"
    txt_path.write_text("[0.0s] user-1: hello from admin\n", encoding="utf-8")
    try:
        db.add_recording(
            rec_id=rec_id,
            user_id=user_obj["id"],
            wav_file=f"{rec_id}.wav",
            txt_file=f"{rec_id}.txt",
            started_at="2026-01-01T00:00:00+00:00",
            duration=9.5,
            turn_count=1,
            preview="admin-visible recording",
            source="transcribe",
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_init_script(seed_auth_script(token, user_obj))
            page = context.new_page()

            page.goto(live_server.base_url + "/admin?tab=recordings")
            page.wait_for_selector("text=admin-visible recording", timeout=10000)

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
        best_effort_unlink([txt_path])
