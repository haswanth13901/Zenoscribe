import sys, os
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import config, auth, db, routes_api
from server import app

# Enable test hooks for this run
config.ALLOW_TEST_HOOKS = True
config.TEST_HOOK_SECRET = 'secret123'
config.RESTRICT_TEST_HOOK_TO_LOCALHOST = False  # allow TestClient which uses 'testserver' host

# Create admin user
admin_user = 'hook_admin'
admin_pw = 'HookAdmin123!'
admin_id = db.create_user(admin_user, auth.hash_password(admin_pw), full_name='Hook Admin', role='admin')

client = TestClient(app)
# Login
r = client.post('/api/login', json={'username': admin_user, 'password': admin_pw})
print('login', r.status_code, r.text)
assert r.status_code == 200
token = r.json().get('token')
headers = {'x-test-hook-secret': 'secret123', 'Authorization': f'Bearer {token}'}
# Call endpoint with correct header
resp = client.post('/internal/test-hook/transcribe_mode', json={'mode':'ok'}, headers=headers)
print('set ok', resp.status_code, resp.text)
assert resp.status_code == 200
# Clear
resp2 = client.post('/internal/test-hook/transcribe_mode', json={'mode': None}, headers=headers)
print('clear', resp2.status_code, resp2.text)
assert resp2.status_code == 200

print('test hook endpoint works')
