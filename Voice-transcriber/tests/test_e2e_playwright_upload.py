import os
import sys
import time
import subprocess
import wave
import requests
import pytest
from pathlib import Path

# This test runs the Playwright-based E2E upload+alert flow as an integration test.
# It starts a server subprocess with test-hooks enabled, uses the admin-only
# test hook to toggle fake transcribe modes (timeout/runtime) and asserts the
# client-side alert behavior via a headless Playwright browser.

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
os.chdir(ROOT)

# Helper: create a small WAV file to upload
def _make_wav(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((b'\x00\x00') * 16000)


@pytest.mark.integration
def test_e2e_playwright_upload_alert():
    sys.path.insert(0, str(ROOT))
    import db, auth

    admin_user = 'e2e_admin'
    password = 'E2EPass123!'
    user_id = db.create_user(admin_user, auth.hash_password(password), full_name='E2E Admin', role='admin')

    wav_path = TESTS_DIR / 'e2e_test.wav'
    _make_wav(wav_path)

    PY = sys.executable
    # pick an ephemeral port
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()

    env = os.environ.copy()
    env['ALLOW_TEST_HOOKS'] = 'true'
    HOOK_SECRET = 'e2e-secret'
    env['TEST_HOOK_SECRET'] = HOOK_SECRET

    server = subprocess.Popen([PY, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(port)], env=env)
    base = f'http://127.0.0.1:{port}'

    try:
        # wait for server to be healthy
        for _ in range(60):
            try:
                r = requests.get(base + '/')
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            pytest.fail('Server did not start')

        # Login as admin to obtain token
        r = requests.post(base + '/api/login', json={'username': admin_user, 'password': password})
        assert r.status_code == 200, 'login failed'
        token = r.json().get('token')
        user_obj = {'id': r.json()['user']['id'], 'username': r.json()['user']['username'], 'role': r.json()['user']['role']}

        # helper to toggle server-side fake transcribe mode
        def set_fake_mode(mode):
            headers = {'Authorization': f'Bearer {token}', 'X-TEST-HOOK-SECRET': HOOK_SECRET}
            resp = requests.post(base + '/internal/test-hook/transcribe_mode', json={'mode': mode}, headers=headers)
            assert resp.status_code == 200, f'Setting fake mode failed: {resp.status_code} {resp.text}'

        # start Playwright-driven browser
        from playwright.sync_api import sync_playwright
        import json as _json

        # timeout mode
        set_fake_mode('timeout')

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            init_script = (
                f"window.__E2E_TOKEN = {_json.dumps(token)}; window.__E2E_USER = {_json.dumps(user_obj)}; "
                "sessionStorage.setItem('token', window.__E2E_TOKEN); sessionStorage.setItem('user', JSON.stringify(window.__E2E_USER));"
                "window.__E2E_ALERTS = []; window.alert = function(m){ window.__E2E_ALERTS.push(String(m)); };"
            )
            context.add_init_script(init_script)
            page = context.new_page()
            page.goto(base + '/app')

            page.click('#uploadBtn')
            page.set_input_files('#uploadInput', str(wav_path))
            page.click('#doTranscribe')

            alert_msg = None
            for _ in range(40):
                alerts = page.evaluate('() => window.__E2E_ALERTS.slice()')
                if alerts and len(alerts) > 0:
                    alert_msg = alerts[-1]
                    break
                time.sleep(0.2)
            assert alert_msg, 'No alert recorded for timeout case'
            assert '504' in alert_msg or 'timed out' in alert_msg, f"Unexpected alert for timeout: {alert_msg}"

            # runtime mode (no server restart): toggle, re-create context to reset JS
            context.close()
            browser.close()

        set_fake_mode('runtime')

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            init_script2 = (
                f"window.__E2E_TOKEN = {_json.dumps(token)}; window.__E2E_USER = {_json.dumps(user_obj)}; "
                "sessionStorage.setItem('token', window.__E2E_TOKEN); sessionStorage.setItem('user', JSON.stringify(window.__E2E_USER));"
                "window.__E2E_ALERTS = []; window.alert = function(m){ window.__E2E_ALERTS.push(String(m)); };"
            )
            context.add_init_script(init_script2)
            page = context.new_page()
            page.goto(base + '/app')

            page.click('#uploadBtn')
            page.set_input_files('#uploadInput', str(wav_path))
            page.click('#doTranscribe')

            alert_msg = None
            for _ in range(40):
                alerts = page.evaluate('() => window.__E2E_ALERTS.slice()')
                if alerts and len(alerts) > 0:
                    alert_msg = alerts[-1]
                    break
                time.sleep(0.2)
            assert alert_msg, 'No alert recorded for runtime error case'
            assert '502' in alert_msg or 'runtime' in alert_msg or 'Bad Gateway' in alert_msg, f"Unexpected alert for runtime error: {alert_msg}"

        # reset
        set_fake_mode('ok')

    finally:
        try:
            server.kill()
        except Exception:
            pass
        try:
            os.remove(str(wav_path))
        except Exception:
            pass
        try:
            db.delete_user(user_id)
        except Exception:
            pass
