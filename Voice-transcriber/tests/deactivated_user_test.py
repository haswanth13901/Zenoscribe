import os
import sys
import requests
sys.path.insert(0, os.getcwd())
import db, auth

BASE = 'http://127.0.0.1:8000'
user_pwd = 'DeactTestPass1!'
admin_pwd = 'DeactAdminPass1!'

print('Creating test user and admin...')
user_id = db.create_user('tc05_user2', auth.hash_password(user_pwd), full_name='TC05 User')
admin_id = db.create_user('tc05_admin2', auth.hash_password(admin_pwd), full_name='TC05 Admin', role='admin')
print('user_id', user_id, 'admin_id', admin_id)

# User login
r = requests.post(BASE + '/api/login', json={'username': 'tc05_user2', 'password': user_pwd})
assert r.status_code == 200, f'user login failed: {r.status_code} {r.text}'
user_token = r.json().get('token')
headers = {'Authorization': f'Bearer {user_token}'}

# Protected call should succeed before deactivation
r2 = requests.get(BASE + '/api/me', headers=headers)
assert r2.status_code == 200, f'/api/me before deactivation failed: {r2.status_code} {r2.text}'

# Admin login
ra = requests.post(BASE + '/api/login', json={'username': 'tc05_admin2', 'password': admin_pwd})
assert ra.status_code == 200, f'admin login failed: {ra.status_code} {ra.text}'
admin_token = ra.json().get('token')
ah = {'Authorization': f'Bearer {admin_token}'}

# Deactivate the user
rd = requests.post(BASE + f'/api/admin/users/{user_id}/active', headers=ah, json={'is_active': False})
assert rd.status_code == 200, f'deactivate failed: {rd.status_code} {rd.text}'

# The original token should now be rejected
r3 = requests.get(BASE + '/api/me', headers=headers)
assert r3.status_code in (401, 403), f'/api/me after deactivation expected 401/403 got: {r3.status_code} {r3.text}'
print('TC-05 passed: deactivated token rejected as expected')

# Cleanup: try to reactivate and remove test users
try:
    requests.post(BASE + f'/api/admin/users/{user_id}/active', headers=ah, json={'is_active': True})
except Exception:
    pass
try:
    db.delete_user(user_id)
except Exception:
    pass
try:
    db.delete_user(admin_id)
except Exception:
    pass
