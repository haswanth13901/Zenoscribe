"""Black-box E2E: real server subprocess + headless Chromium via Playwright.

Starts a real uvicorn subprocess with test hooks enabled (via the
live_server fixture), uses the admin-only test hook to toggle fake transcribe
modes (timeout/runtime), and asserts the client-side alert() behavior when
uploading through the real UI.

This is the one test in the suite that genuinely needs a live server and a
real browser - everything else in the fast suite goes through TestClient
in-process instead. See pytest.ini: marked `integration`, excluded from a
bare `pytest` run by default.
"""
import json as _json
import time

import pytest
import requests


@pytest.mark.integration
def test_e2e_playwright_upload_alert(live_server, make_wav, tmp_path):
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
            f"window.__E2E_TOKEN = {_json.dumps(token)}; window.__E2E_USER = {_json.dumps(user_obj)}; "
            "sessionStorage.setItem('token', window.__E2E_TOKEN); "
            "sessionStorage.setItem('user', JSON.stringify(window.__E2E_USER));"
            "window.__E2E_ALERTS = []; window.alert = function(m){ window.__E2E_ALERTS.push(String(m)); };"
        )

    def upload_and_get_alert(browser):
        context = browser.new_context()
        context.add_init_script(init_script())
        page = context.new_page()
        page.goto(live_server.base_url + "/app")

        page.click("#uploadBtn")
        page.set_input_files("#uploadInput", str(wav_path))
        page.click("#doTranscribe")

        alert_msg = None
        for _ in range(40):
            alerts = page.evaluate("() => window.__E2E_ALERTS.slice()")
            if alerts:
                alert_msg = alerts[-1]
                break
            time.sleep(0.2)
        context.close()
        return alert_msg

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        set_fake_mode("timeout")
        alert_msg = upload_and_get_alert(browser)
        assert alert_msg, "no alert recorded for timeout case"
        assert "504" in alert_msg or "timed out" in alert_msg, f"unexpected alert for timeout: {alert_msg}"

        set_fake_mode("runtime")
        alert_msg = upload_and_get_alert(browser)
        assert alert_msg, "no alert recorded for runtime error case"
        assert "502" in alert_msg or "runtime" in alert_msg or "Bad Gateway" in alert_msg, (
            f"unexpected alert for runtime error: {alert_msg}"
        )

        set_fake_mode("ok")
        browser.close()
