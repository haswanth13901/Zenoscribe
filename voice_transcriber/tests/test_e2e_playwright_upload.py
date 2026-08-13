"""Black-box E2E: real server subprocess + headless Chromium via Playwright.

Starts a real uvicorn subprocess with test hooks enabled (via the
live_server fixture), uses the admin-only test hook to toggle fake transcribe
modes (timeout/runtime), and asserts the upload panel's inline error text
for each.

Previously drove upload.js's vanilla #uploadBtn UI on /app and asserted
window.alert() calls, then the ported UploadPanel opened via a ?upload=1
deep-link over /app. It's since gained its own route, /upload (see
UploadPage.tsx - the diagnostic info, status + server detail, still shows
inline instead of via alert(); see UploadPanel.tsx's formatUploadError()).
This test was rewritten in place each time rather than left targeting UI
that no longer exists.

This is one of the few tests in the suite that genuinely needs a live
server and a real browser - everything else in the fast suite goes through
TestClient in-process instead. See pytest.ini: marked `integration`,
excluded from a bare `pytest` run by default.
"""
import json as _json
import time

import pytest
import requests


@pytest.mark.integration
def test_upload_page_redirects_unauthenticated_to_login(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(live_server.base_url + "/upload")
        page.wait_for_url("**/login", timeout=10000)

        context.close()
        browser.close()


@pytest.mark.integration
def test_e2e_playwright_upload_inline_error(live_server, make_wav, tmp_path):
    from playwright.sync_api import sync_playwright

    wav_path = make_wav(path=tmp_path / "e2e_test.wav")

    r = requests.post(
        live_server.base_url + "/api/login",
        json={"username": live_server.admin_username, "password": live_server.admin_password},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    user_obj = r.json()["user"]

    def set_fake_mode(mode):
        headers = {"Authorization": f"Bearer {token}", "X-TEST-HOOK-SECRET": live_server.hook_secret}
        resp = requests.post(
            live_server.base_url + "/internal/test-hook/transcribe_mode",
            json={"mode": mode}, headers=headers,
        )
        assert resp.status_code == 200, f"setting fake mode failed: {resp.status_code} {resp.text}"

    def init_script():
        return (
            f"sessionStorage.setItem('token', {_json.dumps(token)}); "
            f"sessionStorage.setItem('user', {_json.dumps(_json.dumps(user_obj))});"
        )

    def upload_and_get_error(browser):
        context = browser.new_context()
        context.add_init_script(init_script())
        page = context.new_page()
        page.goto(live_server.base_url + "/upload")

        # The file input is deliberately hidden (triggered indirectly via
        # the "Choose file" button) - wait for it to be attached, not
        # visible, and set_input_files works on a hidden input directly.
        page.wait_for_selector('[data-testid="upload-file-input"]', state="attached", timeout=10000)
        page.set_input_files('[data-testid="upload-file-input"]', str(wav_path))
        # "text=Transcribe" would also match the "Transcribe a file" heading
        # and the "Transcribe & Translate" button (substring match) - an
        # exact role/name query is unambiguous.
        page.get_by_role("button", name="Transcribe", exact=True).click()

        error_text = None
        for _ in range(40):
            el = page.query_selector('[data-testid="upload-transcribe-error"]')
            if el:
                error_text = el.inner_text()
                break
            time.sleep(0.2)
        context.close()
        return error_text

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        set_fake_mode("timeout")
        error_text = upload_and_get_error(browser)
        assert error_text, "no inline error rendered for the timeout case"
        assert "504" in error_text or "timed out" in error_text, f"unexpected error for timeout: {error_text}"

        set_fake_mode("runtime")
        error_text = upload_and_get_error(browser)
        assert error_text, "no inline error rendered for the runtime error case"
        assert "502" in error_text or "runtime" in error_text or "service error" in error_text, (
            f"unexpected error for runtime error: {error_text}"
        )

        set_fake_mode("ok")
        browser.close()
