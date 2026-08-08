import os
import sys
import time
import subprocess
import tempfile
import wave
import requests
from pathlib import Path

# Working directories
TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
os.chdir(ROOT)

# Create a small WAV file to upload
wav_path = TESTS_DIR / 'e2e_test.wav'
wav_path.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(wav_path), 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((b'\x00\x00') * 16000)

# Create test admin user in DB (idempotent)
sys.path.insert(0, str(ROOT))
import db, auth
admin_user = 'e2e_admin'
password = 'E2EPass123!'
# create as admin role so it can call the test-hook endpoint
user_id = db.create_user(admin_user, auth.hash_password(password), full_name='E2E Admin', role='admin')

PY = sys.executable
# Start server with test hooks enabled so the runtime test-hook endpoint exists
import socket
s = socket.socket()
s.bind(('127.0.0.1', 0))
port = s.getsockname()[1]
s.close()

env = os.environ.copy()
# Enable server-side test hooks via environment so config picks it up
env['ALLOW_TEST_HOOKS'] = 'true'
# Provide a short secret used by the test to authenticate the hook calls
HOOK_SECRET = 'e2e-secret'
env['TEST_HOOK_SECRET'] = HOOK_SECRET
# Keep localhost restriction (server is bound to 127.0.0.1)
PY = sys.executable
server = subprocess.Popen([PY, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(port)], env=env)
base = f'http://127.0.0.1:{port}'

# Wait for server to be ready
for _ in range(60):
    try:
        r = requests.get(base + '/')
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(0.5)
else:
    server.kill()
    raise SystemExit('Server did not start')

# Install and run Playwright-driven browser test
from playwright.sync_api import sync_playwright

# Login via API to obtain token (admin user)
r = requests.post(base + '/api/login', json={'username': admin_user, 'password': password})
assert r.status_code == 200, 'login failed'
token = r.json().get('token')
user_obj = {'id': r.json()['user']['id'], 'username': r.json()['user']['username'], 'role': r.json()['user']['role']}

# Helper to toggle server-side fake transcribe mode via the admin-only test hook
def set_fake_mode(mode):
    headers = {'Authorization': f'Bearer {token}', 'X-TEST-HOOK-SECRET': HOOK_SECRET}
    resp = requests.post(base + '/internal/test-hook/transcribe_mode', json={'mode': mode}, headers=headers)
    if resp.status_code != 200:
        raise SystemExit(f'Setting fake mode failed: {resp.status_code} {resp.text}')

# Ensure starting in timeout mode for the first assertion
set_fake_mode('timeout')

caught = {'msg': None}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    # Prepare sessionStorage with token and user before any page loads
    import json as _json
    # Override alert to capture messages into window.__E2E_ALERTS (avoids modal dialogs)
    init_script = (
        f"window.__E2E_TOKEN = {_json.dumps(token)}; window.__E2E_USER = {_json.dumps(user_obj)}; "
        "sessionStorage.setItem('token', window.__E2E_TOKEN); sessionStorage.setItem('user', JSON.stringify(window.__E2E_USER));"
        "window.__E2E_ALERTS = []; window.alert = function(m){ window.__E2E_ALERTS.push(String(m)); };"
    )
    context.add_init_script(init_script)
    page = context.new_page()

    # Navigate to main app
    page.goto(base + '/app')

    # Upload file using the hidden input
    page.click('#uploadBtn')
    page.set_input_files('#uploadInput', str(wav_path))
    # Click Transcribe (should trigger timeout path and alert)
    page.click('#doTranscribe')

    # Wait for the page to record an alert
    alert_msg = None
    for _ in range(40):
        alerts = page.evaluate('() => window.__E2E_ALERTS.slice()')
        if alerts and len(alerts) > 0:
            alert_msg = alerts[-1]
            break
        time.sleep(0.2)
    assert alert_msg, 'No alert recorded for timeout case'
    assert '504' in alert_msg or 'timed out' in alert_msg, f"Unexpected alert for timeout: {alert_msg}"

    # Now test runtime error mapping without restarting the server: toggle fake mode via the admin test-hook
    try:
        context.close()
        browser.close()
    except Exception:
        pass

    # Switch server-side fake mode to 'runtime'
    set_fake_mode('runtime')

    # Create a fresh browser/context to reset JS state but reuse the same token
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

    # Reset server fake mode back to normal
    set_fake_mode('ok')

    browser.close()


# Cleanup
server.kill()
try:
    os.remove(str(wav_path))
except Exception:
    pass
try:
    db.delete_user(user_id)
except Exception:
    pass

print('E2E Playwright upload alert test passed')
